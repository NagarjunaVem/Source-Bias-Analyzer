"""Hybrid FAISS + BM25 search helpers with timeout handling."""

from __future__ import annotations

import threading

import numpy as np

from app.retrieval.constants import DEFAULT_CREDIBILITY, TOP_K_BM25, TOP_K_COMBINED, TOP_K_FAISS, TOP_K_PER_SITE
from app.retrieval.weighting import get_adaptive_threshold


def _build_result_from_chunk(site: dict, idx: int, score: float, search_type: str, threshold_used: float) -> dict:
    """Map one metadata record into the standardized retrieval result format."""
    chunk = site["metadata"][idx]
    return {
        "chunk_id": chunk["chunk_id"],
        "text": chunk.get("text", chunk.get("content", "")),
        "title": chunk["title"],
        "url": chunk["url"],
        "scraped_date": chunk.get("scraped_date", chunk.get("scraped_at", "")),
        "score": float(score),
        "website_name": chunk.get("website_name", chunk.get("source", site["site"])),
        "recency_boost": 1.0,
        "days_old": -1,
        "credibility_score": DEFAULT_CREDIBILITY,
        "search_type": search_type,
        "ce_score": 0.0,
        "threshold_used": float(threshold_used),
        "site_name": site["site"],
    }


def search_single_site(site: dict, query_embedding: np.ndarray, query_text: str, top_k: int) -> list[dict]:
    """Run hybrid FAISS + BM25 retrieval for a single site and return its best fused results."""
    site_threshold = get_adaptive_threshold(site["site"])

    faiss_k = min(TOP_K_FAISS, site["index"].ntotal) if site["index"].ntotal > 0 else 0
    faiss_scores = np.array([], dtype=np.float32)
    faiss_indices = np.array([], dtype=np.int64)
    if faiss_k > 0:
        faiss_scores_raw, faiss_indices_raw = site["index"].search(query_embedding, faiss_k)
        faiss_scores = faiss_scores_raw[0]
        faiss_indices = faiss_indices_raw[0]

    query_tokens = query_text.lower().split()
    bm25_scores = np.asarray(site["bm25"].get_scores(query_tokens), dtype=np.float32)
    bm25_top_k = min(TOP_K_BM25, len(bm25_scores))
    bm25_top_indices = np.argsort(bm25_scores)[::-1][:bm25_top_k]
    bm25_max = float(np.max(bm25_scores)) if len(bm25_scores) and float(np.max(bm25_scores)) > 0 else 1.0
    bm25_normalized = bm25_scores / bm25_max

    combined_candidates: dict[int, dict] = {}
    for score, idx in zip(faiss_scores, faiss_indices, strict=False):
        if idx == -1 or idx < 0 or idx >= len(site["metadata"]):
            continue
        combined_candidates[int(idx)] = {
            "faiss_score": float(score),
            "bm25_score": 0.0,
            "search_type": "faiss",
        }

    for idx in bm25_top_indices:
        idx = int(idx)
        if idx < 0 or idx >= len(site["metadata"]):
            continue
        bm25_score = float(bm25_normalized[idx])
        if idx in combined_candidates:
            combined_candidates[idx]["bm25_score"] = bm25_score
            combined_candidates[idx]["search_type"] = "both"
        else:
            combined_candidates[idx] = {
                "faiss_score": 0.0,
                "bm25_score": bm25_score,
                "search_type": "bm25",
            }

    site_results: list[dict] = []
    for idx, candidate in combined_candidates.items():
        final_score = (0.6 * float(candidate["faiss_score"])) + (0.4 * float(candidate["bm25_score"]))
        if final_score < site_threshold:
            continue
        site_results.append(
            _build_result_from_chunk(
                site=site,
                idx=idx,
                score=final_score,
                search_type=str(candidate["search_type"]),
                threshold_used=site_threshold,
            )
        )

    site_results = sorted(site_results, key=lambda item: item["score"], reverse=True)[:top_k]
    print(f"{site['site']}: {len(site_results)} results found")
    return site_results


def search_site_with_timeout(site, query_embedding, query_text, top_k, timeout_seconds=10):
    """Search one site with timeout protection so one failing site cannot crash the pipeline."""
    result_container: list[dict] = []
    error_container: list[Exception] = []

    def _run_search() -> None:
        try:
            result_container.extend(search_single_site(site, query_embedding, query_text, top_k))
        except Exception as error:
            error_container.append(error)

    worker = threading.Thread(target=_run_search, daemon=True)
    worker.start()
    worker.join(timeout_seconds)

    if worker.is_alive():
        print(f"{site['site']}: search timed out after {timeout_seconds}s, skipping")
        return []
    if error_container:
        print(f"{site['site']}: search failed. Reason: {error_container[0]}")
        return []
    return result_container


def search_all_sites_hybrid(
    site_indexes: list[dict],
    query_embedding: np.ndarray,
    query_text: str,
) -> list[dict]:
    """Run hybrid retrieval across every site and keep the combined top candidate pool."""
    all_results: list[dict] = []
    for site in site_indexes:
        site_results = search_site_with_timeout(
            site=site,
            query_embedding=query_embedding,
            query_text=query_text,
            top_k=TOP_K_PER_SITE,
            timeout_seconds=10,
        )
        all_results.extend(site_results)

    all_results = sorted(all_results, key=lambda item: item["score"], reverse=True)[:TOP_K_COMBINED]
    return all_results
