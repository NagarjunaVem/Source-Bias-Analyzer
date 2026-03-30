"""Main retrieval pipeline orchestration."""

from __future__ import annotations

import re
import time
from pathlib import Path

import faiss
import numpy as np
from langchain_ollama import OllamaEmbeddings
from ollama import ResponseError

from app.retrieval.constants import TOP_K_FINAL_MAX
from app.retrieval.cross_encoder_reranker import cross_encoder_rerank
from app.retrieval.empty_results import handle_empty_results
from app.retrieval.hybrid_search import search_all_sites_bm25_only, search_all_sites_hybrid
from app.retrieval.index_loader import load_all_indexes
from app.retrieval.query_planner import diversify_results, filter_results, filter_site_indexes, plan_retrieval
from app.retrieval.weighting import apply_credibility_weight, apply_recency_weight

RETRIEVAL_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "than", "that", "this", "these", "those", "is", "are",
    "was", "were", "be", "been", "being", "to", "of", "in", "on", "for", "from", "by", "with", "as", "at",
    "it", "its", "their", "they", "them", "he", "she", "his", "her", "you", "your", "we", "our", "will", "would",
    "could", "should", "may", "might", "said", "says", "reported", "reports", "about", "after", "before", "during",
    "over", "under", "into", "also", "more", "most", "very",
}
MIN_RELEVANCE_OVERLAP = 2
MIN_TITLE_OVERLAP = 1
LOW_SIGNAL_TITLE_PATTERNS = (
    "daily briefing",
    "morning briefing",
    "newsletter",
    "live updates",
    "podcast",
    "horoscope",
)
QUERY_MAX_EMBED_CHARS = 2500
QUERY_MIN_EMBED_CHARS = 400
QUERY_EMBED_MAX_ATTEMPTS = 3
QUERY_EMBED_RETRY_DELAY_SECONDS = 4.0
_QUERY_EMBEDDER: OllamaEmbeddings | None = None


