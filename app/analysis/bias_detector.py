"""Evidence-based bias detection pipeline."""

from __future__ import annotations

import logging
import re
from collections import Counter
from functools import lru_cache
from typing import Any

from app.analysis.claim_extractor import extract_claims
from app.analysis.contradiction_detector import detect_contradictions
from app.analysis.lexicon import CATEGORY_WEIGHTS, TERM_TO_CATEGORY
from app.analysis.narrative_analyzer import BIAS_LEXICON, analyze_narratives
from app.analysis.scoring_v2 import compute_scores
from app.analysis.stance_detector import detect_claim_stance, normalize_evidence_item
from app.analysis.summarizer import summarize_retrieved_chunks
from app.retrieval.faiss_retriever import search

LOGGER = logging.getLogger(__name__)
DEFAULT_RETRIEVAL_DIR = "app/embeddings/vector_index"
DEFAULT_MAX_CLAIMS = 3
DEFAULT_CLAIM_RETRIEVAL_TOP_K = 2
TOPIC_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "than", "that", "this", "these", "those", "is", "are",
    "was", "were", "be", "been", "being", "to", "of", "in", "on", "for", "from", "by", "with", "as", "at",
    "it", "its", "their", "they", "them", "he", "she", "his", "her", "you", "your", "we", "our", "will", "would",
    "could", "should", "may", "might", "said", "says", "reported", "reports", "about", "after", "before", "during",
    "over", "under", "into", "also", "more", "most", "very",
}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", text.lower())


def _topic_tokens(text: str) -> set[str]:
    return {token for token in _tokenize(text) if token not in TOPIC_STOPWORDS and len(token) > 2}


def _validate_input(article_text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(article_text or "")).strip()
    if len(normalized) < 80:
        raise ValueError("Article text must contain at least 80 characters for reliable analysis.")
    return normalized


@lru_cache(maxsize=128)
def _cached_search(query_text: str, base_dir: str, top_k: int, stage_label: str) -> tuple[dict[str, Any], ...]:
    results = search(query_text, base_dir=base_dir, top_k=top_k, stage_label=stage_label)
    return tuple(dict(item) for item in results)


def _retrieve_evidence(query_text: str, base_dir: str, top_k: int, stage_label: str) -> list[dict[str, Any]]:
    try:
        raw_results = [dict(item) for item in _cached_search(query_text, base_dir, top_k, stage_label)]
        query_topics = _topic_tokens(query_text)
        if not query_topics:
            return raw_results

        filtered_results: list[dict[str, Any]] = []
        for item in raw_results:
            title_topics = _topic_tokens(str(item.get("title", "")))
            text_topics = _topic_tokens(str(item.get("text", ""))[:500])
            overlap = len(query_topics & (title_topics | text_topics))
            if overlap >= 2:
                filtered_results.append(item)
        return filtered_results or raw_results
    except Exception as error:
        LOGGER.warning("Retrieval failed for query '%s': %s", query_text[:80], error)
        return []


def _highlight_biased_language(article_text: str) -> list[dict[str, str]]:
    highlights: list[dict[str, str]] = []
    for sentence in re.split(r"(?<=[.!?])\s+", article_text):
        matched_terms = [word for word in _tokenize(sentence) if word in BIAS_LEXICON]
        if matched_terms:
            unique_terms = sorted(set(matched_terms))
            categories = sorted({TERM_TO_CATEGORY.get(word, "other") for word in unique_terms})
            category_map: dict[str, list[str]] = {}
            for word in unique_terms:
                category = TERM_TO_CATEGORY.get(word, "other")
                category_map.setdefault(category, []).append(word)
            weighted_intensity = sum(CATEGORY_WEIGHTS.get(category, 1.0) * len(words) for category, words in category_map.items())
            highlights.append(
                {
                    "text": sentence.strip(),
                    "terms": ", ".join(unique_terms),
                    "categories": ", ".join(categories),
                    "category_terms": category_map,
                    "weighted_intensity": round(weighted_intensity, 4),
                }
            )
    return highlights


def _compute_weighted_language_score(highlights: list[dict[str, Any]], article_text: str) -> float:
    """Compute weighted lexical intensity so harsher categories affect scoring more."""
    if not highlights:
        return 0.0
    total_weight = 0.0
    for item in highlights:
        category_terms = dict(item.get("category_terms", {}))
        for category, terms in category_terms.items():
            if isinstance(terms, list):
                total_weight += CATEGORY_WEIGHTS.get(str(category), 1.0) * len({str(term) for term in terms if str(term).strip()})
    normalized = total_weight / max(len(_tokenize(article_text)), 1)
    return round(max(0.0, min(1.0, normalized * 18.0)), 4)


