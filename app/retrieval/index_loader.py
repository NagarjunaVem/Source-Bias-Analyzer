"""Helpers for loading FAISS and BM25 indexes for all sites."""

from __future__ import annotations

import json
import os

import faiss
from rank_bm25 import BM25Okapi


def load_index_with_gpu(index, site_name: str):
    """Move a FAISS index to GPU when available, otherwise keep CPU."""
    if hasattr(faiss, "StandardGpuResources"):
        try:
            res = faiss.StandardGpuResources()
            gpu_index = faiss.index_cpu_to_gpu(res, 0, index)
            print(f"{site_name}: running on GPU")
            return gpu_index
        except Exception as e:
            print(f"{site_name}: GPU failed, using CPU. Reason: {e}")
            return index
    else:
        print(f"{site_name}: faiss-gpu not installed, using CPU")
        return index


def ensure_cosine_index(index):
    """Ensure the FAISS index uses inner product on normalized vectors."""
    if not isinstance(index, faiss.IndexFlatIP):
        print("Rebuilding index as IndexFlatIP for cosine similarity...")
        if hasattr(index, "get_xb"):
            all_vectors = faiss.rev_swig_ptr(index.get_xb(), index.ntotal * index.d)
            all_vectors = all_vectors.reshape(index.ntotal, index.d).copy()
        else:
            import numpy as np

            all_vectors = np.empty((index.ntotal, index.d), dtype=np.float32)
            for row in range(index.ntotal):
                all_vectors[row] = index.reconstruct(row)
        faiss.normalize_L2(all_vectors)
        new_index = faiss.IndexFlatIP(index.d)
        new_index.add(all_vectors)
        return new_index
    return index


def load_all_indexes(base_dir: str) -> list[dict]:
    """Load every site index folder and prepare both FAISS and BM25 indexes."""
    loaded_sites: list[dict] = []
    for site in sorted(os.listdir(base_dir)):
        site_path = os.path.join(base_dir, site)
        if not os.path.isdir(site_path):
            continue

        index_path = os.path.join(site_path, "articles.index")
        metadata_path = os.path.join(site_path, "metadata.json")
        if not os.path.exists(index_path) or not os.path.exists(metadata_path):
            print(f"Skipping {site}: missing files")
            continue

        index = faiss.read_index(index_path)
        index = ensure_cosine_index(index)
        index = load_index_with_gpu(index, site)

        with open(metadata_path, "r", encoding="utf-8") as file_handle:
            metadata = json.load(file_handle)

        corpus = [
            str(chunk.get("text", chunk.get("content", ""))).lower().split()
            for chunk in metadata
        ]
        bm25 = BM25Okapi(corpus)

        loaded_sites.append(
            {
                "site": site,
                "index": index,
                "metadata": metadata,
                "bm25": bm25,
            }
        )

    print(f"Loaded {len(loaded_sites)} site indexes successfully")
    return loaded_sites
