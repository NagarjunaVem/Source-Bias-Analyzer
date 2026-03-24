"""Embedding helpers for article and query text."""

from __future__ import annotations

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"
MODEL = SentenceTransformer(MODEL_NAME)
print(f"Embedding model loaded: {MODEL_NAME}")


def get_embedding(text: str) -> np.ndarray:
    """Encode a single text string into a 1D embedding vector."""
    embedding = MODEL.encode(text, convert_to_numpy=True, show_progress_bar=False)
    return np.asarray(embedding, dtype=np.float32)


def get_embeddings_batch(texts: list[str]) -> np.ndarray:
    """Encode a batch of text strings into a 2D embedding matrix."""
    embeddings = MODEL.encode(
        texts,
        convert_to_numpy=True,
        show_progress_bar=True,
    )
    return np.asarray(embeddings, dtype=np.float32)

stri = input('text: ')
print(get_embedding(stri))