def _detect_missing_viewpoints(claim_analyses: list[dict[str, Any]]) -> dict[str, Any]:
    support_claims = [item["claim"] for item in claim_analyses if item.get("support_count", 0) > 0]
    contradict_claims = [item["claim"] for item in claim_analyses if item.get("contradict_count", 0) > 0]
    neutral_claims = [item["claim"] for item in claim_analyses if item.get("support_count", 0) == 0 and item.get("contradict_count", 0) == 0]
    average_evidence = (
        sum(len(item.get("all_evidence", [])) for item in claim_analyses) / max(len(claim_analyses), 1)
        if claim_analyses else 0.0
    )

    cluster_sizes = {
        "support": len(support_claims),
        "contradict": len(contradict_claims),
        "neutral": len(neutral_claims),
    }
    populated_clusters = [size for size in cluster_sizes.values() if size > 0]
    largest_cluster = max(cluster_sizes.values()) if cluster_sizes else 0
    smallest_cluster = min(populated_clusters) if populated_clusters else 0

    missing_groups: list[str] = []
    if cluster_sizes["support"] == 0 and average_evidence < 4.5:
        missing_groups.append("supporting evidence")
    if cluster_sizes["contradict"] == 0 and average_evidence < 4.5:
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


def _build_summary_context(evidence_items: list[dict[str, Any]]) -> str:
    """Build grounded summary context from retrieved evidence using the shared summarizer."""
    if not evidence_items:
        return ""

    summarizer_ready_items: list[dict[str, Any]] = []
    for index, item in enumerate(evidence_items):
        summarizer_ready_items.append(
            {
                "chunk_id": index,
                "text": str(item.get("text", "")),
                "title": str(item.get("title", "")),
                "url": str(item.get("url", "")),
                "score": float(item.get("score", 0.0)),
                "website_name": str(item.get("source", "Unknown")),
                "published_at": str(item.get("published_at", "")),
            }
        )

    try:
        return summarize_retrieved_chunks(summarizer_ready_items).strip()
    except Exception as error:
        LOGGER.warning("Evidence summarization failed: %s", error)
        return ""


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
    initial_evidence: list[dict[str, Any]] | None = None,
    max_claims: int = DEFAULT_MAX_CLAIMS,
    claim_retrieval_top_k: int = DEFAULT_CLAIM_RETRIEVAL_TOP_K,
) -> dict[str, Any]:
    """Run the production-style evidence-based bias analysis pipeline."""
    article = _validate_input(article_text)
    article_evidence = (
        [dict(item) for item in initial_evidence]
        if initial_evidence is not None
        else _retrieve_evidence(article, retrieval_base_dir, top_k, "Main Article Retrieval")
    )
    normalized_article_evidence = [normalize_evidence_item(item) for item in article_evidence]

    claims = extract_claims(article, max_claims=max_claims)
    claim_analyses: list[dict[str, Any]] = []
    total_claims = len(claims)
    for index, claim in enumerate(claims, start=1):
        claim_specific_evidence = _retrieve_evidence(
            claim,
            retrieval_base_dir,
            top_k=claim_retrieval_top_k,
            stage_label=f"Claim Retrieval {index}/{total_claims}",
        )
        evidence_pool = _merge_unique_evidence(normalized_article_evidence, claim_specific_evidence)
        claim_analyses.append(detect_claim_stance(claim, evidence_pool[:6]))

    contradictions = detect_contradictions(claim_analyses)
    narrative_analysis = analyze_narratives(article, normalized_article_evidence)
    missing_viewpoints = _detect_missing_viewpoints(claim_analyses)
    biased_language = _highlight_biased_language(article)
    weighted_language_score = _compute_weighted_language_score(biased_language, article)
    scores = compute_scores(claim_analyses, contradictions, missing_viewpoints, narrative_analysis)
    if weighted_language_score > 0.0:
        scores["narrative_bias"] = round(min(1.0, float(scores.get("narrative_bias", 0.0)) + (0.55 * weighted_language_score)), 4)
        scores["factual_accuracy"] = round(max(0.0, float(scores.get("factual_accuracy", 0.0)) - (0.18 * weighted_language_score)), 4)
        scores["completeness"] = round(max(0.0, float(scores.get("completeness", 0.0)) - (0.10 * weighted_language_score)), 4)
        scores["confidence"] = round(max(0.0, float(scores.get("confidence", 0.0)) - (0.08 * weighted_language_score)), 4)

    evidence_by_source = Counter(item["source"] for item in normalized_article_evidence)
    retrieval_summary = _summarize_retrieval(normalized_article_evidence)
    summarized_evidence = _build_summary_context(normalized_article_evidence)
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
        "retrieved_summary_text": summarized_evidence,
        "evidence_coverage": {
            "total_evidence_items": len(normalized_article_evidence),
            "sources_considered": dict(evidence_by_source),
            "retrieval_fallback_used": retrieval_fallback_used,
            "consistency": _compute_consistency(claim_analyses),
        },
        "biased_language": biased_language,
        "weighted_language_score": weighted_language_score,
        "input_validation": {
            "article_length": len(article),
            "valid": True,
        },
    }

