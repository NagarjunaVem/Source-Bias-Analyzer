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


def append_to_index(
    new_embeddings: np.ndarray,
    new_metadata: list[dict],
    save_dir: str,
) -> None:
    """Append new vectors and metadata to an existing FAISS index, deduplicating by cache_key."""
    output_dir = Path(save_dir)
    index_path = output_dir / INDEX_FILENAME
    metadata_path = output_dir / METADATA_FILENAME
    embeddings_path = output_dir / EMBEDDINGS_FILENAME

    new_embeddings = np.asarray(new_embeddings, dtype=np.float32)

    if index_path.exists() and metadata_path.exists():
        existing_index = faiss.read_index(str(index_path))
        existing_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        existing_emb = (
            np.load(str(embeddings_path)).astype(np.float32)
            if embeddings_path.exists()
            else np.empty((0, 0), dtype=np.float32)
        )

        existing_keys = {str(m.get("cache_key", "")) for m in existing_metadata}
        new_mask = [
            i for i, m in enumerate(new_metadata)
            if str(m.get("cache_key", "")) not in existing_keys
        ]

        if not new_mask:
            print(f"All {len(new_metadata)} chunks already in index — nothing to append.")
            return

        filtered_embeddings = new_embeddings[new_mask]
        filtered_metadata = [new_metadata[i] for i in new_mask]

        faiss.normalize_L2(filtered_embeddings)
        existing_index.add(filtered_embeddings)

        merged_metadata = existing_metadata + filtered_metadata
        merged_embeddings = (
            np.vstack([existing_emb, filtered_embeddings])
            if existing_emb.size > 0
            else filtered_embeddings
        )

        skipped = len(new_metadata) - len(new_mask)
        print(f"Appended {len(filtered_metadata)} new vectors (skipped {skipped} duplicates)")
        print(f"Index now has {existing_index.ntotal} total vectors")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        faiss.normalize_L2(new_embeddings)
        existing_index = faiss.IndexFlatIP(new_embeddings.shape[1])
        existing_index.add(new_embeddings)
        merged_metadata = list(new_metadata)
        merged_embeddings = new_embeddings
        print(f"Created new index with {len(new_metadata)} vectors")

    output_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(existing_index, str(index_path))
    metadata_path.write_text(
        json.dumps(merged_metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    np.save(str(embeddings_path), merged_embeddings.astype(np.float32))
    print(f"Saved → {index_path}")
