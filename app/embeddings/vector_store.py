"""FAISS index utilities for article embeddings."""

from __future__ import annotations

import json
from pathlib import Path

import faiss
import numpy as np

from .embed import get_embedding

INDEX_FILENAME = "articles.index"
METADATA_FILENAME = "metadata.json"
EMBEDDING_DIMENSION = 384


def build_faiss_index(embeddings: np.ndarray) -> faiss.IndexFlatL2:
    """Build an in-memory FAISS L2 index from a 2D embedding matrix."""
    normalized = np.asarray(embeddings, dtype=np.float32)
    if normalized.ndim != 2:
        raise ValueError("Embeddings must be a 2D array.")

    index = faiss.IndexFlatL2(EMBEDDING_DIMENSION)
    index.add(normalized)
    return index


def save_index(index: faiss.Index, metadata: list[dict], save_dir: str) -> None:
    """Persist the FAISS index and article metadata to disk."""
    output_dir = Path(save_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    faiss.write_index(index, str(output_dir / INDEX_FILENAME))
    (output_dir / METADATA_FILENAME).write_text(
        json.dumps(metadata, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def load_index(save_dir: str) -> tuple[faiss.Index, list[dict]]:
    """Load a FAISS index and its metadata from disk."""
    input_dir = Path(save_dir)
    index = faiss.read_index(str(input_dir / INDEX_FILENAME))
    metadata = json.loads((input_dir / METADATA_FILENAME).read_text(encoding="utf-8"))
    return index, metadata


def search(
    query: str,
    index: faiss.Index,
    metadata: list[dict],
    top_k: int = 5,
) -> list[dict]:
    """Search the index for the nearest articles to a query string."""
    if top_k <= 0 or index.ntotal == 0:
        return []

    query_vector = get_embedding(query).reshape(1, -1)
    distances, indices = index.search(query_vector, min(top_k, index.ntotal))

    results: list[dict] = []
    for score, match_index in zip(distances[0], indices[0], strict=False):
        if match_index < 0 or match_index >= len(metadata):
            continue
        result = dict(metadata[match_index])
        result["score"] = float(score)
        results.append(result)
    return results
