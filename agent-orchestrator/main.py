"""
agent-orchestrator — Fase 4.

Recebe o webhook do Alertmanager e dispara o grafo multi-agente
(triagem -> retrieval -> diagnóstico) em segundo plano.

Por que em segundo plano (BackgroundTasks) e não de forma síncrona
-------------------------------------------------------------------
O Alertmanager cancela a espera pela resposta do webhook depois de um
tempo definido por `group_interval` (configurado em alertmanager.yml).
Como nosso processamento envolve uma chamada de rede ao RAG e ao LLM,
ele pode facilmente ultrapassar esse tempo — o que fazia o Alertmanager
logar "notify retry canceled: context deadline exceeded", mesmo que o
diagnóstico tivesse terminado normalmente.

A correção: responder OK imediatamente (aceitando o alerta), e deixar
o processamento pesado rodar depois, em background. O resultado fica
disponível para consulta em GET /incidents/{fingerprint}.

Deduplicação de alertas
-----------------------
O Alertmanager reenvia um alerta `firing` periodicamente enquanto ele
continuar ativo (`repeat_interval`). Reenvios do mesmo `fingerprint`
são ignorados; o controle é liberado quando o alerta é `resolved`,
garantindo que um incidente futuro do mesmo tipo seja tratado como novo.
"""
import uuid

from fastapi import BackgroundTasks, FastAPI, Request
from pydantic import BaseModel

from graph import incident_graph

app = FastAPI(title="agent-orchestrator")

# Controles em memória (RAM do processo) — zeram se o container
# reiniciar. Suficiente para esta fase; migra para algo persistente
# quando o checkpointer virar Postgres.
_alertas_em_tratamento: dict[str, str] = {}   # fingerprint -> thread_id
_diagnosticos: dict[str, dict] = {}           # fingerprint -> resultado


def _rodar_diagnostico(payload: dict, thread_id: str, fingerprint: str) -> None:
    """Executado em background pelo BackgroundTasks, depois que a
    resposta HTTP já foi enviada ao Alertmanager."""
    config = {"configurable": {"thread_id": thread_id}}
    resultado = incident_graph.invoke({"alert_raw": payload}, config=config)

    _diagnosticos[fingerprint] = {
        "thread_id": thread_id,
        "alert_summary": resultado.get("alert_summary"),
        "diagnosis": resultado.get("diagnosis"),
        "recommended_action": resultado.get("recommended_action"),
        "severity_assessed": resultado.get("severity_assessed"),
    }

    print("=" * 60)
    print(f"[agent-orchestrator] thread_id={thread_id} fingerprint={fingerprint}")
    print(f"  alerta: {resultado.get('alert_summary')}")
    print(f"  diagnóstico: {resultado.get('diagnosis')}")
    print(f"  ação recomendada: {resultado.get('recommended_action')}")
    print(f"  severidade avaliada: {resultado.get('severity_assessed')}")
    print("=" * 60)


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
        print(f"[agent-orchestrator] alerta RESOLVIDO (fingerprint={fingerprint}) — liberado para novo diagnóstico no futuro")
        return {"status": "resolved_acknowledged", "fingerprint": fingerprint, "thread_id": thread_id_antigo}

    if fingerprint in _alertas_em_tratamento:
        thread_id = _alertas_em_tratamento[fingerprint]
        print(f"[agent-orchestrator] alerta {fingerprint} já está sendo tratado (thread_id={thread_id}) — ignorando reenvio")
        return {"status": "duplicate_ignored", "fingerprint": fingerprint, "thread_id": thread_id}

    thread_id = str(uuid.uuid4())
    _alertas_em_tratamento[fingerprint] = thread_id

    # Responde IMEDIATAMENTE (sem esperar o grafo terminar) — o
    # processamento de verdade só começa depois que essa resposta sai.
    background_tasks.add_task(_rodar_diagnostico, payload, thread_id, fingerprint)

    return {"status": "accepted", "thread_id": thread_id, "fingerprint": fingerprint}


@app.get("/incidents")
def list_incidents():
    """Lista todos os diagnósticos já concluídos, mais recentes primeiro."""
    return {"incidentes": _diagnosticos}


@app.get("/incidents/{fingerprint}")
def get_incident(fingerprint: str):
    """Consulta o diagnóstico de um incidente específico pelo fingerprint."""
    resultado = _diagnosticos.get(fingerprint)
    if resultado is None:
        return {"status": "ainda_processando_ou_nao_encontrado", "fingerprint": fingerprint}
    return resultado


class DiagnoseRequest(BaseModel):
    """Payload simplificado para testar o grafo diretamente, sem
    depender do formato exato do Alertmanager nem esperar em background
    — útil durante desenvolvimento."""
    alertname: str
    summary: str
    description: str = ""
    severity: str = "critical"


@app.post("/diagnose")
def diagnose_synchronous(req: DiagnoseRequest):
    """
    Endpoint de teste manual: roda o grafo de forma SÍNCRONA (espera
    terminar e devolve o resultado na hora). Não é o caminho que o
    Alertmanager usa (esse é o /webhook, assíncrono) — este aqui existe
    só para facilitar testes durante o desenvolvimento.
    """
    payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": req.alertname, "severity": req.severity},
                "annotations": {"summary": req.summary, "description": req.description},
            }
        ]
    }
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    resultado = incident_graph.invoke({"alert_raw": payload}, config=config)

    return {
        "thread_id": thread_id,
        "alert_summary": resultado.get("alert_summary"),
        "diagnosis": resultado.get("diagnosis"),
        "recommended_action": resultado.get("recommended_action"),
        "severity_assessed": resultado.get("severity_assessed"),
    }


@app.get("/health")
def health():
    return {"status": "ok", "alertas_em_tratamento": len(_alertas_em_tratamento)}
