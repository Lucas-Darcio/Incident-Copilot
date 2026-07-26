"""
agent-orchestrator — Fase 5/6.

Recebe o webhook do Alertmanager e dispara o grafo multi-agente em
segundo plano. O grafo PAUSA antes de qualquer ação corretiva real,
esperando aprovação humana via POST /approve/{thread_id}.

Estado "em processamento" (novo)
---------------------------------
A chamada ao LLM (Google) + a busca no RAG levam alguns segundos. Sem
um estado intermediário, o dashboard ficava "mudo" até o diagnóstico
inteiro terminar. Agora, assim que o alerta chega, ele já aparece como
"em análise" (com um resumo básico, extraído na hora, sem esperar o
LLM) — e só vira "aguardando aprovação" quando o diagnóstico terminar.

Endpoints:
  POST /webhook              - recebido pelo Alertmanager
  POST /diagnose              - teste manual (cria um incidente sem Alertmanager)
  GET  /processing             - incidentes em análise (LLM ainda rodando)
  GET  /pending                - lista incidentes aguardando aprovação humana
  GET  /pending/{thread_id}    - detalhe de um incidente pendente
  POST /approve/{thread_id}    - aprova ou rejeita a ação recomendada
  GET  /incidents              - lista incidentes já concluídos (aprovados/rejeitados)
  GET  /incidents/{thread_id}  - detalhe de um incidente concluído
  GET  /health
"""
import logging
import uuid

from fastapi import BackgroundTasks, FastAPI, Request
from langgraph.types import Command
from pydantic import BaseModel

from graph import incident_graph
from parsing import extrair_info_alerta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("agent-orchestrator.main")

app = FastAPI(title="agent-orchestrator")

# Controles em memória (RAM do processo) — o ESTADO DO GRAFO em si já
# está seguro no Postgres (checkpointer). Isso aqui é só um índice
# auxiliar para facilitar consulta via API sem precisar vasculhar o
# checkpointer diretamente.
_alertas_em_tratamento: dict[str, str] = {}   # fingerprint -> thread_id
_processando: dict[str, dict] = {}            # thread_id -> resumo básico (LLM ainda rodando)
_pendentes: dict[str, dict] = {}              # thread_id -> payload do interrupt()
_diagnosticos: dict[str, dict] = {}           # thread_id -> resultado final


def _extrair_interrupt(resultado: dict):
    """Se o grafo pausou, o resultado do invoke() traz a chave especial
    '__interrupt__' com o valor passado para interrupt() dentro do nó."""
    interrupts = resultado.get("__interrupt__")
    if interrupts:
        return interrupts[0].value
    return None


def _rodar_ate_aprovacao(payload: dict, thread_id: str, fingerprint: str | None) -> None:
    """Executado em background: roda o grafo até ele pausar no nó de
    aprovação humana (ou terminar/falhar, cobrindo os dois casos)."""
    try:
        config = {"configurable": {"thread_id": thread_id}}
        resultado = incident_graph.invoke({"alert_raw": payload}, config=config)

        interrupt_payload = _extrair_interrupt(resultado)
        if interrupt_payload:
            if fingerprint:
                interrupt_payload = {**interrupt_payload, "fingerprint": fingerprint}
            _pendentes[thread_id] = interrupt_payload
            logger.info("thread_id=%s AGUARDANDO APROVAÇÃO HUMANA | diagnóstico: %s | ação: %s", thread_id, interrupt_payload.get('diagnosis'), interrupt_payload.get('recommended_action'))
        else:
            # Não deveria acontecer no fluxo normal (o grafo sempre para
            # no human_approval), mas cobrimos o caso de qualquer forma.
            _diagnosticos[thread_id] = resultado
            logger.warning("thread_id=%s concluiu sem pausar (inesperado)", thread_id)
    except Exception as e:
        # Sem isso, uma falha aqui (ex: API do Google fora do ar, cota
        # excedida, rag-service indisponível) faria o incidente
        # simplesmente DESAPARECER — preso em _processando para sempre,
        # sem nenhuma indicação de erro em lugar nenhum.
        logger.exception("Erro ao processar thread_id=%s", thread_id)
        _diagnosticos[thread_id] = {
            "thread_id": thread_id,
            "fingerprint": fingerprint,
            "erro": True,
            "action_result": f"Falha ao processar o incidente: {e}",
        }
    finally:
        _processando.pop(thread_id, None)


