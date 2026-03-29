"""Simple embedding helpers for Stage 3."""

from __future__ import annotations

import numpy as np
from langchain_ollama import OllamaEmbeddings
from ollama import ResponseError
from tqdm import tqdm

MODEL_NAME = "nomic-embed-text"
MODEL = OllamaEmbeddings(model=MODEL_NAME)
BATCH_SIZE = 8
MAX_EMBED_CHARS = 2500
MIN_EMBED_CHARS = 400
print(f"Embedding model loaded: {MODEL_NAME}")


def _prepare_text(text: str) -> str:
    """Trim text to a safe size so Ollama embeddings stay within context length."""
    normalized = " ".join(str(text).split())
    return normalized[:MAX_EMBED_CHARS]


def _embed_single_with_backoff(text: str) -> list[float]:
    """Embed one text, shrinking it progressively if Ollama still rejects the length."""
    candidate = _prepare_text(text)

    while True:
        try:
            return MODEL.embed_query(candidate)
        except ResponseError as error:
            message = str(error).lower()
            if "input length exceeds the context length" not in message:
                raise
            if len(candidate) <= MIN_EMBED_CHARS:
                raise

            # Keep shrinking aggressively until the input fits Ollama's embed context.
            next_length = max(MIN_EMBED_CHARS, int(len(candidate) * 0.7))
            candidate = candidate[:next_length]


def get_embedding(text: str) -> np.ndarray:
    """Return one embedding vector for one text."""
    embedding = _embed_single_with_backoff(text)
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
        batch = [_prepare_text(text) for text in texts[start : start + BATCH_SIZE]]
        try:
            batch_embeddings = MODEL.embed_documents(batch)
        except Exception as error:
            print(f"Batch embedding failed, retrying one-by-one. Reason: {error}")
            batch_embeddings = [_embed_single_with_backoff(text) for text in batch]
        all_embeddings.extend(batch_embeddings)

    return np.asarray(all_embeddings, dtype=np.float32)
