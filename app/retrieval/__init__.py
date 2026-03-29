"""Public exports for retrieval helpers."""

from .constants import (
    CREDIBILITY_SCORES,
    DEFAULT_CREDIBILITY,
    TOP_K_BM25,
    TOP_K_COMBINED,
    TOP_K_FAISS,
    TOP_K_FINAL_MAX,
    TOP_K_FINAL_MIN,
    TOP_K_PER_SITE,
)
from .cross_encoder_reranker import cross_encoder_rerank
from .empty_results import handle_empty_results
from .faiss_retriever import embed_query, retrieve_similar_chunks, search
from .hybrid_search import search_all_sites_hybrid, search_single_site, search_site_with_timeout
from .index_loader import ensure_cosine_index, load_all_indexes
from .query_planner import diversify_results, filter_results, filter_site_indexes, plan_retrieval
from .reranker import rerank_results
from .weighting import apply_credibility_weight, apply_recency_weight, get_adaptive_threshold

__all__ = [
    "apply_credibility_weight",
    "apply_recency_weight",
    "CREDIBILITY_SCORES",
    "cross_encoder_rerank",
    "DEFAULT_CREDIBILITY",
    "embed_query",
    "ensure_cosine_index",
    "diversify_results",
    "filter_results",
    "filter_site_indexes",
    "get_adaptive_threshold",
    "handle_empty_results",
    "load_all_indexes",
    "plan_retrieval",
    "retrieve_similar_chunks",
    "rerank_results",
    "search",
    "search_all_sites_hybrid",
    "search_single_site",
    "search_site_with_timeout",
    "TOP_K_BM25",
    "TOP_K_COMBINED",
    "TOP_K_FAISS",
    "TOP_K_FINAL_MAX",
    "TOP_K_FINAL_MIN",
    "TOP_K_PER_SITE",
]
