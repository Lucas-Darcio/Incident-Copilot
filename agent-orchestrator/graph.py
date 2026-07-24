"""
Grafo multi-agente — Fase 5.

Cinco passos em sequência:
  1. triage_node          - interpreta o alerta bruto do Alertmanager
  2. retrieve_node        - busca runbooks relevantes no rag-service (Fase 3)
  3. diagnose_node        - usa o LLM para sintetizar diagnóstico + ação
  4. human_approval_node  - PAUSA o grafo (interrupt()) esperando aprovação humana
  5. execute_action_node  - só roda DEPOIS da aprovação; executa a ação real
                            via Docker SDK (ex: reiniciar o container afetado)
"""
import json
import os
import re
from typing import Optional, TypedDict

import docker
import httpx
import psycopg
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from psycopg.rows import dict_row

RAG_SERVICE_URL = os.environ.get("RAG_SERVICE_URL", "http://rag-service:8002")
POSTGRES_URI = os.environ.get("POSTGRES_URI")


class IncidentState(TypedDict):
    alert_raw: dict
    alert_summary: str
    severity_original: str
    target_container: Optional[str]
    retrieved_runbooks: list
    diagnosis: Optional[str]
    recommended_action: Optional[str]
    severity_assessed: Optional[str]
    action_type: Optional[str]
    approved: Optional[bool]
    action_result: Optional[str]


llm = ChatGoogleGenerativeAI(
    model="gemma-4-31b-it",
    temperature=0.6,
    max_output_tokens=1024,
)


def triage_node(state: IncidentState) -> dict:
    """
    Agente 1 - Triagem: extrai um resumo em texto do payload bruto do
    Alertmanager, além do nome do container afetado (extraído da label
    `instance`, no formato "nome:porta") — é esse nome que o nó de ação
    vai usar para saber QUAL container reiniciar, se for aprovado.
    """
    alerts = state["alert_raw"].get("alerts", [])
    if not alerts:
        return {
            "alert_summary": "Alerta recebido sem detalhes (payload vazio).",
            "severity_original": "desconhecida",
            "target_container": None,
        }

    primeiro_alerta = alerts[0]
    labels = primeiro_alerta.get("labels", {})
    annotations = primeiro_alerta.get("annotations", {})

    alertname = labels.get("alertname", "AlertaDesconhecido")
    summary = annotations.get("summary", "")
    description = annotations.get("description", "")
    instance = labels.get("instance", "")

    alert_summary = f"{alertname}: {summary}. {description}".strip()
    severity_original = labels.get("severity", "desconhecida")
    target_container = instance.split(":")[0] if instance else None

    return {
        "alert_summary": alert_summary,
        "severity_original": severity_original,
        "target_container": target_container,
    }


def retrieve_node(state: IncidentState) -> dict:
    """
    Agente 2 - Retrieval: usa o resumo do alerta para buscar os runbooks
    mais relevantes no rag-service (o mesmo endpoint /search da Fase 3).
    """
    response = httpx.post(
        f"{RAG_SERVICE_URL}/search",
        json={"query": state["alert_summary"], "top_k": 3},
        timeout=30,
    )
    response.raise_for_status()
    resultados = response.json()["resultados"]
    return {"retrieved_runbooks": resultados}


