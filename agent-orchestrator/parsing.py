"""
Funções puras de interpretação de texto — sem chamadas de rede, sem
LLM, sem Docker. Separadas em módulo próprio de propósito: isso deixa
essa lógica testável com `pytest` puro, sem precisar instalar
LangChain/LangGraph/Docker SDK só para rodar os testes (ver tests/).
"""
import json
import re
from typing import Optional


def extrair_info_alerta(alert_raw: dict) -> dict:
    """
    Extrai um resumo em texto do payload bruto do Alertmanager, além do
    nome do container afetado (label `instance`, formato "nome:porta").
    Usada tanto pelo nó de triagem do grafo quanto pelo main.py, para
    exibir o alerta no dashboard imediatamente, antes do LLM rodar.
    """
    alerts = alert_raw.get("alerts", [])
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


def extrair_texto_resposta(content) -> str:
    """
    Normaliza o `.content` da resposta de um LLM (string ou lista de
    blocos, dependendo da versão do SDK/modelo). Blocos de tipos
    inesperados usam `getattr` como última tentativa, ao invés de
    descartar silenciosamente (o que cortaria o texto no meio sem
    nenhum aviso).
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
    # Aspas de fechamento opcional (`"?`) de propósito: se a resposta do
    # modelo foi truncada no meio de uma string, não existe aspas de
    # fechamento, e sem essa flexibilidade o valor inteiro seria perdido.
    "causa_provavel": r'"causa_provavel"\s*:\s*"([^"]*)"?',
    "acao_recomendada": r'"acao_recomendada"\s*:\s*"([^"]*)"?',
    "severidade": r'"severidade"\s*:\s*"([^"]*)"?',
    "acao_automatizavel": r'"acao_automatizavel"\s*:\s*(true|false)',
}


def recuperar_campos_parciais(texto: str) -> Optional[dict]:
    """
    Segunda linha de defesa: se o JSON vier malformado ou cortado,
    tenta recuperar os campos individualmente via regex. Usa
    "acao_automatizavel": False como padrão seguro quando esse campo
    específico não é recuperável — a dúvida nunca deve resultar em uma
    ação automática.
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
        "acao_automatizavel": campos.get("acao_automatizavel") == "true",
    }


def parsear_resposta_diagnostico(texto: str) -> dict:
    """
    Tenta, em ordem:
    1. Parse de JSON completo e válido (removendo blocos de código
       markdown, se houver)
    2. Recuperação parcial via regex (JSON truncado/malformado)
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

    recuperado = recuperar_campos_parciais(texto)
    if recuperado:
        return recuperado

    return {
        "causa_provavel": texto,
        "acao_recomendada": "Não foi possível interpretar uma ação estruturada a partir da resposta do modelo — revisar manualmente.",
        "severidade": "desconhecida",
        "acao_automatizavel": False,
    }
