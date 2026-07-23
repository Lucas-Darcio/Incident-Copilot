"""
Grafo multi-agente da Fase 4.

Três agentes em sequência:
  1. triage_node    - interpreta o alerta bruto do Alertmanager
  2. retrieve_node  - busca runbooks relevantes no rag-service (Fase 3)
  3. diagnose_node  - usa o LLM para sintetizar diagnóstico + ação

Ainda não há aprovação humana aqui — isso entra na Fase 5, quando um
nó adicional vai pausar o grafo com `interrupt()` antes de qualquer
ação corretiva real.
"""
import json
import os
from typing import Optional, TypedDict

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

RAG_SERVICE_URL = os.environ.get("RAG_SERVICE_URL", "http://rag-service:8002")


class IncidentState(TypedDict):
    alert_raw: dict
    alert_summary: str
    severity_original: str
    retrieved_runbooks: list
    diagnosis: Optional[str]
    recommended_action: Optional[str]
    severity_assessed: Optional[str]


# GOOGLE_API_KEY é lido automaticamente da variável de ambiente pelo
# próprio SDK do Google — não precisamos passá-la explicitamente aqui.
llm = ChatGoogleGenerativeAI(
    model="gemma-4-31b-it",
    temperature=0.6,
    max_output_tokens=1024,
)


def triage_node(state: IncidentState) -> dict:
    """
    Agente 1 - Triagem: extrai um resumo em texto do payload bruto do
    Alertmanager. Esse resumo vira a query de busca semântica no RAG,
    então a qualidade dele importa bastante para o resultado final.
    """
    alerts = state["alert_raw"].get("alerts", [])
    if not alerts:
        return {
            "alert_summary": "Alerta recebido sem detalhes (payload vazio).",
            "severity_original": "desconhecida",
        }

    primeiro_alerta = alerts[0]
    labels = primeiro_alerta.get("labels", {})
    annotations = primeiro_alerta.get("annotations", {})

    alertname = labels.get("alertname", "AlertaDesconhecido")
    summary = annotations.get("summary", "")
    description = annotations.get("description", "")

    alert_summary = f"{alertname}: {summary}. {description}".strip()
    severity_original = labels.get("severity", "desconhecida")

    return {"alert_summary": alert_summary, "severity_original": severity_original}


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
    Normaliza o `.content` da resposta do LLM. Dependendo do modelo e da
    versão do LangChain, isso pode vir como uma string simples OU como
    uma lista de "blocos" de conteúdo (ex: [{"type": "text", "text": "..."}]),
    formato mais novo que suporta conteúdo misto (texto, chamadas de
    ferramenta, etc). Aqui extraímos só o texto, não importa qual formato
    veio.
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
        return "".join(partes)
    return str(content)


def _parse_json_response(texto: str) -> dict:
    """
    Pedimos ao LLM para responder em JSON, mas modelos menores às vezes
    envolvem a resposta em blocos de código markdown (```json ... ```).
    Esta função limpa isso antes do parse, e tem um fallback caso o
    modelo não retorne um JSON válido de jeito nenhum.
    """
    texto = texto.strip()
    if texto.startswith("```"):
        texto = texto.strip("`").strip()
        if texto.lower().startswith("json"):
            texto = texto[4:].strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        return {
            "causa_provavel": texto,
            "acao_recomendada": "Não foi possível interpretar uma ação estruturada a partir da resposta do modelo — revisar manualmente.",
            "severidade": "desconhecida",
        }


def diagnose_node(state: IncidentState) -> dict:
    """
    Agente 3 - Diagnóstico: recebe o alerta + os runbooks recuperados e
    usa o LLM para sintetizar uma causa provável e uma ação recomendada,
    seguindo o mesmo raciocínio que um analista humano seguiria lendo
    os mesmos documentos.
    """
    contexto = "\n\n---\n\n".join(
        f"[{r['source']} / {r['section']}]\n{r['text']}"
        for r in state["retrieved_runbooks"]
    )

    system_prompt = (
        "Você é um agente de diagnóstico de incidentes de infraestrutura. "
        "Use os runbooks fornecidos como referência para diagnosticar o "
        "alerta recebido. Responda ESTRITAMENTE em JSON válido, sem texto "
        "fora do JSON, no seguinte formato: "
        '{"causa_provavel": "...", "acao_recomendada": "...", '
        '"severidade": "baixa|media|alta|critica"}'
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

    return {
        "diagnosis": parsed.get("causa_provavel"),
        "recommended_action": parsed.get("acao_recomendada"),
        "severity_assessed": parsed.get("severidade"),
    }


def build_graph():
    graph = StateGraph(IncidentState)
    graph.add_node("triage", triage_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("diagnose", diagnose_node)

    graph.add_edge(START, "triage")
    graph.add_edge("triage", "retrieve")
    graph.add_edge("retrieve", "diagnose")
    graph.add_edge("diagnose", END)

    # Checkpointer em memória (RAM do processo): guarda o estado de cada
    # execução associado a um thread_id. Na Fase 5 isso vira um
    # checkpointer Postgres — necessário porque o interrupt() de
    # aprovação humana precisa sobreviver mesmo que o container reinicie
    # enquanto espera alguém aprovar a ação.
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


incident_graph = build_graph()
