"""
Serviço de RAG (Retrieval-Augmented Generation) — Fase 3.

Responsável por:
1. Ler os runbooks em markdown (pasta /app/runbooks, montada como volume)
2. Quebrar cada runbook em chunks menores (por seção "## ") — lógica em chunking.py
3. Gerar embeddings locais (sentence-transformers, sem depender de API paga)
4. Guardar tudo no Qdrant (vector database)
5. Expor um endpoint de busca semântica para testar isoladamente,
   antes de conectar isso a agentes na Fase 4.
"""
import glob
import logging
import os

from fastapi import FastAPI
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer

from chunking import chunk_markdown

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("rag-service")

app = FastAPI(title="rag-service")

RUNBOOKS_DIR = "/app/runbooks"
COLLECTION_NAME = "runbooks"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

# Carregado uma vez na inicialização do container — evita recarregar o
# modelo a cada requisição, o que seria lento.
model = SentenceTransformer(EMBEDDING_MODEL_NAME)
EMBEDDING_DIM = model.get_sentence_embedding_dimension()

qdrant = QdrantClient(host="qdrant", port=6333)


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
        all_chunks.extend(chunk_markdown(text, source))

    if not all_chunks:
        logger.warning("Nenhum runbook encontrado em %s", RUNBOOKS_DIR)
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
    logger.info("Ingestão concluída: %d chunks indexados", len(points))
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
