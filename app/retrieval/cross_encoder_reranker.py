"""Ollama-based reranking for retrieval results."""

from __future__ import annotations

import numpy as np
from langchain_ollama import OllamaEmbeddings

from app.retrieval.constants import TOP_K_COMBINED, TOP_K_FINAL_MAX, TOP_K_FINAL_MIN

RERANK_MODEL_NAME = "nomic-embed-text"
_RERANK_EMBEDDER: OllamaEmbeddings | None = None


def _get_rerank_embedder() -> OllamaEmbeddings:
    """Load and cache the Ollama embedder used for reranking."""
    global _RERANK_EMBEDDER
    if _RERANK_EMBEDDER is None:
        _RERANK_EMBEDDER = OllamaEmbeddings(model=RERANK_MODEL_NAME)
    return _RERANK_EMBEDDER


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    """L2-normalize rows for cosine-style similarity."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return matrix / norms


def _normalize_scores(scores: np.ndarray) -> list[float]:
    """Normalize scores into a stable 0 to 1 range."""
    score_min = float(np.min(scores))
    score_max = float(np.max(scores))
    score_range = score_max - score_min if score_max != score_min else 1.0
    return [float((score - score_min) / score_range) for score in scores]


def cross_encoder_rerank(
    query_text: str,
    results: list[dict],
    top_k_min: int = TOP_K_FINAL_MIN,
    top_k_max: int = TOP_K_FINAL_MAX,
) -> list[dict]:
    """Rerank the candidate pool with Ollama embeddings and return 10-15 final results."""
    if not results:
        return results

    candidate_results = sorted(results, key=lambda item: item["score"], reverse=True)[:TOP_K_COMBINED]
    embedder = _get_rerank_embedder()
    query_embedding = np.asarray(embedder.embed_query(" ".join(query_text.split())[:2000]), dtype=np.float32)
    document_texts = [" ".join(str(result["text"]).split())[:1200] for result in candidate_results]
    document_embeddings = np.asarray(embedder.embed_documents(document_texts), dtype=np.float32)

    query_embedding = query_embedding.reshape(1, -1)
    query_embedding = _normalize_rows(query_embedding)
    document_embeddings = _normalize_rows(document_embeddings)
    rerank_scores = np.matmul(document_embeddings, query_embedding.T).reshape(-1)
    normalized_scores = _normalize_scores(rerank_scores)

    for index, result in enumerate(candidate_results):
        result["ce_score"] = float(normalized_scores[index])
        result["score"] = (0.4 * float(result["score"])) + (0.6 * result["ce_score"])

    candidate_results = sorted(candidate_results, key=lambda item: item["score"], reverse=True)
    if len(candidate_results) < top_k_min:
        final_results = candidate_results
    elif len(candidate_results) <= top_k_max:
        final_results = candidate_results
    else:
        final_results = candidate_results[:top_k_max]

    print(f"Ollama reranked -> returning {len(final_results)} results")
    return final_results
