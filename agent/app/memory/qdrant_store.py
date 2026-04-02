"""Qdrant vector store for schema descriptions and conversation memory."""

import uuid
import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from langchain_ollama import OllamaEmbeddings
from langchain_openai import OpenAIEmbeddings
from langchain_core.embeddings import Embeddings

from app.config import settings

logger = structlog.get_logger(__name__)


def get_qdrant_client() -> QdrantClient:
    return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)


def get_embeddings() -> Embeddings:
    provider = settings.embedding_provider.lower()
    if provider in {"llama_cpp", "llama-cpp", "llamacpp"}:
        base_url = settings.llama_cpp_embed_base_url or settings.llama_cpp_base_url
        api_key = settings.llama_cpp_embed_api_key or settings.llama_cpp_api_key or "sk-no-key"
        return OpenAIEmbeddings(
            model=settings.llama_cpp_embed_model,
            openai_api_key=api_key,
            openai_api_base=base_url,
        )
    return OllamaEmbeddings(
        model=settings.ollama_embed_model,
        base_url=settings.ollama_base_url,
    )


def _extract_vector_size(vectors_config: object) -> int | None:
    """Extract vector size from Qdrant vectors_config (single or named vectors)."""
    if vectors_config is None:
        return None
    # Single-vector collection
    size = getattr(vectors_config, "size", None)
    if isinstance(size, int):
        return size
    # Named-vector collection
    if isinstance(vectors_config, dict):
        first = next(iter(vectors_config.values()), None)
        if first is not None:
            named_size = getattr(first, "size", None)
            if isinstance(named_size, int):
                return named_size
    return None


def _embedding_vector_size(embeddings: Embeddings) -> int:
    sample_vector = embeddings.embed_query("dimension probe")
    return len(sample_vector)


def ensure_collection(client: QdrantClient, collection_name: str, embeddings: Embeddings) -> None:
    """Create the collection if missing and validate vector dimensions."""
    expected_size = _embedding_vector_size(embeddings)
    existing = [c.name for c in client.get_collections().collections]
    if collection_name not in existing:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=expected_size, distance=Distance.COSINE
            ),
        )
        logger.info("qdrant.collection_created", name=collection_name, vector_size=expected_size)
        return

    info = client.get_collection(collection_name)
    current_size = _extract_vector_size(info.config.params.vectors)
    if current_size is not None and current_size != expected_size:
        raise ValueError(
            "Qdrant collection vector size mismatch: "
            f"collection='{collection_name}', current={current_size}, expected={expected_size}. "
            "Use a new collection name or recreate the collection for the new embedding model."
        )


def upsert_texts(
    client: QdrantClient,
    embeddings: Embeddings,
    collection_name: str,
    texts: list[str],
    metadatas: list[dict] | None = None,
) -> int:
    """Embed and upsert a batch of texts into Qdrant. Returns count."""
    vectors = embeddings.embed_documents(texts)
    points = []
    for idx, (vec, txt) in enumerate(zip(vectors, texts)):
        payload = {"text": txt}
        if metadatas and idx < len(metadatas):
            payload.update(metadatas[idx])
        points.append(PointStruct(id=str(uuid.uuid4()), vector=vec, payload=payload))

    client.upsert(collection_name=collection_name, points=points)
    logger.info("qdrant.upserted", collection=collection_name, count=len(points))
    return len(points)


def search_similar(
    client: QdrantClient,
    embeddings: Embeddings,
    collection_name: str,
    query: str,
    top_k: int = 5,
) -> list[dict]:
    """Return the top-k most similar documents with scores."""
    query_vector = embeddings.embed_query(query)
    results = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        limit=top_k,
        with_payload=True,
    )
    return [
        {"text": hit.payload.get("text", ""), "score": hit.score, **hit.payload}
        for hit in results.points
    ]
