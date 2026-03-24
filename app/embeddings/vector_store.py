"""Simple FAISS helpers for Stage 3."""

from __future__ import annotations

import json
from pathlib import Path

import faiss
import numpy as np

from .embed import get_embedding

INDEX_FILENAME = "articles.index"
METADATA_FILENAME = "metadata.json"



def build_faiss_index(embeddings: np.ndarray) -> faiss.IndexFlatIP:
    embeddings = np.asarray(embeddings, dtype=np.float32)
    if embeddings.ndim != 2:
        raise ValueError("Embeddings must be a 2D array.")

    if embeddings.shape[0] == 0:
        raise ValueError("No embeddings provided.")
    
    dimension = embeddings.shape[1]
    # Normalize for cosine similarity
    faiss.normalize_L2(embeddings)

    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings)

    print(f"FAISS index built with {index.ntotal} vectors")
    return index


def save_index(index: faiss.Index, metadata: list[dict], save_dir: str) -> None:
    """Save FAISS index + metadata."""
    output_dir = Path(save_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    index_path = output_dir / INDEX_FILENAME
    metadata_path = output_dir / METADATA_FILENAME

    faiss.write_index(index, str(index_path))
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Index saved → {index_path}")
    print(f"Metadata saved → {metadata_path}")


def load_index(save_dir: str) -> tuple[faiss.Index, list[dict]]:
    """Load FAISS index + metadata safely."""
    input_dir = Path(save_dir)
    index_path = input_dir / INDEX_FILENAME
    metadata_path = input_dir / METADATA_FILENAME
    if not index_path.exists() or not metadata_path.exists():
        raise FileNotFoundError("FAISS index or metadata not found.")

    index = faiss.read_index(str(index_path))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    print(f"Loaded index with {index.ntotal} vectors")
    return index, metadata


def search(
    query: str,
    index: faiss.Index,
    metadata: list[dict],
    top_k: int = 5,
) -> list[dict]:
    """Search similar articles."""
    if not query or top_k <= 0 or index.ntotal == 0:
        return []

    query_vector = get_embedding(query).reshape(1, -1)
    query_vector = np.asarray(query_vector, dtype=np.float32)
    faiss.normalize_L2(query_vector)
    distances, indices = index.search(query_vector, min(top_k, index.ntotal))

    results = []
    for score, idx in zip(distances[0], indices[0]):
        if idx < 0 or idx >= len(metadata):
            continue
        item = dict(metadata[idx])
        item["score"] = float(score)
        results.append(item)
    return results
