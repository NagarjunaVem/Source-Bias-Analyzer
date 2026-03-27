"""Public exports for the embeddings package."""

from .embed import get_embedding, get_embeddings_batch
from .vector_store import build_faiss_index, load_embedding_cache, load_index, save_index, search

__all__ = [
    "get_embedding",
    "get_embeddings_batch",
    "build_faiss_index",
    "save_index",
    "load_index",
    "load_embedding_cache",
    "search",
]
