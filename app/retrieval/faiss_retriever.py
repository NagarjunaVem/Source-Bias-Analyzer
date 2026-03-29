"""Multi-site FAISS retrieval helpers using FAISS CPU."""

from __future__ import annotations

import json
import os
from pathlib import Path

import faiss
import numpy as np
from langchain_ollama import OllamaEmbeddings

from app.retrieval.reranker import rerank_results


def load_index_cpu(index, site_name: str):
    """Keep the loaded FAISS index on CPU."""
    print(f"{site_name}: using FAISS CPU")
    return index


def ensure_cosine_index(index):
    """Ensure the FAISS index uses inner product on normalized vectors."""
    # Rebuild non-IndexFlatIP indexes so cosine similarity works consistently.
    if not isinstance(index, faiss.IndexFlatIP):
        print("Rebuilding index as IndexFlatIP for cosine similarity...")
        all_vectors = faiss.rev_swig_ptr(
            index.get_xb(), index.ntotal * index.d
        )
        all_vectors = all_vectors.reshape(index.ntotal, index.d).copy()
        faiss.normalize_L2(all_vectors)
        new_index = faiss.IndexFlatIP(index.d)
        new_index.add(all_vectors)
        return new_index
    return index


def load_all_indexes(base_dir: str) -> list[dict]:
    """Load every site index folder found under the base vector-index directory."""
    # Walk every direct child folder dynamically so new sites are picked up automatically.
    loaded_sites: list[dict] = []
    for site in os.listdir(base_dir):
        site_path = os.path.join(base_dir, site)
        if not os.path.isdir(site_path):
            continue

        # Each site folder must have both the index and metadata files.
        index_path = os.path.join(site_path, "articles.index")
        metadata_path = os.path.join(site_path, "metadata.json")
        if not os.path.exists(index_path) or not os.path.exists(metadata_path):
            print(f"Skipping {site}: missing files")
            continue

        # Load the index, force cosine compatibility, and keep it on CPU.
        index = faiss.read_index(index_path)
        index = ensure_cosine_index(index)
        index = load_index_cpu(index, site)

        # Load the aligned chunk metadata for this site.
        with open(metadata_path, "r", encoding="utf-8") as file_handle:
            metadata = json.load(file_handle)

        loaded_sites.append(
            {
                "site": site,
                "index": index,
                "metadata": metadata,
            }
        )

    # Report how many site indexes were loaded successfully.
    print(f"Loaded {len(loaded_sites)} site indexes successfully")
    return loaded_sites


def embed_query(query_text: str) -> np.ndarray:
    """Embed the user query with nomic-embed-text and normalize it for cosine search."""
    try:
        # Use OllamaEmbeddings so query vectors match the current retrieval setup.
        embedder = OllamaEmbeddings(model="nomic-embed-text")
        query_vector = embedder.embed_query(query_text)
        query_embedding = np.array([query_vector]).astype("float32")
        faiss.normalize_L2(query_embedding)
        return query_embedding
    except Exception as error:
        # Raise a clear setup message if Ollama or the model is unavailable.
        print(
            "Ollama not running or nomic-embed-text not pulled.\n"
            "Run: ollama pull nomic-embed-text"
        )
        raise RuntimeError("Query embedding failed") from error


def search_all_sites(
    site_indexes: list[dict],
    query_embedding: np.ndarray,
    top_k_per_site: int = 5,
    threshold: float = 0.3,
) -> list[dict]:
    """Search every loaded site index and combine the passing chunk matches."""
    all_results: list[dict] = []

    # Query each site's FAISS index independently and keep only meaningful matches.
    for site in site_indexes:
        index = site["index"]
        search_k = min(top_k_per_site, index.ntotal) if index.ntotal > 0 else 0
        if search_k <= 0:
            print(f"{site['site']}: 0 results found")
            continue

        scores, indices = index.search(query_embedding, search_k)
        scores = scores[0]
        indices = indices[0]

        site_count = 0
        for score, idx in zip(scores, indices, strict=False):
            if idx == -1:
                continue
            if float(score) < threshold:
                continue
            if idx < 0 or idx >= len(site["metadata"]):
                continue

            chunk = site["metadata"][idx]
            all_results.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "text": chunk["text"],
                    "title": chunk["title"],
                    "url": chunk["url"],
                    "scraped_date": chunk["scraped_date"],
                    "score": float(score),
                    "website_name": chunk["website_name"],
                }
            )
            site_count += 1

        # Report how many results this site contributed after thresholding.
        print(f"{site['site']}: {site_count} results found")

    return all_results


def retrieve_similar_chunks(
    query_text: str,
    base_dir: str = "app/embeddings/vector_index",
    top_k_per_site: int = 5,
    top_k_final: int = 10,
    threshold: float = 0.3,
) -> list[dict]:
    """Load all site indexes, search them, rerank globally, and return the best chunks."""
    try:
        # Step 1: load every site index folder under the base vector-index directory.
        site_indexes = load_all_indexes(base_dir)
        if not site_indexes:
            print("No site indexes could be loaded.")
            return []

        # Step 2: embed and normalize the incoming query text.
        query_embedding = embed_query(query_text)

        # Step 3: search each site independently and combine all passing results.
        all_results = search_all_sites(
            site_indexes=site_indexes,
            query_embedding=query_embedding,
            top_k_per_site=top_k_per_site,
            threshold=threshold,
        )
        if not all_results:
            print("No sufficiently similar documents found for this query.")
            return []

        # Step 4: rerank the combined pool and return the final overall winners.
        final_results = rerank_results(all_results, top_k_final=top_k_final)
        return final_results
    except Exception as error:
        print(f"Failed to retrieve similar chunks: {error}")
        return []


def search(
    query: str,
    base_dir: str | Path = "app/embeddings/vector_index",
    *_unused_args,
    top_k: int = 10,
    threshold: float = 0.3,
) -> list[dict]:
    """Compatibility wrapper around multi-site retrieval for existing callers."""
    # Accept either the vector-index directory directly or an old file path and normalize it.
    normalized_base_dir = Path(base_dir)
    if normalized_base_dir.suffix == ".index":
        normalized_base_dir = normalized_base_dir.parent

    return retrieve_similar_chunks(
        query_text=query,
        base_dir=str(normalized_base_dir),
        top_k_per_site=5,
        top_k_final=top_k,
        threshold=threshold,
    )


if __name__ == "__main__":
    query = "government economic policy inflation"
    results = retrieve_similar_chunks(query)
    for r in results:
        print(f"Site    : {r['website_name']}")
        print(f"Title   : {r['title']}")
        print(f"Score   : {r['score']:.4f}")
        print(f"Text    : {r['text'][:100]}")
        print("---")
