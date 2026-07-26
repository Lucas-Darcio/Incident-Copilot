"""
Testes de parsing.py — funções puras, sem necessidade de LLM, Docker
ou Postgres reais. Rodam em milissegundos.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parsing import (
    extrair_info_alerta,
    extrair_texto_resposta,
    parsear_resposta_diagnostico,
    recuperar_campos_parciais,
)


# --- extrair_info_alerta ----------------------------------------------------

def test_extrair_info_alerta_payload_completo():
    payload = {
        "alerts": [
            {
                "labels": {"alertname": "HighCPUUsage", "severity": "critical", "instance": "app-fake:8000"},
                "annotations": {"summary": "CPU alta", "description": "97% de uso"},
            }
        ]
    }
    resultado = extrair_info_alerta(payload)
    assert resultado["target_container"] == "app-fake"
    assert resultado["severity_original"] == "critical"
    assert "HighCPUUsage" in resultado["alert_summary"]
    assert "CPU alta" in resultado["alert_summary"]


def test_extrair_info_alerta_payload_vazio():
    resultado = extrair_info_alerta({"alerts": []})
    assert resultado["target_container"] is None
    assert resultado["severity_original"] == "desconhecida"


def test_extrair_info_alerta_sem_instance():
    payload = {"alerts": [{"labels": {"alertname": "X"}, "annotations": {}}]}
    resultado = extrair_info_alerta(payload)
    assert resultado["target_container"] is None


# --- extrair_texto_resposta --------------------------------------------------

def test_extrair_texto_resposta_string_simples():
    assert extrair_texto_resposta("texto puro") == "texto puro"


def test_extrair_texto_resposta_lista_de_dicts():
    content = [{"type": "text", "text": "parte 1"}, {"type": "text", "text": " parte 2"}]
    assert extrair_texto_resposta(content) == "parte 1 parte 2"


def test_extrair_texto_resposta_bloco_tipo_objeto():
    """Regressão: um bloco que não é dict nem str (ex: um objeto com
    atributo .text) não deve ser descartado silenciosamente."""

    class BlocoCustomizado:
        def __init__(self, text):
            self.text = text

    content = [{"text": "início "}, BlocoCustomizado("fim")]
    assert extrair_texto_resposta(content) == "início fim"


# --- parsear_resposta_diagnostico -------------------------------------------

def test_parsear_json_valido():
    texto = '{"causa_provavel": "CPU alta", "acao_recomendada": "reiniciar", "severidade": "alta", "acao_automatizavel": true}'
    resultado = parsear_resposta_diagnostico(texto)
    assert resultado["causa_provavel"] == "CPU alta"
    assert resultado["acao_automatizavel"] is True


def test_parsear_json_com_bloco_markdown():
    texto = '```json\n{"causa_provavel": "X", "acao_recomendada": "Y", "severidade": "baixa", "acao_automatizavel": false}\n```'
    resultado = parsear_resposta_diagnostico(texto)
    assert resultado["causa_provavel"] == "X"
    assert resultado["acao_automatizavel"] is False


def test_parsear_json_truncado_recupera_via_regex():
    """Caso real observado em produção: o modelo corta a resposta no
    meio de uma string. Deve recuperar o que der, sem quebrar."""
    texto = '{\n  "causa_provavel": "Uso de CPU acima do limite (97%), poss'
    resultado = parsear_resposta_diagnostico(texto)
    assert "Uso de CPU acima do limite" in resultado["causa_provavel"]
    # Campo não recuperável (acao_automatizavel) deve cair no padrão SEGURO
    assert resultado["acao_automatizavel"] is False


def test_parsear_texto_completamente_invalido_usa_fallback_seguro():
    resultado = parsear_resposta_diagnostico("isso não é JSON nem se parece com um")
    assert resultado["acao_automatizavel"] is False
    assert "revisar manualmente" in resultado["acao_recomendada"].lower() or resultado["causa_provavel"]


def test_recuperar_campos_parciais_sem_nenhum_campo_reconhecivel():
    assert recuperar_campos_parciais("texto qualquer sem json") is None
