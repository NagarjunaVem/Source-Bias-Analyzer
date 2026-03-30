"""Claim extraction utilities for evidence-grounded article analysis."""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

FACTUAL_VERBS = {
    "said",
    "says",
    "reported",
    "reports",
    "announced",
    "announces",
    "confirmed",
    "confirms",
    "showed",
    "shows",
    "approved",
    "approves",
    "won",
    "lost",
    "killed",
    "injured",
    "arrested",
    "launched",
    "signed",
    "passed",
    "claimed",
    "claims",
    "found",
    "finds",
    "stated",
    "states",
}
WEAK_SENTENCE_PREFIXES = ("opinion:", "editorial:", "analysis:", "commentary:")


def split_into_candidate_sentences(text: str) -> list[str]:
    """Split text into sentence-like units while preserving abbreviations reasonably well."""
    normalized = re.sub(r"\s+", " ", text.strip())
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", normalized)
    return [part.strip(" \n\t\"'") for part in parts if part.strip()]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", text.lower())


def _named_entity_count(text: str) -> int:
    return len(re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", text))


def _numeric_count(text: str) -> int:
    return len(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", text))


def _contains_factual_signal(tokens: Iterable[str]) -> bool:
    token_set = set(tokens)
    return bool(token_set & FACTUAL_VERBS)


def is_meaningful_claim(sentence: str) -> bool:
    """Filter sentence candidates down to factual, checkable claims."""
    cleaned = sentence.strip()
    if len(cleaned) < 35 or len(cleaned.split()) < 7:
        return False
    if cleaned.endswith("?"):
        return False
    if cleaned.lower().startswith(WEAK_SENTENCE_PREFIXES):
        return False
    tokens = _tokenize(cleaned)
    if not tokens:
        return False
    if _contains_factual_signal(tokens):
        return True
    return _numeric_count(cleaned) > 0 or _named_entity_count(cleaned) >= 2


def _deduplicate_claims(claims: list[str]) -> list[str]:
    """Drop near-duplicate claims using token-overlap heuristics."""
    unique_claims: list[str] = []
    seen_signatures: list[set[str]] = []

    for claim in claims:
        signature = set(_tokenize(claim))
        if not signature:
            continue
        duplicate_found = False
        for existing in seen_signatures:
            overlap = len(signature & existing) / max(len(signature | existing), 1)
            if overlap >= 0.75:
                duplicate_found = True
                break
        if not duplicate_found:
            unique_claims.append(claim)
            seen_signatures.append(signature)
    return unique_claims


def _score_claim(sentence: str, corpus_tokens: Counter[str]) -> float:
    tokens = _tokenize(sentence)
    if not tokens:
        return 0.0
    informativeness = sum(corpus_tokens[token] for token in set(tokens)) / max(len(set(tokens)), 1)
    return (
        0.35 * min(_numeric_count(sentence), 3)
        + 0.35 * min(_named_entity_count(sentence), 3)
        + 0.20 * (1.0 if _contains_factual_signal(tokens) else 0.0)
        + 0.10 * informativeness
    )


def extract_claims(article_text: str, max_claims: int = 7) -> list[str]:
    """Extract high-value factual claims instead of naively returning every sentence."""
    candidates = split_into_candidate_sentences(article_text)
    filtered = [sentence for sentence in candidates if is_meaningful_claim(sentence)]
    if not filtered:
        filtered = [sentence for sentence in candidates if len(sentence.split()) >= 8][:max_claims]

    corpus_tokens = Counter(_tokenize(article_text))
    ranked = sorted(filtered, key=lambda sentence: _score_claim(sentence, corpus_tokens), reverse=True)
    return _deduplicate_claims(ranked)[:max_claims]

