"""Evidence-based bias detection pipeline."""

from __future__ import annotations

import logging
import re
from collections import Counter
from functools import lru_cache
from typing import Any

from app.analysis.claim_extractor import extract_claims
from app.analysis.contradiction_detector import detect_contradictions
from app.analysis.narrative_analyzer import BIAS_LEXICON, analyze_narratives
from app.analysis.scoring_v2 import compute_scores
from app.analysis.stance_detector import detect_claim_stance, normalize_evidence_item
from app.retrieval.faiss_retriever import search

LOGGER = logging.getLogger(__name__)
DEFAULT_RETRIEVAL_DIR = "app/embeddings/vector_index"


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", text.lower())


def _validate_input(article_text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(article_text or "")).strip()
    if len(normalized) < 80:
        raise ValueError("Article text must contain at least 80 characters for reliable analysis.")
    return normalized


@lru_cache(maxsize=128)
def _cached_search(query_text: str, base_dir: str, top_k: int) -> tuple[dict[str, Any], ...]:
    results = search(query_text, base_dir=base_dir, top_k=top_k)
    return tuple(dict(item) for item in results)


def _retrieve_evidence(query_text: str, base_dir: str, top_k: int) -> list[dict[str, Any]]:
    try:
        return [dict(item) for item in _cached_search(query_text, base_dir, top_k)]
    except Exception as error:
        LOGGER.warning("Retrieval failed for query '%s': %s", query_text[:80], error)
        return []


def _highlight_biased_language(article_text: str) -> list[dict[str, str]]:
    highlights: list[dict[str, str]] = []
    for sentence in re.split(r"(?<=[.!?])\s+", article_text):
        matched_terms = [word for word in _tokenize(sentence) if word in BIAS_LEXICON]
        if matched_terms:
            highlights.append(
                {
                    "text": sentence.strip(),
                    "terms": ", ".join(sorted(set(matched_terms))),
                }
            )
    return highlights


def _detect_missing_viewpoints(claim_analyses: list[dict[str, Any]]) -> dict[str, Any]:
    support_claims = [item["claim"] for item in claim_analyses if item.get("support_count", 0) > 0]
    contradict_claims = [item["claim"] for item in claim_analyses if item.get("contradict_count", 0) > 0]
    neutral_claims = [item["claim"] for item in claim_analyses if item.get("support_count", 0) == 0 and item.get("contradict_count", 0) == 0]

    cluster_sizes = {
        "support": len(support_claims),
        "contradict": len(contradict_claims),
        "neutral": len(neutral_claims),
    }
    populated_clusters = [size for size in cluster_sizes.values() if size > 0]
    largest_cluster = max(cluster_sizes.values()) if cluster_sizes else 0
    smallest_cluster = min(populated_clusters) if populated_clusters else 0

    missing_groups: list[str] = []
    if cluster_sizes["support"] == 0:
        missing_groups.append("supporting evidence")
    if cluster_sizes["contradict"] == 0:
        missing_groups.append("challenging evidence")
    if cluster_sizes["neutral"] == 0:
        missing_groups.append("contextual or neutral evidence")

    imbalance_score = 1.0
    if largest_cluster > 0:
        imbalance_score = 1.0 - (smallest_cluster / largest_cluster if smallest_cluster else 0.0)

    return {
        "clusters": cluster_sizes,
        "missing": missing_groups,
        "imbalance_score": round(max(0.0, min(1.0, imbalance_score)), 4),
        "flagged_bias": imbalance_score >= 0.6 or bool(missing_groups),
    }


def _merge_unique_evidence(*evidence_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for group in evidence_groups:
        for item in group:
            normalized = normalize_evidence_item(item)
            key = (normalized["url"], normalized["text"][:180])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            merged.append(normalized)
    merged.sort(key=lambda item: item["score"], reverse=True)
    return merged


def _summarize_retrieval(evidence_items: list[dict[str, Any]]) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    for item in evidence_items[:6]:
        summaries.append(
            {
                "source": str(item.get("source", "Unknown")),
                "title": str(item.get("title", "")),
                "url": str(item.get("url", "")),
                "published_at": str(item.get("published_at", "")),
                "text": str(item.get("text", ""))[:350],
            }
        )
    return summaries


def _compute_consistency(claim_analyses: list[dict[str, Any]]) -> float:
    if not claim_analyses:
        return 0.0
    values = []
    for item in claim_analyses:
        evidence_count = len(item.get("all_evidence", []))
        contradiction_penalty = 1.0 if item.get("contradict_count", 0) == 0 else 0.6
        values.append(min(1.0, (evidence_count / 4.0) * contradiction_penalty))
    return round(sum(values) / len(values), 4)


def analyze_bias(
    article_text: str,
    *,
    retrieval_base_dir: str = DEFAULT_RETRIEVAL_DIR,
    top_k: int = 8,
) -> dict[str, Any]:
    """Run the production-style evidence-based bias analysis pipeline."""
    article = _validate_input(article_text)
    article_evidence = _retrieve_evidence(article, retrieval_base_dir, top_k)
    normalized_article_evidence = [normalize_evidence_item(item) for item in article_evidence]

    claims = extract_claims(article)
    claim_analyses: list[dict[str, Any]] = []
    for claim in claims:
        claim_specific_evidence = _retrieve_evidence(claim, retrieval_base_dir, top_k=5)
        evidence_pool = _merge_unique_evidence(normalized_article_evidence, claim_specific_evidence)
        claim_analyses.append(detect_claim_stance(claim, evidence_pool[:6]))

    contradictions = detect_contradictions(claim_analyses)
    narrative_analysis = analyze_narratives(article, normalized_article_evidence)
    missing_viewpoints = _detect_missing_viewpoints(claim_analyses)
    scores = compute_scores(claim_analyses, contradictions, missing_viewpoints, narrative_analysis)

    evidence_by_source = Counter(item["source"] for item in normalized_article_evidence)
    retrieval_summary = _summarize_retrieval(normalized_article_evidence)
    biased_language = _highlight_biased_language(article)
    retrieval_fallback_used = not bool(normalized_article_evidence)

    return {
        "claims": claims,
        "claim_analysis": [
            {
                "claim": item["claim"],
                "evidence": item["evidence"],
                "stance": item["stance"],
                "stance_confidence": item["stance_confidence"],
                "support_count": item["support_count"],
                "contradict_count": item["contradict_count"],
                "neutral_count": item["neutral_count"],
            }
            for item in claim_analyses
        ],
        "contradictions": contradictions["contradictions"],
        "narrative_analysis": narrative_analysis,
        "missing_viewpoints": missing_viewpoints,
        "scores": scores,
        "confidence_score": scores["confidence"],
        "retrieved_sources": retrieval_summary,
        "evidence_coverage": {
            "total_evidence_items": len(normalized_article_evidence),
            "sources_considered": dict(evidence_by_source),
            "retrieval_fallback_used": retrieval_fallback_used,
            "consistency": _compute_consistency(claim_analyses),
        },
        "biased_language": biased_language,
        "input_validation": {
            "article_length": len(article),
            "valid": True,
        },
    }

