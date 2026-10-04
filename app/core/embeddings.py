import httpx

from app.core.config import settings

# nomic-embed-text expects a task prefix on every input.
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


def _embed(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    with httpx.Client(base_url=settings.llm_base_url, timeout=120) as client:
        for i in range(0, len(texts), settings.embedding_batch_size):
            batch = texts[i : i + settings.embedding_batch_size]
            resp = client.post(
                "/embeddings", json={"model": settings.embedding_model, "input": batch}
            )
            resp.raise_for_status()
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
            vectors.extend(d["embedding"] for d in data)
    return vectors


def embed_documents(texts: list[str]) -> list[list[float]]:
    return _embed([DOCUMENT_PREFIX + t for t in texts])


def embed_query(text: str) -> list[float]:
    return _embed([QUERY_PREFIX + text])[0]
