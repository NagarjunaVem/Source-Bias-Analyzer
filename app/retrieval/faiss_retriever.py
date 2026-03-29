"""Multi-site FAISS retrieval helpers with hybrid search and reranking."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path

import faiss
import numpy as np
import torch
from langchain_ollama import OllamaEmbeddings
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder


TOP_K_FAISS = 8
TOP_K_BM25 = 8
TOP_K_PER_SITE = 5
TOP_K_COMBINED = 30
TOP_K_FINAL_MIN = 10
TOP_K_FINAL_MAX = 15
DEFAULT_CREDIBILITY = 0.60

CREDIBILITY_SCORES = {
    "reuters_com": 1.00,
    "apnews_com": 1.00,
    "bbc_com": 0.95,
    "bbc_co_uk": 0.95,
    "theguardian_com": 0.90,
    "npr_org": 0.90,
    "nature_com": 0.95,
    "sciencedaily_com": 0.88,
    "aljazeera_com": 0.82,
    "cnbc_com": 0.82,
    "techcrunch_com": 0.80,
    "wired_com": 0.80,
    "arstechnica_com": 0.80,
    "theverge_com": 0.78,
    "engadget_com": 0.75,
    "indianexpress_com": 0.75,
    "thehindu_com": 0.75,
    "hindustantimes_com": 0.70,
    "timesofindia_indiatimes_com": 0.68,
    "indiatoday_in": 0.68,
    "livemint_com": 0.68,
    "artificialintelligence_news_com": 0.65,
    "aajtak_in": 0.60,
    "space_com": 0.75,
}

_CROSS_ENCODER: CrossEncoder | None = None


def load_index_with_gpu(index, site_name: str):
    """Move a FAISS index to GPU when available, otherwise keep CPU."""
    # Always use the hasattr check first so faiss-cpu does not fail on GPU-only symbols.
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
    # Rebuild non-IndexFlatIP indexes so cosine similarity works consistently.
    if not isinstance(index, faiss.IndexFlatIP):
        print("Rebuilding index as IndexFlatIP for cosine similarity...")
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
    return index


def load_all_indexes(base_dir: str) -> list[dict]:
    """Load every site index folder and prepare both FAISS and BM25 indexes."""
    loaded_sites: list[dict] = []

    # Loop through every site folder dynamically so newly added sources are included automatically.
    for site in sorted(os.listdir(base_dir)):
        site_path = os.path.join(base_dir, site)
        if not os.path.isdir(site_path):
            continue

        index_path = os.path.join(site_path, "articles.index")
        metadata_path = os.path.join(site_path, "metadata.json")
        if not os.path.exists(index_path) or not os.path.exists(metadata_path):
            print(f"Skipping {site}: missing files")
            continue

        # Load the vector index, force cosine behavior, then use GPU when FAISS GPU is available.
        index = faiss.read_index(index_path)
        index = ensure_cosine_index(index)
        index = load_index_with_gpu(index, site)

        # Load metadata and build the BM25 keyword index once at load time.
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


def apply_recency_weight(results: list[dict]) -> list[dict]:
    """Apply a freshness-based multiplier to each result score."""
    today = datetime.today()
    for result in results:
        try:
            raw_date = str(result.get("scraped_date", "")).strip()
            if "T" in raw_date:
                scraped = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).replace(tzinfo=None)
            else:
                scraped = datetime.strptime(raw_date, "%Y-%m-%d")
            days_old = (today - scraped).days
            if days_old <= 30:
                recency_boost = 1.0
            elif days_old <= 90:
                recency_boost = 0.85
            elif days_old <= 180:
                recency_boost = 0.70
            else:
                recency_boost = 0.55
            result["score"] = float(result["score"]) * recency_boost
            result["recency_boost"] = recency_boost
            result["days_old"] = days_old
        except Exception:
            result["recency_boost"] = 1.0
            result["days_old"] = -1
    return results


def apply_credibility_weight(results: list[dict]) -> list[dict]:
    """Apply source credibility weighting to each result score."""
    for result in results:
        site_key = str(result.get("site_name", "")).lower().replace(" ", "_")
        if not site_key:
            site_key = str(result.get("website_name", "")).lower().replace(" ", "_")
        credibility = CREDIBILITY_SCORES.get(site_key, DEFAULT_CREDIBILITY)
        result["score"] = float(result["score"]) * credibility
        result["credibility_score"] = credibility
    return results


def get_adaptive_threshold(site_name: str, base_threshold: float = 0.3) -> float:
    """Use stricter thresholds for higher-credibility sources and looser ones for others."""
    credibility = CREDIBILITY_SCORES.get(site_name, DEFAULT_CREDIBILITY)
    if credibility >= 0.90:
        return base_threshold + 0.05
    if credibility >= 0.75:
        return base_threshold
    return base_threshold - 0.05


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

    # Stage 1: semantic FAISS search for the site.
    faiss_k = min(TOP_K_FAISS, site["index"].ntotal) if site["index"].ntotal > 0 else 0
    faiss_scores = np.array([], dtype=np.float32)
    faiss_indices = np.array([], dtype=np.int64)
    if faiss_k > 0:
        faiss_scores_raw, faiss_indices_raw = site["index"].search(query_embedding, faiss_k)
        faiss_scores = faiss_scores_raw[0]
        faiss_indices = faiss_indices_raw[0]

    # Stage 2: keyword BM25 search for the same site.
    query_tokens = query_text.lower().split()
    bm25_scores = np.asarray(site["bm25"].get_scores(query_tokens), dtype=np.float32)
    bm25_top_k = min(TOP_K_BM25, len(bm25_scores))
    bm25_top_indices = np.argsort(bm25_scores)[::-1][:bm25_top_k]
    bm25_max = float(np.max(bm25_scores)) if len(bm25_scores) and float(np.max(bm25_scores)) > 0 else 1.0
    bm25_normalized = bm25_scores / bm25_max

    # Merge FAISS and BM25 candidates by metadata index so each chunk is represented once.
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

    # Fuse semantic and keyword scores, filter by the adaptive site threshold, and keep top 5.
    site_results: list[dict] = []
    for idx, candidate in combined_candidates.items():
        faiss_score = float(candidate["faiss_score"])
        bm25_score = float(candidate["bm25_score"])
        final_score = (0.6 * faiss_score) + (0.4 * bm25_score)
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

    # Search every site independently with timeout protection.
    for site in site_indexes:
        site_results = search_site_with_timeout(
            site=site,
            query_embedding=query_embedding,
            query_text=query_text,
            top_k=TOP_K_PER_SITE,
            timeout_seconds=10,
        )
        all_results.extend(site_results)

    # Keep a manageable combined pool before the cross-encoder reranker.
    all_results = sorted(all_results, key=lambda item: item["score"], reverse=True)[:TOP_K_COMBINED]
    return all_results


def handle_empty_results(results: list[dict], query_text: str) -> list[dict]:
    """Return an empty list safely with clear diagnostics when nothing was retrieved."""
    if len(results) == 0:
        print(f"WARNING: No results found for query: '{query_text}'")
        print("Possible reasons:")
        print("  1. Query too specific — try broader terms")
        print("  2. All site scores below threshold 0.3")
        print("  3. FAISS indexes may be empty or corrupted")
        print("  4. Ollama embedding failed silently")
        return []
    return results


def _get_cross_encoder() -> CrossEncoder:
    """Load and cache the cross-encoder on GPU when available, otherwise CPU."""
    global _CROSS_ENCODER
    if _CROSS_ENCODER is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _CROSS_ENCODER = CrossEncoder(
            "cross-encoder/ms-marco-MiniLM-L-6-v2",
            device=device,
        )
        print(f"Cross-encoder running on: {device}")
    return _CROSS_ENCODER


def cross_encoder_rerank(
    query_text: str,
    results: list[dict],
    top_k_min: int = TOP_K_FINAL_MIN,
    top_k_max: int = TOP_K_FINAL_MAX,
) -> list[dict]:
    """Rerank the candidate pool with a cross-encoder and return 10-15 final results."""
    if not results:
        return results

    # Build query-chunk pairs from the combined candidate pool.
    candidate_results = sorted(results, key=lambda item: item["score"], reverse=True)[:TOP_K_COMBINED]
    pairs = [(query_text, str(result["text"])[:512]) for result in candidate_results]

    # Score all pairs with the cross-encoder.
    cross_encoder = _get_cross_encoder()
    ce_scores = cross_encoder.predict(pairs)

    # Normalize cross-encoder scores to 0-1 before mixing them with the existing score.
    ce_min = float(np.min(ce_scores))
    ce_max = float(np.max(ce_scores))
    ce_range = ce_max - ce_min if ce_max != ce_min else 1.0
    ce_normalized = [(float(score) - ce_min) / ce_range for score in ce_scores]

    for index, result in enumerate(candidate_results):
        result["ce_score"] = float(ce_normalized[index])
        result["score"] = (0.4 * float(result["score"])) + (0.6 * result["ce_score"])

    candidate_results = sorted(candidate_results, key=lambda item: item["score"], reverse=True)
    if len(candidate_results) < top_k_min:
        final_results = candidate_results
    elif len(candidate_results) <= top_k_max:
        final_results = candidate_results
    else:
        final_results = candidate_results[:top_k_max]

    print(f"Cross-encoder reranked -> returning {len(final_results)} results")
    return final_results


def retrieve_similar_chunks(
    query_text: str,
    base_dir: str = "app/embeddings/vector_index",
) -> list[dict]:
    """Run the full hybrid retrieval pipeline and return the best final chunks."""
    try:
        # Step 1: load all site indexes plus BM25 corpora.
        site_indexes = load_all_indexes(base_dir)
        if not site_indexes:
            print("No site indexes could be loaded.")
            return []

        # Step 2: embed the query text for semantic retrieval.
        query_embedding = embed_query(query_text)

        # Step 3: hybrid search per site with FAISS + BM25.
        all_results = search_all_sites_hybrid(site_indexes, query_embedding, query_text)

        # Step 4: cleanly handle empty retrieval output.
        all_results = handle_empty_results(all_results, query_text)
        if not all_results:
            return []

        # Step 5 and 6: apply recency and credibility weighting before reranking.
        all_results = apply_recency_weight(all_results)
        all_results = apply_credibility_weight(all_results)

        # Step 7: rerank with the cross-encoder and return the final 10-15 results.
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
