"""
Testes de chunking.py — função pura, sem PyTorch/sentence-transformers,
roda em milissegundos.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chunking import chunk_markdown

RUNBOOK_EXEMPLO = """# Runbook: CPU alta

## Sintomas
CPU acima de 80%.

## Ações recomendadas
Reiniciar o container.

## Severidade
Alta.
"""


def test_chunk_markdown_uma_secao_por_chunk():
    chunks = chunk_markdown(RUNBOOK_EXEMPLO, "teste.md")
    assert len(chunks) == 3
    secoes = [c["section"] for c in chunks]
    assert secoes == ["Sintomas", "Ações recomendadas", "Severidade"]


def test_chunk_markdown_inclui_titulo_no_texto():
    """O título do documento deve aparecer prefixado em cada chunk —
    é isso que dá contexto ao embedding de cada seção isolada."""
    chunks = chunk_markdown(RUNBOOK_EXEMPLO, "teste.md")
    for chunk in chunks:
        assert "Runbook: CPU alta" in chunk["text"]


def test_chunk_markdown_preserva_source():
    chunks = chunk_markdown(RUNBOOK_EXEMPLO, "runbook-high-cpu.md")
    assert all(c["source"] == "runbook-high-cpu.md" for c in chunks)


def test_chunk_markdown_documento_sem_titulo_usa_source_como_titulo():
    texto = "## Sintomas\nAlgo errado.\n"
    chunks = chunk_markdown(texto, "sem-titulo.md")
    assert "sem-titulo.md" in chunks[0]["text"]


def test_chunk_markdown_documento_vazio():
    assert chunk_markdown("", "vazio.md") == []


def test_chunk_markdown_secao_vazia_e_descartada():
    """Uma seção sem conteúdo (só o cabeçalho, sem texto embaixo) não
    deve virar um chunk vazio e inútil."""
    texto = "# Título\n\n## Seção vazia\n\n## Seção com conteúdo\nTexto aqui.\n"
    chunks = chunk_markdown(texto, "teste.md")
    assert len(chunks) == 1
    assert chunks[0]["section"] == "Seção com conteúdo"
