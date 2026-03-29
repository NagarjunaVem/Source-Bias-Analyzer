"""Simple embedding helpers for Stage 3."""

from __future__ import annotations

import numpy as np
from langchain_ollama import OllamaEmbeddings
from tqdm import tqdm

MODEL_NAME = "nomic-embed-text"
MODEL = OllamaEmbeddings(model=MODEL_NAME)
BATCH_SIZE = 32
print(f"Embedding model loaded: {MODEL_NAME}")


def get_embedding(text: str) -> np.ndarray:
    """Return one embedding vector for one text."""
    embedding = MODEL.embed_query(text)
    return np.asarray(embedding, dtype=np.float32)


def get_embeddings_batch(texts: list[str]) -> np.ndarray:
    """Return embedding vectors for a list of texts."""
    if not texts:
        return np.empty((0, 0), dtype=np.float32)

    all_embeddings: list[list[float]] = []
    for start in tqdm(
        range(0, len(texts), BATCH_SIZE),
        desc="Embedding chunks",
        unit="batch",
    ):
        batch = texts[start : start + BATCH_SIZE]
        batch_embeddings = MODEL.embed_documents(batch)
        all_embeddings.extend(batch_embeddings)

    return np.asarray(all_embeddings, dtype=np.float32)