def _is_ollama_runner_failure(error: Exception) -> bool:
    """Detect common Ollama runner crashes so we can degrade gracefully."""
    current: BaseException | None = error
    seen_ids: set[int] = set()
    while current is not None and id(current) not in seen_ids:
        seen_ids.add(id(current))
        message = str(current).lower()
        if (
            "llama runner process has terminated" in message
            or "status code: 500" in message
            or ("ollama" in message and "terminated" in message)
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def _tokenize_for_relevance(text: str) -> set[str]:
    return {
        token for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", str(text).lower())
        if token not in RETRIEVAL_STOPWORDS and len(token) > 2
    }


def _get_query_embedder() -> OllamaEmbeddings:
    """Reuse a single Ollama query embedder within the app process."""
    global _QUERY_EMBEDDER
    if _QUERY_EMBEDDER is None:
        _QUERY_EMBEDDER = OllamaEmbeddings(model="nomic-embed-text")
    return _QUERY_EMBEDDER


def _prepare_query_text(query_text: str) -> str:
    """Normalize and trim the query to a safe initial embedding length."""
    normalized_query = " ".join(str(query_text).split())
    return normalized_query[:QUERY_MAX_EMBED_CHARS]


def _filter_irrelevant_results(query_text: str, results: list[dict]) -> list[dict]:
    """Drop obviously off-topic retrieval results before analysis consumes them."""
    query_tokens = _tokenize_for_relevance(query_text)
    if not query_tokens:
        return results

    filtered_results: list[dict] = []
    for result in results:
        title_text = str(result.get("title", "")).strip()
        lowered_title = title_text.lower()
        if any(pattern in lowered_title for pattern in LOW_SIGNAL_TITLE_PATTERNS):
            continue

        title_tokens = _tokenize_for_relevance(title_text)
        text_tokens = _tokenize_for_relevance(str(result.get("text", ""))[:500])
        title_overlap = len(query_tokens & title_tokens)
        text_overlap = len(query_tokens & text_tokens)
        overlap = len(query_tokens & (title_tokens | text_tokens))
        if title_overlap >= MIN_TITLE_OVERLAP or overlap >= max(MIN_RELEVANCE_OVERLAP, 3) or text_overlap >= 4:
            filtered_results.append(result)

    if filtered_results:
        print(f"Relevance filter kept {len(filtered_results)} of {len(results)} results")
        return filtered_results

    print("Relevance filter removed all results; returning original candidate set")
    return results


def embed_query(query_text: str) -> np.ndarray:
    """Embed the user query with nomic-embed-text and normalize it for cosine search."""
    embedder = _get_query_embedder()
    candidate = _prepare_query_text(query_text)
    last_error: Exception | None = None

    for attempt in range(1, QUERY_EMBED_MAX_ATTEMPTS + 1):
        try:
            working_candidate = candidate
            while True:
                try:
                    query_vector = embedder.embed_query(working_candidate)
                    query_embedding = np.array([query_vector]).astype("float32")
                    faiss.normalize_L2(query_embedding)
                    return query_embedding
                except ResponseError as error:
                    message = str(error).lower()
                    if "input length exceeds the context length" not in message:
                        raise
                    if len(working_candidate) <= QUERY_MIN_EMBED_CHARS:
                        raise
                    next_length = max(QUERY_MIN_EMBED_CHARS, int(len(working_candidate) * 0.7))
                    working_candidate = working_candidate[:next_length]
        except Exception as error:
            last_error = error
            if attempt < QUERY_EMBED_MAX_ATTEMPTS:
                print(
                    f"Query embedding attempt {attempt} failed; retrying in "
                    f"{QUERY_EMBED_RETRY_DELAY_SECONDS:.0f}s..."
                )
                time.sleep(QUERY_EMBED_RETRY_DELAY_SECONDS)
                continue
            print("Query embedding failed; Ollama embedding runner may be unavailable or unstable.")
            raise RuntimeError(f"Query embedding failed: {error}") from error
    if last_error is not None:
        raise RuntimeError(f"Query embedding failed: {last_error}") from last_error


def retrieve_similar_chunks(
    query_text: str,
    base_dir: str = "app/embeddings/vector_index",
    stage_label: str = "Retrieval",
) -> list[dict]:
    """Run the full hybrid retrieval pipeline and return the best final chunks."""
    retrieval_plan: dict | None = None
    site_indexes: list[dict] = []
    try:
        print(f"=== {stage_label} ===")
        retrieval_plan = plan_retrieval(query_text)
        print(f"Retrieval plan: {retrieval_plan}")

        print("Loading site indexes...")
        site_indexes = load_all_indexes(base_dir)
        if not site_indexes:
            print("No site indexes could be loaded.")
            return []
        site_indexes = filter_site_indexes(site_indexes, retrieval_plan)
        if not site_indexes:
            print("No site indexes matched the retrieval plan.")
            return []

        try:
            query_embedding = embed_query(query_text)
            all_results = search_all_sites_hybrid(site_indexes, query_embedding, query_text)
        except RuntimeError:
            print("Falling back to BM25-only retrieval because query embedding failed.")
            all_results = search_all_sites_bm25_only(site_indexes, query_text)
        all_results = handle_empty_results(all_results, query_text)
        if not all_results:
            return []

        all_results = apply_recency_weight(all_results)
        all_results = filter_results(all_results, retrieval_plan)
        if not all_results:
            return []

        if retrieval_plan.get("credibility_priority", True):
            all_results = apply_credibility_weight(all_results)

        final_results = cross_encoder_rerank(query_text, all_results)
        if retrieval_plan.get("diversity_required", False):
            final_results = diversify_results(final_results, TOP_K_FINAL_MAX)
        final_results = _filter_irrelevant_results(query_text, final_results)
        return final_results
    except Exception as error:
        if _is_ollama_runner_failure(error) and site_indexes:
            print("Ollama runner became unavailable; retrying retrieval with BM25 fallback.")
            try:
                fallback_results = search_all_sites_bm25_only(site_indexes, query_text)
                fallback_results = handle_empty_results(fallback_results, query_text)
                if not fallback_results:
                    return []
                if retrieval_plan is not None:
                    fallback_results = filter_results(fallback_results, retrieval_plan) or fallback_results
                    if retrieval_plan.get("credibility_priority", True):
                        fallback_results = apply_credibility_weight(fallback_results)
                    if retrieval_plan.get("diversity_required", False):
                        fallback_results = diversify_results(fallback_results, TOP_K_FINAL_MAX)
                fallback_results = _filter_irrelevant_results(query_text, fallback_results)
                print(f"BM25 fallback recovered {len(fallback_results)} results")
                return fallback_results
            except Exception as fallback_error:
                print(f"BM25 fallback also failed: {fallback_error}")
        print(f"Failed to retrieve similar chunks: {error}")
        return []


def search(
    query: str,
    base_dir: str | Path = "app/embeddings/vector_index",
    *_unused_args,
    top_k: int = TOP_K_FINAL_MAX,
    threshold: float = 0.3,
    stage_label: str = "Retrieval",
) -> list[dict]:
    """Compatibility wrapper around the upgraded retrieval pipeline for existing callers."""
    normalized_base_dir = Path(base_dir)
    if normalized_base_dir.suffix == ".index":
        normalized_base_dir = normalized_base_dir.parent

    results = retrieve_similar_chunks(
        query_text=query,
        base_dir=str(normalized_base_dir),
        stage_label=stage_label,
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
