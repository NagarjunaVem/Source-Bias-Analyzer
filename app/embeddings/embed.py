"""Simple embedding helpers for Stage 3."""

from __future__ import annotations

import numpy as np
from langchain_community.embeddings import OllamaEmbeddings

MODEL_NAME = "nomic-embed-text"
MODEL = OllamaEmbeddings(model=MODEL_NAME)
print(f"Embedding model loaded: {MODEL_NAME}")


def get_embedding(text: str) -> np.ndarray:
    """Return one embedding vector for one text."""
    embedding = MODEL.embed_query(text)
    return np.asarray(embedding, dtype=np.float32)


def get_embeddings_batch(texts: list[str]) -> np.ndarray:
    """Return embedding vectors for a list of texts."""
    embeddings = MODEL.embed_documents(texts)
    return np.asarray(embeddings, dtype=np.float32)
