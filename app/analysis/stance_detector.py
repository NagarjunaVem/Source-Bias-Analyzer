"""Claim-to-evidence stance detection utilities."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

STANCE_SUPPORT = "SUPPORT"
STANCE_CONTRADICT = "CONTRADICT"
STANCE_NEUTRAL = "NEUTRAL"
NEGATION_WORDS = {"no", "not", "never", "none", "without", "denied", "denies", "deny", "refuted", "rejects"}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", text.lower())


def _extract_numbers(text: str) -> set[str]:
    return set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", text))


def _extract_named_tokens(text: str) -> set[str]:
    matches = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", text)
    return {match.lower() for match in matches}


def _negation_present(text: str) -> bool:
    tokens = set(_tokenize(text))
    return bool(tokens & NEGATION_WORDS)


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _cosine_similarity(left: Counter[str], right: Counter[str]) -> float:
    shared = set(left) & set(right)
    numerator = sum(left[token] * right[token] for token in shared)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


def normalize_evidence_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize retrieval output into the evidence shape used by analysis."""
    return {
        "source": str(item.get("website_name") or item.get("source") or item.get("site_name") or "Unknown"),
        "text": str(item.get("text", "")).strip(),
        "score": float(item.get("score", 0.0)),
        "url": str(item.get("url", "")),
        "title": str(item.get("title", "")),
        "published_at": str(item.get("published_at") or item.get("scraped_date") or item.get("published") or ""),
    }


def classify_stance(claim: str, evidence_text: str) -> tuple[str, float, str]:
    """Classify a single evidence chunk as supporting, contradicting, or neutral."""
    claim_tokens = _tokenize(claim)
    evidence_tokens = _tokenize(evidence_text)
    claim_token_set = set(claim_tokens)
    evidence_token_set = set(evidence_tokens)

    lexical_similarity = _jaccard_similarity(claim_token_set, evidence_token_set)
    semantic_similarity = _cosine_similarity(Counter(claim_tokens), Counter(evidence_tokens))
    named_overlap = _jaccard_similarity(_extract_named_tokens(claim), _extract_named_tokens(evidence_text))

    claim_numbers = _extract_numbers(claim)
    evidence_numbers = _extract_numbers(evidence_text)
    number_conflict = bool(claim_numbers and evidence_numbers and claim_numbers != evidence_numbers)
    negation_conflict = _negation_present(claim) != _negation_present(evidence_text)

    if (number_conflict and lexical_similarity >= 0.20) or (negation_conflict and semantic_similarity >= 0.30):
        confidence = min(1.0, 0.55 + lexical_similarity * 0.25 + semantic_similarity * 0.20)
        return STANCE_CONTRADICT, confidence, "entity_or_quantity_conflict"

    support_signal = (0.45 * lexical_similarity) + (0.40 * semantic_similarity) + (0.15 * named_overlap)
    if support_signal >= 0.35:
        confidence = min(1.0, 0.45 + support_signal)
        return STANCE_SUPPORT, confidence, "semantic_alignment"

    neutral_signal = max(semantic_similarity, lexical_similarity)
    return STANCE_NEUTRAL, min(1.0, 0.20 + neutral_signal), "weak_alignment"


def detect_claim_stance(claim: str, evidence_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate chunk-level stance into a claim-level analysis result."""
    normalized_evidence = [normalize_evidence_item(item) for item in evidence_items if str(item.get("text", "")).strip()]
    if not normalized_evidence:
        return {
            "claim": claim,
            "evidence": [],
            "stance": STANCE_NEUTRAL,
            "stance_confidence": 0.0,
            "support_count": 0,
            "contradict_count": 0,
            "neutral_count": 0,
        }

    analyzed_evidence: list[dict[str, Any]] = []
    stance_buckets = {
        STANCE_SUPPORT: [],
        STANCE_CONTRADICT: [],
        STANCE_NEUTRAL: [],
    }

    for item in normalized_evidence:
        stance, confidence, reason = classify_stance(claim, item["text"])
        enriched_item = dict(item)
        enriched_item["stance"] = stance
        enriched_item["stance_confidence"] = round(confidence, 4)
        enriched_item["reason"] = reason
        analyzed_evidence.append(enriched_item)
        stance_buckets[stance].append(enriched_item)

    if stance_buckets[STANCE_CONTRADICT]:
        overall_stance = STANCE_CONTRADICT
        chosen_bucket = stance_buckets[STANCE_CONTRADICT]
    elif stance_buckets[STANCE_SUPPORT]:
        overall_stance = STANCE_SUPPORT
        chosen_bucket = stance_buckets[STANCE_SUPPORT]
    else:
        overall_stance = STANCE_NEUTRAL
        chosen_bucket = stance_buckets[STANCE_NEUTRAL]

    chosen_bucket = sorted(
        chosen_bucket,
        key=lambda item: (item["stance_confidence"], item["score"]),
        reverse=True,
    )[:3]

    return {
        "claim": claim,
        "evidence": chosen_bucket,
        "stance": overall_stance,
        "stance_confidence": round(
            sum(item["stance_confidence"] for item in chosen_bucket) / max(len(chosen_bucket), 1),
            4,
        ),
        "support_count": len(stance_buckets[STANCE_SUPPORT]),
        "contradict_count": len(stance_buckets[STANCE_CONTRADICT]),
        "neutral_count": len(stance_buckets[STANCE_NEUTRAL]),
        "all_evidence": analyzed_evidence,
    }