def _extract_text(content) -> str:
    """
    Normaliza o `.content` da resposta do LLM (string ou lista de blocos).
    Alguns blocos podem vir como objetos (não dict/str) dependendo da
    versão do SDK — por isso o `getattr` como última tentativa, ao invés
    de simplesmente descartar o bloco silenciosamente (o que cortaria o
    texto no meio sem nenhum aviso).
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        partes = []
        for bloco in content:
            if isinstance(bloco, str):
                partes.append(bloco)
            elif isinstance(bloco, dict):
                partes.append(bloco.get("text", ""))
            else:
                partes.append(getattr(bloco, "text", "") or str(bloco))
        return "".join(partes)
    return str(content)


_CAMPO_REGEX = {
    # A aspas de fechamento é opcional (`"?`) de propósito: se a resposta
    # do modelo foi truncada no meio de uma string, não existe aspas de
    # fechamento, e sem essa flexibilidade o valor inteiro seria perdido.
    "causa_provavel": r'"causa_provavel"\s*:\s*"([^"]*)"?',
    "acao_recomendada": r'"acao_recomendada"\s*:\s*"([^"]*)"?',
    "severidade": r'"severidade"\s*:\s*"([^"]*)"?',
    "acao_automatizavel": r'"acao_automatizavel"\s*:\s*(true|false)',
}


def _recuperar_campos_parciais(texto: str) -> Optional[dict]:
    """
    Segunda linha de defesa: se o JSON vier malformado ou cortado (ex:
    resposta truncada no meio), tenta recuperar os campos individualmente
    via regex, ao invés de descartar tudo. Modelos menores/mais baratos
    (como o Gemma) ocasionalmente truncam ou geram JSON levemente
    inválido — isso recupera o que der, e usa "revisao_manual" como
    padrão seguro para o que não conseguir recuperar.
    """
    campos = {}
    for campo, padrao in _CAMPO_REGEX.items():
        match = re.search(padrao, texto)
        if match:
            campos[campo] = match.group(1)

    if not campos:
        return None

    return {
        "causa_provavel": campos.get("causa_provavel", texto[:500]),
        "acao_recomendada": campos.get(
            "acao_recomendada",
            "Resposta do modelo parcialmente corrompida — revisar manualmente.",
        ),
        "severidade": campos.get("severidade", "desconhecida"),
        # Padrão seguro: se não conseguimos confirmar que é automatizável,
        # tratamos como NÃO automatizável — a dúvida nunca deve resultar
        # em uma ação automática.
        "acao_automatizavel": campos.get("acao_automatizavel") == "true",
    }


def _parse_json_response(texto: str) -> dict:
    """
    Tenta, em ordem:
    1. Parse de JSON completo e válido (removendo blocos de código
       markdown, se houver)
    2. Recuperação parcial via regex (se o JSON veio truncado/malformado)
    3. Fallback total: texto bruto como causa_provavel, sem automação
    """
    texto_limpo = texto.strip()
    if texto_limpo.startswith("```"):
        texto_limpo = texto_limpo.strip("`").strip()
        if texto_limpo.lower().startswith("json"):
            texto_limpo = texto_limpo[4:].strip()

    try:
        return json.loads(texto_limpo)
    except json.JSONDecodeError:
        pass

    recuperado = _recuperar_campos_parciais(texto)
    if recuperado:
        return recuperado

    return {
        "causa_provavel": texto,
        "acao_recomendada": "Não foi possível interpretar uma ação estruturada a partir da resposta do modelo — revisar manualmente.",
        "severidade": "desconhecida",
        "acao_automatizavel": False,
    }


def diagnose_node(state: IncidentState) -> dict:
    """
    Agente 3 - Diagnóstico: sintetiza causa provável + ação recomendada,
    e decide se a ação é automatizável (hoje, a única ação automatizável
    deste projeto é reiniciar o container afetado).
    """
    contexto = "\n\n---\n\n".join(
        f"[{r['source']} / {r['section']}]\n{r['text']}"
        for r in state["retrieved_runbooks"]
    )

    system_prompt = (
        "Você é um agente de diagnóstico de incidentes de infraestrutura. "
        "Use os runbooks fornecidos como referência para diagnosticar o "
        "alerta recebido. A única ação automatizável disponível neste "
        "sistema é REINICIAR O CONTAINER afetado — se essa for a ação "
        "recomendada pelo runbook, marque acao_automatizavel como true; "
        "para qualquer outra ação (escalar, revisar código, etc.), marque "
        "como false, pois exige revisão humana manual. "
        "Responda ESTRITAMENTE em JSON válido, sem texto fora do JSON, "
        "no seguinte formato: "
        '{"causa_provavel": "...", "acao_recomendada": "...", '
        '"severidade": "baixa|media|alta|critica", '
        '"acao_automatizavel": true|false}'
    )
    human_prompt = (
        f"Alerta recebido: {state['alert_summary']}\n"
        f"Severidade original do alerta: {state['severity_original']}\n\n"
        f"Runbooks relevantes encontrados:\n{contexto}"
    )

    resposta = llm.invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
    )
    parsed = _parse_json_response(_extract_text(resposta.content))

    acao_automatizavel = bool(parsed.get("acao_automatizavel", False))
    action_type = "restart_container" if acao_automatizavel else "revisao_manual"

    return {
        "diagnosis": parsed.get("causa_provavel"),
        "recommended_action": parsed.get("acao_recomendada"),
        "severity_assessed": parsed.get("severidade"),
        "action_type": action_type,
    }


def human_approval_node(state: IncidentState) -> dict:
    """
    Agente 4 - Aprovação humana: PAUSA a execução do grafo aqui. O valor
    passado para interrupt() é exatamente o que fica disponível para o
    humano revisar (via GET /pending). A execução só continua quando
    alguém chamar POST /approve com Command(resume={"approved": ...}).
    """
    decisao = interrupt(
        {
            "alert_summary": state["alert_summary"],
            "diagnosis": state["diagnosis"],
            "recommended_action": state["recommended_action"],
            "severity_assessed": state["severity_assessed"],
            "action_type": state.get("action_type"),
            "target_container": state.get("target_container"),
        }
    )
    return {"approved": bool(decisao.get("approved", False))}


def execute_action_node(state: IncidentState) -> dict:
    """
    Agente 5 - Execução: só chega aqui DEPOIS que human_approval_node foi
    retomado. Executa a ação real via Docker SDK, acessando o socket do
    Docker do host (montado como volume no docker-compose.yml).

    Atenção de segurança: montar o socket do Docker dentro de um
    container equivale, na prática, a dar acesso root ao host para esse
    container. Isso é aceitável aqui porque é um projeto de portfólio
    rodando localmente, mas em produção o recomendado é isolar isso
    atrás de uma API intermediária com escopo restrito (allowlist de
    comandos), não dar acesso livre ao socket.
    """
    if not state.get("approved"):
        return {"action_result": "Ação REJEITADA pelo humano — nenhuma alteração foi feita no sistema."}

    if state.get("action_type") != "restart_container" or not state.get("target_container"):
        return {
            "action_result": (
                "Ação aprovada, mas não é uma ação automatizável neste "
                "projeto (ex: escalar réplicas, revisar código) — "
                "requer intervenção manual de um engenheiro."
            )
        }

    try:
        client = docker.from_env()
        container = client.containers.get(state["target_container"])
        container.restart()
        return {"action_result": f"Container '{state['target_container']}' reiniciado com sucesso."}
    except docker.errors.NotFound:
        return {"action_result": f"Container '{state['target_container']}' não encontrado — verifique o nome."}
    except Exception as e:
        return {"action_result": f"Falha ao executar ação corretiva: {e}"}


def _build_checkpointer():
    """
    Postgres se POSTGRES_URI estiver configurado (produção/Fase 5+);
    cai para memória (RAM) se não estiver — útil para rodar testes
    rápidos sem subir o Postgres, mas SEM sobreviver a restarts.
    """
    if not POSTGRES_URI:
        print("[agent-orchestrator] POSTGRES_URI não configurado — usando checkpointer em memória (não sobrevive a restarts)")
        return MemorySaver()

    # autocommit=True e row_factory=dict_row são exigidos pelo PostgresSaver
    # quando se passa uma conexão já criada manualmente (ao invés de usar
    # o context manager from_conn_string) — necessário para manter a
    # conexão aberta durante toda a vida do processo FastAPI.
    conn = psycopg.connect(POSTGRES_URI, autocommit=True, row_factory=dict_row)
    checkpointer = PostgresSaver(conn)
    checkpointer.setup()  # idempotente: cria as tabelas se ainda não existirem
    print("[agent-orchestrator] checkpointer Postgres conectado e configurado")
    return checkpointer


def build_graph():
    graph = StateGraph(IncidentState)
    graph.add_node("triage", triage_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("diagnose", diagnose_node)
    graph.add_node("human_approval", human_approval_node)
    graph.add_node("execute_action", execute_action_node)

    graph.add_edge(START, "triage")
    graph.add_edge("triage", "retrieve")
    graph.add_edge("retrieve", "diagnose")
    graph.add_edge("diagnose", "human_approval")
    graph.add_edge("human_approval", "execute_action")
    graph.add_edge("execute_action", END)

    checkpointer = _build_checkpointer()
    return graph.compile(checkpointer=checkpointer)


incident_graph = build_graph()
