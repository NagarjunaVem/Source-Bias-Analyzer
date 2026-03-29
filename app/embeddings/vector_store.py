"""FAISS index build/load helpers for embedding storage."""

from __future__ import annotations

import json
from pathlib import Path

import faiss
import numpy as np

INDEX_FILENAME = "articles.index"
METADATA_FILENAME = "metadata.json"
EMBEDDINGS_FILENAME = "embeddings.npy"


def build_faiss_index(embeddings: np.ndarray) -> faiss.IndexFlatIP:
    """Build a cosine-similarity FAISS index from a 2D numpy array."""
    embeddings = np.asarray(embeddings, dtype=np.float32)
    if embeddings.ndim != 2:
        raise ValueError("Embeddings must be a 2D array.")
    if embeddings.shape[0] == 0:
        raise ValueError("No embeddings provided.")

    dimension = embeddings.shape[1]
    faiss.normalize_L2(embeddings)

    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings)
    print(f"FAISS index built with {index.ntotal} vectors")
    return index


def save_index(
    index: faiss.Index,
    metadata: list[dict],
    save_dir: str,
    embeddings: np.ndarray | None = None,
) -> None:
    """Save the FAISS index, metadata, and optional numpy embedding cache."""
    output_dir = Path(save_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    index_path = output_dir / INDEX_FILENAME
    metadata_path = output_dir / METADATA_FILENAME

    faiss.write_index(index, str(index_path))
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if embeddings is not None:
        np.save(output_dir / EMBEDDINGS_FILENAME, np.asarray(embeddings, dtype=np.float32))

    print(f"Index saved -> {index_path}")
    print(f"Metadata saved -> {metadata_path}")
    if embeddings is not None:
        print(f"Embedding cache saved -> {output_dir / EMBEDDINGS_FILENAME}")


def load_index(save_dir: str) -> tuple[faiss.Index, list[dict]]:
    """Load the FAISS index and metadata."""
    input_dir = Path(save_dir)
    index_path = input_dir / INDEX_FILENAME
    metadata_path = input_dir / METADATA_FILENAME
    if not index_path.exists() or not metadata_path.exists():
        raise FileNotFoundError("FAISS index or metadata not found.")

    index = faiss.read_index(str(index_path))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    print(f"Loaded index with {index.ntotal} vectors")
    return index, metadata


def load_embedding_cache(save_dir: str) -> tuple[np.ndarray, list[dict]]:
    """Load the saved numpy embeddings and aligned metadata."""
    input_dir = Path(save_dir)
    embeddings_path = input_dir / EMBEDDINGS_FILENAME
    metadata_path = input_dir / METADATA_FILENAME

    if not embeddings_path.exists() or not metadata_path.exists():
        return np.empty((0, 0), dtype=np.float32), []

    embeddings = np.load(embeddings_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return np.asarray(embeddings, dtype=np.float32), metadata
