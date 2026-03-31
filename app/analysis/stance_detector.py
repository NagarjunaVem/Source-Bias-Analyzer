"""Claim-to-evidence stance detection utilities.

Primary method: LLM-based (phi3:mini via Ollama) with a generous timeout.
Fallback method: Rule-based lexical heuristics (original implementation).
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)

STANCE_SUPPORT = "SUPPORT"
STANCE_CONTRADICT = "CONTRADICT"
STANCE_NEUTRAL = "NEUTRAL"
STANCE_MIXED = "MIXED"

# ---------------------------------------------------------------------------
# LLM configuration
# ---------------------------------------------------------------------------
OLLAMA_URL = "http://localhost:11434/api/generate"
STANCE_MODEL = "phi3:mini"        # loaded model
STANCE_LLM_TIMEOUT = 180          # seconds — generous to avoid false fallbacks
STANCE_LLM_NUM_PREDICT = 120      # only need a small JSON object

STANCE_PROMPT_TEMPLATE = """You are a precise stance-detection engine.

Given a CLAIM and an EVIDENCE chunk, classify the stance of the evidence toward the claim.

Rules:
- SUPPORT   → the evidence agrees with, confirms, or corroborates the claim
- CONTRADICT → the evidence disagrees with, refutes, or is in conflict with the claim
- NEUTRAL   → the evidence is topically related but neither supports nor contradicts

Return ONLY valid JSON with this exact schema (no prose, no explanation outside the JSON):
{{
  "stance": "SUPPORT" | "CONTRADICT" | "NEUTRAL",
  "confidence": 0.0,
  "reason": ""
}}

CLAIM:
{claim}

