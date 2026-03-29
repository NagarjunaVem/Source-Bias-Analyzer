"""Reranking helpers for retrieval results."""

from __future__ import annotations


def rerank_results(
    all_results: list[dict],
    top_k_final: int = 10,
) -> list[dict]:
    """Sort combined retrieval results by score and keep the top final matches."""
    sorted_results = sorted(all_results, key=lambda x: x["score"], reverse=True)
    final_results = sorted_results[:top_k_final]
    print(f"Reranked {len(all_results)} total results -> returning top {len(final_results)}")
    return final_results
