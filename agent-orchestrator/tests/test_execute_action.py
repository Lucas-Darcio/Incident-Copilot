"""
Testes de execute_action_node — a parte do grafo que executa ações
reais. Usa um Docker client MOCKADO (unittest.mock), então roda em
qualquer máquina sem precisar de acesso real ao socket do Docker.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import docker as docker_module  # noqa: E402  (garante import real p/ docker.errors.NotFound)

from graph import execute_action_node  # noqa: E402


def _estado_base(**overrides) -> dict:
    base = {
        "alert_summary": "HighCPUUsage: teste",
        "severity_original": "critical",
        "target_container": "app-fake",
        "diagnosis": "diagnóstico de teste",
        "recommended_action": "reiniciar container",
        "severity_assessed": "alta",
        "action_type": "restart_container",
        "approved": True,
    }
    base.update(overrides)
    return base


def test_acao_rejeitada_nao_executa_nada():
    """A garantia de segurança mais importante do projeto: se o humano
    rejeita, NENHUMA chamada ao Docker deve acontecer."""
    with patch("graph.docker.from_env") as mock_from_env:
        resultado = execute_action_node(_estado_base(approved=False))

    mock_from_env.assert_not_called()
    assert "REJECTED" in resultado["action_result"]


def test_acao_nao_automatizavel_nao_executa_nada():
    """Mesmo aprovada, uma ação marcada como não-automatizável não deve
    chamar o Docker — só ações do tipo restart_container são executadas."""
    with patch("graph.docker.from_env") as mock_from_env:
        resultado = execute_action_node(_estado_base(action_type="revisao_manual"))

    mock_from_env.assert_not_called()
    assert "not an automatable action" in resultado["action_result"]


def test_restart_bem_sucedido():
    mock_container = MagicMock()
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_container

    with patch("graph.docker.from_env", return_value=mock_client):
        resultado = execute_action_node(_estado_base())

    mock_client.containers.get.assert_called_once_with("app-fake")
    mock_container.restart.assert_called_once()
    assert "restarted successfully" in resultado["action_result"]


def test_container_nao_encontrado():
    mock_client = MagicMock()
    mock_client.containers.get.side_effect = docker_module.errors.NotFound("não existe")

    with patch("graph.docker.from_env", return_value=mock_client):
        resultado = execute_action_node(_estado_base())

    assert "not found" in resultado["action_result"]


def test_falha_generica_do_docker_nao_derruba_o_grafo():
    """Qualquer outra falha do Docker (permissão negada, socket
    indisponível, etc.) deve virar um resultado tratado, não uma
    exceção não capturada que derrubaria o processo inteiro."""
    mock_client = MagicMock()
    mock_client.containers.get.side_effect = RuntimeError("socket indisponível")

    with patch("graph.docker.from_env", return_value=mock_client):
        resultado = execute_action_node(_estado_base())

    assert "Failed to execute corrective action" in resultado["action_result"]
