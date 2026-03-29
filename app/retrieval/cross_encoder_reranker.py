"""Cross-encoder reranking for retrieval results."""

from __future__ import annotations

import numpy as np
import torch
from sentence_transformers import CrossEncoder

from app.retrieval.constants import TOP_K_COMBINED, TOP_K_FINAL_MAX, TOP_K_FINAL_MIN

_CROSS_ENCODER: CrossEncoder | None = None


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

    candidate_results = sorted(results, key=lambda item: item["score"], reverse=True)[:TOP_K_COMBINED]
    pairs = [(query_text, str(result["text"])[:512]) for result in candidate_results]

    cross_encoder = _get_cross_encoder()
    ce_scores = cross_encoder.predict(pairs)

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