EVIDENCE:
{evidence}
"""

# ---------------------------------------------------------------------------
# Heuristic helpers (original implementation — used as fallback)
# ---------------------------------------------------------------------------
NEGATION_WORDS = {"no", "not", "never", "none", "without", "denied", "denies", "deny", "refuted", "rejects"}
TOPIC_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "than", "that", "this", "these", "those", "is", "are",
    "was", "were", "be", "been", "being", "to", "of", "in", "on", "for", "from", "by", "with", "as", "at",
    "it", "its", "their", "they", "them", "he", "she", "his", "her", "said", "says", "reported", "according",
    "will", "would", "could", "should", "may", "might", "into", "about", "after", "before", "during", "over",
}


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


def _topic_tokens(text: str) -> set[str]:
    return {token for token in _tokenize(text) if token not in TOPIC_STOPWORDS and len(token) > 2}


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


def _is_relevant_evidence(claim: str, evidence_text: str) -> bool:
    """Require minimal topical overlap before using evidence for stance decisions."""
    claim_topics = _topic_tokens(claim)
    evidence_topics = _topic_tokens(evidence_text)
    if not claim_topics or not evidence_topics:
        return False

    topic_overlap = len(claim_topics & evidence_topics)
    named_overlap = len(_extract_named_tokens(claim) & _extract_named_tokens(evidence_text))
    return topic_overlap >= 2 or (topic_overlap >= 1 and named_overlap >= 1)


def _heuristic_classify_stance(claim: str, evidence_text: str) -> tuple[str, float, str]:
    """Original rule-based stance classification (used as fallback)."""
    if not _is_relevant_evidence(claim, evidence_text):
        return STANCE_NEUTRAL, 0.05, "low_topic_overlap"

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
    contradiction_signal = (0.55 * semantic_similarity) + (0.30 * lexical_similarity) + (0.15 * named_overlap)

    if (
        number_conflict
        and lexical_similarity >= 0.45
        and semantic_similarity >= 0.35
        and contradiction_signal >= 0.42
    ) or (
        negation_conflict
        and semantic_similarity >= 0.55
        and lexical_similarity >= 0.20
        and contradiction_signal >= 0.48
    ):
        confidence = min(1.0, 0.55 + lexical_similarity * 0.25 + semantic_similarity * 0.20)
        return STANCE_CONTRADICT, confidence, "entity_or_quantity_conflict"

    support_signal = (0.45 * lexical_similarity) + (0.40 * semantic_similarity) + (0.15 * named_overlap)
    if (
        support_signal >= 0.36
        or (
            semantic_similarity >= 0.32
            and lexical_similarity >= 0.16
            and named_overlap >= 0.08
        )
        or (
            semantic_similarity >= 0.40
            and lexical_similarity >= 0.15
        )
    ):
        confidence = min(1.0, 0.45 + support_signal)
        return STANCE_SUPPORT, confidence, "semantic_alignment"

    neutral_signal = max(semantic_similarity, lexical_similarity)
    return STANCE_NEUTRAL, min(1.0, 0.20 + neutral_signal), "weak_alignment"


# ---------------------------------------------------------------------------
# LLM-based stance classification
# ---------------------------------------------------------------------------

def _llm_classify_stance(claim: str, evidence_text: str) -> tuple[str, float, str] | None:
    """Call Ollama LLM to classify stance. Returns None on any failure so the
    caller can fall through to the heuristic method."""
    # Trim inputs to keep the prompt concise and latency low
    claim_snippet = claim.strip()[:600]
    evidence_snippet = evidence_text.strip()[:800]

    prompt = STANCE_PROMPT_TEMPLATE.format(claim=claim_snippet, evidence=evidence_snippet)

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": STANCE_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.05,
                    "num_predict": STANCE_LLM_NUM_PREDICT,
                },
                "keep_alive": "1m", # Keep in RAM for 1 minute to bridge burst calls
            },
            timeout=STANCE_LLM_TIMEOUT,
        )
        response.raise_for_status()
        raw = str(response.json().get("response", "")).strip()
        parsed = json.loads(raw)

        stance_raw = str(parsed.get("stance", "")).strip().upper()
        if stance_raw not in {STANCE_SUPPORT, STANCE_CONTRADICT, STANCE_NEUTRAL}:
            LOGGER.debug("LLM returned unexpected stance value '%s'; falling back.", stance_raw)
            return None

        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
        reason = str(parsed.get("reason", "llm_classified")).strip() or "llm_classified"
        return stance_raw, confidence, reason

    except Exception as error:
        LOGGER.debug("LLM stance classification failed: %s — using heuristic fallback.", error)
        return None


# ---------------------------------------------------------------------------
# Public classify_stance — LLM first, heuristic fallback
# ---------------------------------------------------------------------------

def classify_stance(claim: str, evidence_text: str) -> tuple[str, float, str]:
    """Classify a single evidence chunk as supporting, contradicting, or neutral.

    Tries the LLM first; falls back to heuristic if LLM is unavailable or
    returns an invalid response.
    """
    llm_result = _llm_classify_stance(claim, evidence_text)
    if llm_result is not None:
        return llm_result

    # Heuristic fallback
    return _heuristic_classify_stance(claim, evidence_text)


# ---------------------------------------------------------------------------
# Evidence normalisation
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Claim-level aggregation
# ---------------------------------------------------------------------------

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

    support_bucket = stance_buckets[STANCE_SUPPORT]
    contradict_bucket = stance_buckets[STANCE_CONTRADICT]
    neutral_bucket = stance_buckets[STANCE_NEUTRAL]
    strong_support_bucket = [
        item for item in support_bucket
        if float(item.get("stance_confidence", 0.0)) >= 0.58 and float(item.get("score", 0.0)) >= 0.70
    ]

    support_avg = (
        sum(item["stance_confidence"] for item in support_bucket) / len(support_bucket)
        if support_bucket else 0.0
    )
    contradict_avg = (
        sum(item["stance_confidence"] for item in contradict_bucket) / len(contradict_bucket)
        if contradict_bucket else 0.0
    )

    # 1. Clear Contradiction Dominance
    if (
        len(contradict_bucket) >= 2
        and (
            # Simple majority in count if count is high enough (e.g. 4 vs 2, 3 vs 1)
            (len(contradict_bucket) > len(support_bucket) + 1 and contradict_avg >= 0.55)
            # Or clear confidence gap
            or (contradict_avg >= 0.70 and contradict_avg >= support_avg + 0.08)
            # Or absolute dominance
            or (len(contradict_bucket) >= 3 and not support_bucket)
        )
    ):
        overall_stance = STANCE_CONTRADICT
        chosen_bucket = contradict_bucket
    
    # 2. Clear Support Dominance
    elif (
        support_bucket
        and (
            # Simple majority in count
            (len(support_bucket) > len(contradict_bucket) + 1 and support_avg >= 0.55)
            # Or clear confidence gap or multiple strong items
            or support_avg >= 0.65 or len(strong_support_bucket) >= 2
        )
        and (
            not contradict_bucket
            or support_avg >= contradict_avg + 0.03
            or len(support_bucket) >= len(contradict_bucket) + 1
        )
    ):
        overall_stance = STANCE_SUPPORT
        chosen_bucket = strong_support_bucket or support_bucket
    
    # 3. Mixed Evidence (Both sides present and strong)
    elif support_bucket and contradict_bucket and (support_avg >= 0.45 and contradict_avg >= 0.45):
        overall_stance = STANCE_MIXED
        chosen_bucket = sorted(support_bucket + contradict_bucket, key=lambda x: x["stance_confidence"], reverse=True)
    
    # 4. Neutral or Indeterminate
    else:
        overall_stance = STANCE_NEUTRAL
        chosen_bucket = neutral_bucket or sorted(support_bucket + contradict_bucket, key=lambda x: x["stance_confidence"], reverse=True)

    # Prepare top evidence list for display
    chosen_bucket = sorted(
        chosen_bucket,
        key=lambda item: (item["stance_confidence"], item["score"]),
        reverse=True,
    )[:4] # Show up to 4 top items

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
