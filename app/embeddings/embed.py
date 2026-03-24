"""Simple embedding helpers for Stage 3."""

from __future__ import annotations

import numpy as np
from sentence_transformers import SentenceTransformer
import torch

MODEL_NAME = "all-MiniLM-L6-v2"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
MODEL = SentenceTransformer(MODEL_NAME, device=DEVICE)
print(f"Embedding model loaded: {MODEL_NAME}")
print(f"Embedding device: {DEVICE}")


def get_embedding(text: str) -> np.ndarray:
    """Return one embedding vector for one text."""
    embedding = MODEL.encode(text, convert_to_numpy=True, show_progress_bar=False)
    return np.asarray(embedding, dtype=np.float32)


def get_embeddings_batch(texts: list[str]) -> np.ndarray:
    """Return embedding vectors for a list of texts."""
    embeddings = MODEL.encode(
        texts,
        convert_to_numpy=True,
        show_progress_bar=True,
    )
    return np.asarray(embeddings, dtype=np.float32)
