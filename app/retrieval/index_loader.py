"""Helpers for loading FAISS and BM25 indexes for all sites."""

from __future__ import annotations

import json
import os
from functools import lru_cache

import faiss
from rank_bm25 import BM25Okapi


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


@lru_cache(maxsize=4)
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

        try:
            index = faiss.read_index(index_path)
            index = ensure_cosine_index(index)

            with open(metadata_path, "r", encoding="utf-8") as file_handle:
                metadata = json.load(file_handle)

            if not isinstance(metadata, list) or not metadata:
                print(f"Skipping {site}: metadata is empty or invalid")
                continue

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
        except Exception as error:
            print(f"Skipping {site}: failed to load index bundle. Reason: {error}")
            continue

    print(f"Loaded {len(loaded_sites)} site indexes successfully")
    return loaded_sites
