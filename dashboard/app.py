"""
dashboard — Fase 6.

Interface visual para o fluxo de human-in-the-loop. Consome os mesmos
endpoints do agent-orchestrator:
  - GET  /pending               -> incidentes aguardando aprovação
  - POST /approve/{thread_id}   -> aprova/rejeita
  - GET  /incidents             -> incidentes já concluídos
"""
import os

import httpx
import streamlit as st
from streamlit_autorefresh import st_autorefresh

AGENT_ORCHESTRATOR_URL = os.environ.get("AGENT_ORCHESTRATOR_URL", "http://agent-orchestrator:8001")

st.set_page_config(page_title="Incident Copilot", layout="wide")

# Atualiza a página inteira a cada 5s automaticamente — assim novos
# incidentes (ou resoluções automáticas) aparecem sem precisar clicar
# em nada. `key` fixo evita que o Streamlit recrie o componente do zero
# a cada rerun.
st_autorefresh(interval=5000, key="auto_refresh_incidentes")


def _get(path: str) -> dict | None:
    try:
        resposta = httpx.get(f"{AGENT_ORCHESTRATOR_URL}{path}", timeout=10)
        resposta.raise_for_status()
        return resposta.json()
    except Exception as e:
        st.error(f"Não foi possível falar com o agent-orchestrator ({path}): {e}")
        return None


def _approve(thread_id: str, approved: bool) -> None:
    try:
        resposta = httpx.post(
            f"{AGENT_ORCHESTRATOR_URL}/approve/{thread_id}",
            json={"approved": approved},
            timeout=30,
        )
        resposta.raise_for_status()
    except Exception as e:
        st.error(f"Falha ao enviar decisão: {e}")


def _cor_severidade(severidade: str):
    """Escolhe o componente visual do Streamlit de acordo com a
    severidade — um jeito simples de dar destaque visual sem precisar
    de CSS customizado."""
    mapa = {
        "critica": st.error,
        "alta": st.error,
        "media": st.warning,
        "baixa": st.info,
    }
    return mapa.get((severidade or "").lower(), st.info)


st.title("🚨 Incident Copilot — Painel de Aprovação")
st.caption(
    "Diagnósticos gerados por agentes de IA (LangGraph + RAG) aguardando "
    "revisão humana antes de qualquer ação corretiva ser executada. "
    "Atualiza automaticamente a cada 5s."
)

pendentes_resp = _get("/pending")
pendentes = (pendentes_resp or {}).get("pendentes", {})

processando_resp = _get("/processing")
processando = (processando_resp or {}).get("processando", {})

incidentes_resp = _get("/incidents")
incidentes = (incidentes_resp or {}).get("incidentes", {})

# Coluna da esquerda (mais larga) para o que precisa de atenção humana
# AGORA; coluna da direita (mais estreita) para o histórico, que é só
# consulta.
col_pendentes, col_concluidos = st.columns([2, 1])

with col_pendentes:
    st.header("Aguardando ação humana")

    if not pendentes and not processando:
        st.success("Nenhum incidente em andamento no momento.")

    # "Em análise" primeiro — é o mais recente/urgente de acompanhar,
    # já que o diagnóstico ainda está sendo gerado.
    for thread_id, info in processando.items():
        with st.container(border=True):
            st.subheader(info.get("alert_summary", "Alerta sem resumo"))
            st.info("🧠 Analisando o incidente... (buscando runbooks e consultando o LLM)")
            st.caption(f"thread_id: `{thread_id}`")

    for thread_id, incidente in pendentes.items():
        with st.container(border=True):
            st.subheader(incidente.get("alert_summary", "Alerta sem resumo"))

            col_info, col_acao = st.columns([3, 1])

            with col_info:
                st.markdown(f"**Diagnóstico:** {incidente.get('diagnosis')}")
                st.markdown(f"**Ação recomendada:** {incidente.get('recommended_action')}")

                severidade = incidente.get("severity_assessed", "desconhecida")
                _cor_severidade(severidade)(f"Severidade avaliada pelo agente: **{severidade}**")

                action_type = incidente.get("action_type")
                target = incidente.get("target_container")
                if action_type == "restart_container":
                    st.markdown(f"⚙️ Ação automatizável: **reiniciar container `{target}`**")
                else:
                    st.markdown("⚙️ Ação **não** automatizável — requer intervenção manual mesmo se aprovada")

                st.caption(f"thread_id: `{thread_id}`")

            with col_acao:
                if st.button("✅ Aprovar", key=f"aprovar_{thread_id}", use_container_width=True):
                    _approve(thread_id, True)
                    st.rerun()
                if st.button("❌ Rejeitar", key=f"rejeitar_{thread_id}", use_container_width=True):
                    _approve(thread_id, False)
                    st.rerun()

with col_concluidos:
    st.header("Concluídos")

    if not incidentes:
        st.caption("Nenhum incidente concluído ainda.")
    else:
        for thread_id, incidente in reversed(list(incidentes.items())):
            aprovado = incidente.get("approved")
            auto_resolvido = incidente.get("auto_resolved")
            if auto_resolvido:
                icone = "⏱️"
            elif aprovado:
                icone = "✅"
            else:
                icone = "❌"

            diagnostico_curto = (incidente.get("diagnosis") or "Sem diagnóstico")[:60]
            with st.expander(f"{icone} {diagnostico_curto}..."):
                st.markdown(f"**Diagnóstico:** {incidente.get('diagnosis')}")
                st.markdown(f"**Ação recomendada:** {incidente.get('recommended_action')}")
                if auto_resolvido:
                    st.markdown("**Resolvido automaticamente** — ninguém aprovou/rejeitou a tempo")
                else:
                    st.markdown(f"**Aprovado:** {'Sim' if aprovado else 'Não'}")
                st.markdown(f"**Resultado da ação:** {incidente.get('action_result')}")
                st.caption(f"thread_id: `{thread_id}`")
