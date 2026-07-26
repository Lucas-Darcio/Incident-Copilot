"""
Chunking de runbooks em markdown — função pura, sem dependências
externas. Separada em módulo próprio de propósito: isso permite testar
essa lógica com `pytest` puro, sem precisar instalar PyTorch/sentence-
transformers só para rodar os testes (ver tests/test_chunking.py).
"""


def chunk_markdown(text: str, source: str) -> list[dict]:
    """
    Quebra um runbook em pedaços por seção (cabeçalhos "## "). Cada chunk
    carrega o título do documento + o nome da seção, para que o texto
    embutido (embedding) mantenha contexto mesmo isolado do resto do
    arquivo. Essa granularidade (por seção) funciona bem para nossos
    runbooks porque cada seção (Sintomas, Causas, Ações...) já é
    semanticamente coesa por si só.
    """
    lines = text.strip().split("\n")

    # IMPORTANTE: "## Seção" também começa com "#", então checar só
    # startswith("#") confundia uma seção com o título do documento.
    # Aqui exigimos "# " (H1) e explicitamente excluímos "## " (H2).
    primeira_linha_e_titulo = lines and lines[0].startswith("# ") and not lines[0].startswith("## ")
    if primeira_linha_e_titulo:
        title = lines[0].lstrip("#").strip()
        linhas_restantes = lines[1:]
    else:
        title = source
        linhas_restantes = lines

    chunks = []
    current_header = None
    current_lines: list[str] = []

    def _flush():
        content = "\n".join(current_lines).strip()
        if content:
            chunks.append(
                {
                    "text": f"{title} — {current_header or title}\n{content}",
                    "source": source,
                    "section": current_header or title,
                }
            )

    for line in linhas_restantes:
        if line.startswith("## "):
            _flush()
            current_header = line.lstrip("#").strip()
            current_lines = []
        else:
            current_lines.append(line)
    _flush()

    return chunks
