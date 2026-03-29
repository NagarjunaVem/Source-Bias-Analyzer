"""FAISS retrieval helpers kept separate from embedding generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from langchain_community.embeddings import OllamaEmbeddings


def _rebuild_index_for_cosine(index: faiss.Index) -> faiss.IndexFlatIP:
    """Rebuild a CPU FAISS index as IndexFlatIP using L2-normalized vectors."""
    if isinstance(index, faiss.IndexFlatIP):
        return index

    print("Warning: Index is not IndexFlatIP. Rebuilding for cosine similarity...")

    # Reconstruct all stored vectors so we can rebuild the index
    # as an inner-product index for cosine similarity search.
    if hasattr(index, "get_xb"):
        all_vectors = faiss.rev_swig_ptr(index.get_xb(), index.ntotal * index.d)
        all_vectors = all_vectors.reshape(index.ntotal, index.d).copy()
    else:
        all_vectors = np.empty((index.ntotal, index.d), dtype=np.float32)
        for row in range(index.ntotal):
            all_vectors[row] = index.reconstruct(row)

    faiss.normalize_L2(all_vectors)
    new_index = faiss.IndexFlatIP(index.d)
    new_index.add(all_vectors)
    return new_index


def load_faiss_index(index_path: str) -> faiss.Index:
    """Load a FAISS index, make it cosine-ready, and try GPU first."""
    # Step 1: load the saved FAISS index from disk.
    index = faiss.read_index(index_path)

    # Step 2: ensure the index is compatible with cosine similarity search.
    index = _rebuild_index_for_cosine(index)

    # Check whether faiss-gpu is available before attempting GPU transfer.
    if hasattr(faiss, "StandardGpuResources"):
        try:
            res = faiss.StandardGpuResources()
            gpu_index = faiss.index_cpu_to_gpu(res, 0, index)
            print("FAISS running on GPU")
            return gpu_index
        except Exception as e:
            print(f"GPU transfer failed, falling back to CPU. Reason: {e}")
            return index
    else:
        print("faiss-gpu not installed, running on CPU.")
        print("To enable GPU: pip uninstall faiss-cpu && pip install faiss-gpu")
        return index


def retrieve_similar_chunks(
    query_embedding: np.ndarray,
    index_path: str = "faiss_index.bin",
    chunks_path: str = "chunks.json",
    top_k: int = 5,
    threshold: float = 0.5,
) -> list[dict]:
    """Retrieve the most similar chunks using cosine similarity with FAISS."""
    try:
        # Step 3: validate and normalize the query embedding in place.
        query_embedding = np.asarray(query_embedding, dtype=np.float32)
        if query_embedding.ndim != 2 or query_embedding.shape[0] != 1:
            raise ValueError("query_embedding must have shape (1, embedding_dim)")

        faiss.normalize_L2(query_embedding)

        # Step 1 and 2: load a cosine-ready FAISS index with auto GPU/CPU support.
        index = load_faiss_index(index_path)

        # Step 4: search the top-k nearest chunks.
        search_k = min(top_k, index.ntotal) if index.ntotal > 0 else 0
        if search_k <= 0:
            print("No sufficiently similar documents found for this query.")
            return []

        scores, indices = index.search(query_embedding, search_k)
        scores = scores[0]
        indices = indices[0]

        # Step 5: load chunk metadata and map FAISS positions to chunk records.
        with open(chunks_path, "r", encoding="utf-8") as file_handle:
            chunks = json.load(file_handle)

        results: list[dict[str, Any]] = []
        for score, idx in zip(scores, indices, strict=False):
            if idx == -1:
                continue
            if idx < 0 or idx >= len(chunks):
                continue

            # Step 6: keep only strong-enough cosine matches.
            if float(score) < threshold:
                continue

            chunk = chunks[idx]
            results.append(
                {
                    "chunk_id": int(chunk["chunk_id"]),
                    "text": str(chunk.get("text", chunk.get("content", ""))),
                    "title": str(chunk["title"]),
                    "url": str(chunk["url"]),
                    "scraped_date": str(chunk.get("scraped_date", chunk.get("scraped_at", ""))),
                    "score": float(score),
                    "website_name": str(chunk.get("website_name", chunk.get("source", ""))),
                }
            )

        # Step 7: return the best results first.
        results.sort(key=lambda item: item["score"], reverse=True)
        if not results:
            print("No sufficiently similar documents found for this query.")
            return []

        return results
    except Exception as error:
        print(f"Failed to retrieve similar chunks: {error}")
        return []


def search(
    query: str,
    index_path: str | Path,
    chunks_path: str | Path,
    top_k: int = 5,
    threshold: float = 0.5,
) -> list[dict]:
    """Embed a text query and retrieve matching chunks from the retrieval store."""
    if not query or top_k <= 0:
        return []

    try:
        # Ollama must be running locally and the nomic model must be pulled first.
        embedder = OllamaEmbeddings(model="nomic-embed-text")
        query_vector = embedder.embed_query(query)
        query_embedding = np.array([query_vector]).astype("float32")
    except Exception:
        print(
            "Ollama not running or nomic-embed-text model not pulled.\n"
            "Run: ollama pull nomic-embed-text"
        )
        return []

    return retrieve_similar_chunks(
        query_embedding=query_embedding,
        index_path=str(index_path),
        chunks_path=str(chunks_path),
        top_k=top_k,
        threshold=threshold,
    )


if __name__ == "__main__":
    dummy_embedding = np.random.rand(1, 768).astype("float32")
    results = retrieve_similar_chunks(dummy_embedding)
    for r in results:
        print(f"Chunk ID: {r['chunk_id']}")
        print(f"Website: {r['website_name']}")
        print(f"Title: {r['title']}")
        print(f"URL: {r['url']}")
        print(f"Scraped Date: {r['scraped_date']}")
        print(f"Score: {r['score']:.4f}")
        print(f"Text Preview: {r['text'][:100]}")
        print("---")
