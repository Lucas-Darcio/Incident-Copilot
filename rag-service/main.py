"""
Serviço de RAG (Retrieval-Augmented Generation) — Fase 3.

Responsável por:
1. Ler os runbooks em markdown (pasta /app/runbooks, montada como volume)
2. Quebrar cada runbook em chunks menores (por seção "## ")
3. Gerar embeddings locais (sentence-transformers, sem depender de API paga)
4. Guardar tudo no Qdrant (vector database)
5. Expor um endpoint de busca semântica para testar isoladamente,
   antes de conectar isso a agentes na Fase 4.
"""
import glob
import os

from fastapi import FastAPI
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer

app = FastAPI(title="rag-service")

RUNBOOKS_DIR = "/app/runbooks"
COLLECTION_NAME = "runbooks"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

# Carregado uma vez na inicialização do container — evita recarregar o
# modelo a cada requisição, o que seria lento.
model = SentenceTransformer(EMBEDDING_MODEL_NAME)
EMBEDDING_DIM = model.get_sentence_embedding_dimension()

qdrant = QdrantClient(host="qdrant", port=6333)


# --- Chunking --------------------------------------------------------------
def _chunk_markdown(text: str, source: str) -> list[dict]:
    """
    Quebra um runbook em pedaços por seção (cabeçalhos "## "). Cada chunk
    carrega o título do documento + o nome da seção, para que o texto
    embutido (embedding) mantenha contexto mesmo isolado do resto do
    arquivo. Essa granularidade (por seção) funciona bem para nossos
    runbooks porque cada seção (Sintomas, Causas, Ações...) já é
    semanticamente coesa por si só.
    """
    lines = text.strip().split("\n")
    title = lines[0].lstrip("#").strip() if lines and lines[0].startswith("#") else source

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

    for line in lines[1:]:
        if line.startswith("## "):
            _flush()
            current_header = line.lstrip("#").strip()
            current_lines = []
        else:
            current_lines.append(line)
    _flush()

    return chunks


def _ingest_all_runbooks() -> int:
    """Lê todos os .md da pasta de runbooks, gera embeddings e (re)popula
    a coleção no Qdrant do zero. Retorna quantos chunks foram indexados."""
    # Recria a coleção para garantir que uma reingestão nunca deixe
    # chunks antigos/órfãos misturados com os novos.
    if qdrant.collection_exists(COLLECTION_NAME):
        qdrant.delete_collection(COLLECTION_NAME)
    qdrant.create_collection(
        COLLECTION_NAME,
        vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
    )

    all_chunks = []
    for filepath in sorted(glob.glob(os.path.join(RUNBOOKS_DIR, "*.md"))):
        text = open(filepath, encoding="utf-8").read()
        source = os.path.basename(filepath)
        all_chunks.extend(_chunk_markdown(text, source))

    if not all_chunks:
        return 0

    texts = [c["text"] for c in all_chunks]
    embeddings = model.encode(texts, show_progress_bar=False)

    points = [
        PointStruct(
            id=i,
            vector=embeddings[i].tolist(),
            payload={
                "text": all_chunks[i]["text"],
                "source": all_chunks[i]["source"],
                "section": all_chunks[i]["section"],
            },
        )
        for i in range(len(all_chunks))
    ]
    qdrant.upsert(collection_name=COLLECTION_NAME, points=points)
    return len(points)


# --- API ---------------------------------------------------------------
class SearchRequest(BaseModel):
    query: str
    top_k: int = 3


@app.post("/ingest")
def ingest():
    total = _ingest_all_runbooks()
    return {"chunks_indexados": total}


@app.post("/search")
def search(req: SearchRequest):
    query_vector = model.encode(req.query).tolist()
    results = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=req.top_k,
    ).points
    return {
        "query": req.query,
        "resultados": [
            {
                "score": round(r.score, 4),
                "source": r.payload["source"],
                "section": r.payload["section"],
                "text": r.payload["text"],
            }
            for r in results
        ],
    }


@app.get("/health")
def health():
    collection_ok = qdrant.collection_exists(COLLECTION_NAME)
    return {"status": "ok", "collection_exists": collection_ok}
