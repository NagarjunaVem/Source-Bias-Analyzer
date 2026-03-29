"""Main retrieval pipeline orchestration."""

from __future__ import annotations

from pathlib import Path

import faiss
import numpy as np
from langchain_ollama import OllamaEmbeddings

from app.retrieval.constants import TOP_K_FINAL_MAX
from app.retrieval.cross_encoder_reranker import cross_encoder_rerank
from app.retrieval.empty_results import handle_empty_results
from app.retrieval.hybrid_search import search_all_sites_hybrid
from app.retrieval.index_loader import load_all_indexes
from app.retrieval.weighting import apply_credibility_weight, apply_recency_weight


def embed_query(query_text: str) -> np.ndarray:
    """Embed the user query with nomic-embed-text and normalize it for cosine search."""
    try:
        embedder = OllamaEmbeddings(model="nomic-embed-text")
        normalized_query = " ".join(str(query_text).split())
        query_vector = embedder.embed_query(normalized_query[:2000])
        query_embedding = np.array([query_vector]).astype("float32")
        faiss.normalize_L2(query_embedding)
        return query_embedding
    except Exception as error:
        print(
            "Ollama not running or nomic-embed-text not pulled.\n"
            "Run: ollama pull nomic-embed-text"
        )
        raise RuntimeError("Query embedding failed") from error


def retrieve_similar_chunks(
    query_text: str,
    base_dir: str = "app/embeddings/vector_index",
) -> list[dict]:
    """Run the full hybrid retrieval pipeline and return the best final chunks."""
    try:
        site_indexes = load_all_indexes(base_dir)
        if not site_indexes:
            print("No site indexes could be loaded.")
            return []

        query_embedding = embed_query(query_text)
        all_results = search_all_sites_hybrid(site_indexes, query_embedding, query_text)
        all_results = handle_empty_results(all_results, query_text)
        if not all_results:
            return []

        all_results = apply_recency_weight(all_results)
        all_results = apply_credibility_weight(all_results)
        final_results = cross_encoder_rerank(query_text, all_results)
        return final_results
    except Exception as error:
        print(f"Failed to retrieve similar chunks: {error}")
        return []


def search(
    query: str,
    base_dir: str | Path = "app/embeddings/vector_index",
    *_unused_args,
    top_k: int = TOP_K_FINAL_MAX,
    threshold: float = 0.3,
) -> list[dict]:
    """Compatibility wrapper around the upgraded retrieval pipeline for existing callers."""
    normalized_base_dir = Path(base_dir)
    if normalized_base_dir.suffix == ".index":
        normalized_base_dir = normalized_base_dir.parent

    results = retrieve_similar_chunks(
        query_text=query,
        base_dir=str(normalized_base_dir),
    )
    if top_k > 0:
        return results[:top_k]
    return results


if __name__ == "__main__":
    query = "government economic policy inflation"
    results = retrieve_similar_chunks(query)
    print(f"Total results: {len(results)}")
    for result in results:
        print(f"Site       : {result['website_name']}")
        print(f"Title      : {result['title']}")
        print(f"Score      : {result['score']:.4f}")
        print(f"CE Score   : {result['ce_score']:.4f}")
        print(f"Credibility: {result['credibility_score']:.4f}")
        print(f"Recency    : {result['recency_boost']}")
        print(f"Days Old   : {result['days_old']}")
        print(f"Search Type: {result['search_type']}")
        print(f"Text       : {result['text'][:100]}")
        print("---")