@app.post("/webhook")
async def receive_alert(request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()
    alerts = payload.get("alerts", [])

    if not alerts:
        return {"status": "ignorado", "motivo": "payload sem alertas"}

    primeiro_alerta = alerts[0]
    fingerprint = primeiro_alerta.get("fingerprint", "sem-fingerprint")
    status = primeiro_alerta.get("status", "firing")

    if status == "resolved":
        thread_id_antigo = _alertas_em_tratamento.pop(fingerprint, None)
        logger.info("Alerta RESOLVIDO (fingerprint=%s) — liberado para novo diagnóstico no futuro", fingerprint)

        # Se o incidente ainda estava esperando uma decisão humana quando
        # o alerta resolveu sozinho (ex: o stress-ng atingiu o timeout de
        # 120s antes de alguém aprovar/rejeitar), retomamos o grafo com
        # approved=False — nenhuma ação é executada, porque não faz
        # sentido "corrigir" um problema que já desapareceu — e movemos o
        # incidente para "concluídos", ao invés de deixá-lo pendente para
        # sempre.
        if thread_id_antigo and thread_id_antigo in _pendentes:
            config = {"configurable": {"thread_id": thread_id_antigo}}
            resultado = incident_graph.invoke(Command(resume={"approved": False}), config=config)
            pendente = _pendentes.pop(thread_id_antigo, {})

            _diagnosticos[thread_id_antigo] = {
                "thread_id": thread_id_antigo,
                "fingerprint": fingerprint,
                "approved": False,
                "auto_resolved": True,
                "diagnosis": pendente.get("diagnosis"),
                "recommended_action": pendente.get("recommended_action"),
                "action_result": (
                    "Alert resolved automatically before a human decision "
                    "(e.g., the problem went away on its own, or the test "
                    "timeout expired) — no corrective action was executed."
                ),
            }
            logger.info("thread_id=%s auto-resolvido (estava pendente)", thread_id_antigo)

        return {"status": "resolved_acknowledged", "fingerprint": fingerprint, "thread_id": thread_id_antigo}

    if fingerprint in _alertas_em_tratamento:
        thread_id = _alertas_em_tratamento[fingerprint]
        logger.info("Alerta %s já está sendo tratado (thread_id=%s) — ignorando reenvio", fingerprint, thread_id)
        return {"status": "duplicate_ignored", "fingerprint": fingerprint, "thread_id": thread_id}

    thread_id = str(uuid.uuid4())
    _alertas_em_tratamento[fingerprint] = thread_id

    # Registra o "em análise" IMEDIATAMENTE, antes de qualquer chamada
    # lenta (RAG, LLM) — é isso que faz o dashboard mostrar o alerta na
    # hora, ao invés de só quando o diagnóstico completo estiver pronto.
    # extrair_info_alerta() é pura interpretação de texto (sem I/O), por
    # isso é seguro chamar diretamente aqui, fora do grafo.
    _processando[thread_id] = extrair_info_alerta(payload)

    background_tasks.add_task(_rodar_ate_aprovacao, payload, thread_id, fingerprint)

    return {"status": "accepted", "thread_id": thread_id, "fingerprint": fingerprint}


class DiagnoseRequest(BaseModel):
    """Payload simplificado para testar o grafo diretamente, sem
    depender do formato exato do Alertmanager."""
    alertname: str
    summary: str
    description: str = ""
    severity: str = "critical"
    instance: str = "app-fake:8000"


@app.post("/diagnose")
def diagnose_synchronous(req: DiagnoseRequest):
    """
    Endpoint de teste manual: roda o grafo SINCRONAMENTE até ele pausar
    no nó de aprovação humana, e devolve o que seria mostrado a um
    humano. Use POST /approve/{thread_id} em seguida para continuar.
    """
    payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": req.alertname, "severity": req.severity, "instance": req.instance},
                "annotations": {"summary": req.summary, "description": req.description},
            }
        ]
    }
    thread_id = str(uuid.uuid4())
    _processando[thread_id] = extrair_info_alerta(payload)

    config = {"configurable": {"thread_id": thread_id}}
    try:
        resultado = incident_graph.invoke({"alert_raw": payload}, config=config)
    finally:
        _processando.pop(thread_id, None)

    interrupt_payload = _extrair_interrupt(resultado)
    if interrupt_payload:
        _pendentes[thread_id] = interrupt_payload
        return {"thread_id": thread_id, "status": "pending_approval", **interrupt_payload}

    return {"thread_id": thread_id, "status": "concluido_sem_pausa", **resultado}


@app.get("/processing")
def list_processing():
    return {"processando": _processando}


@app.get("/pending")
def list_pending():
    return {"pendentes": _pendentes}


@app.get("/pending/{thread_id}")
def get_pending(thread_id: str):
    pendente = _pendentes.get(thread_id)
    if pendente is None:
        return {"status": "nao_encontrado_ou_ja_processado", "thread_id": thread_id}
    return pendente


class ApprovalRequest(BaseModel):
    approved: bool


@app.post("/approve/{thread_id}")
def approve(thread_id: str, req: ApprovalRequest):
    """
    Retoma o grafo a partir do ponto onde ele pausou, passando a decisão
    humana. É isso que faz `interrupt()` (dentro do nó) devolver
    {"approved": True/False} para o código do human_approval_node.
    """
    if thread_id not in _pendentes:
        return {"status": "nao_encontrado_ou_ja_processado", "thread_id": thread_id}

    config = {"configurable": {"thread_id": thread_id}}
    resultado = incident_graph.invoke(Command(resume={"approved": req.approved}), config=config)

    pendente = _pendentes.pop(thread_id, {})
    fingerprint = pendente.get("fingerprint")

    resultado_final = {
        "thread_id": thread_id,
        "fingerprint": fingerprint,
        "approved": req.approved,
        "diagnosis": resultado.get("diagnosis"),
        "recommended_action": resultado.get("recommended_action"),
        "action_result": resultado.get("action_result"),
    }
    _diagnosticos[thread_id] = resultado_final

    logger.info("thread_id=%s aprovado=%s | resultado da ação: %s", thread_id, req.approved, resultado.get('action_result'))

    return resultado_final


@app.get("/incidents")
def list_incidents():
    return {"incidentes": _diagnosticos}


@app.get("/incidents/{thread_id}")
def get_incident(thread_id: str):
    resultado = _diagnosticos.get(thread_id)
    if resultado is None:
        return {"status": "ainda_nao_concluido_ou_nao_encontrado", "thread_id": thread_id}
    return resultado


@app.get("/health")
def health():
    return {
        "status": "ok",
        "alertas_em_tratamento": len(_alertas_em_tratamento),
        "em_analise": len(_processando),
        "aguardando_aprovacao": len(_pendentes),
    }
