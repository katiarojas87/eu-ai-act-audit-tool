"""Query the local ChromaDB vector store for relevant EU AI Act passages."""
from functools import lru_cache

import chromadb
from sentence_transformers import SentenceTransformer

import config


@lru_cache(maxsize=1)
def _model() -> SentenceTransformer:
    return SentenceTransformer(config.EMBED_MODEL)


@lru_cache(maxsize=1)
def _collection():
    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    return client.get_collection(config.COLLECTION_NAME)


def retrieve(query: str, k: int = config.TOP_K) -> list[dict]:
    """Return top-k passages: [{text, source, distance}]. Works across NL/FR/EN/ES."""
    # e5 models expect a "query: " prefix on the search text.
    emb = _model().encode([f"query: {query}"], normalize_embeddings=True).tolist()
    res = _collection().query(query_embeddings=emb, n_results=k)
    out = []
    for text, meta, dist in zip(
        res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        out.append({"text": text, "source": meta.get("source", "?"), "distance": dist})
    return out
