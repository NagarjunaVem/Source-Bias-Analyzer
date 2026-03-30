"""Narrative comparison and framing analysis."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.analysis.claim_extractor import split_into_candidate_sentences
from app.analysis.json_utils import ensure_dict, ensure_list, generate_validated_json
from app.analysis.lexicon import BIAS_LEXICON

NARRATIVE_MODEL_NAME = "qwen2.5:7b"
NARRATIVE_TIMEOUT_SECONDS = 28
NARRATIVE_MAX_RETRIES = 1

def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", text.lower())


def _extract_article_narrative(article_text: str) -> str:
    sentences = split_into_candidate_sentences(article_text)
    if not sentences:
        return ""
    return " ".join(sentences[:3])[:600]


def _extract_source_narratives(evidence_items: list[dict[str, Any]], limit: int = 5) -> list[dict[str, str]]:
    narratives: list[dict[str, str]] = []
    for item in evidence_items[:limit]:
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        narratives.append(
            {
                "source": str(item.get("source", "Unknown")),
                "summary": " ".join(split_into_candidate_sentences(text)[:2])[:400],
            }
        )
    return narratives


def _fallback_narrative_analysis(article_text: str, evidence_items: list[dict[str, Any]]) -> dict[str, Any]:
    article_tokens = Counter(_tokenize(article_text))
    source_tokens = Counter(_tokenize(" ".join(str(item.get("text", "")) for item in evidence_items)))
    shared = set(article_tokens) & set(source_tokens)
    overlap = len(shared) / max(len(set(article_tokens) | set(source_tokens)), 1)

    bias_hits = [token for token in _tokenize(article_text) if token in BIAS_LEXICON]
    selective_emphasis = 1.0 - overlap
    framing_bias = min(1.0, (len(bias_hits) / max(len(article_tokens), 1)) * 35.0)

    return {
        "article_narrative": _extract_article_narrative(article_text),
        "source_narratives": _extract_source_narratives(evidence_items),
        "framing_bias": "High framing bias detected." if framing_bias >= 0.35 else "Framing shows some restraint but still contains noticeable shaping.",
        "selective_emphasis": "The article emphasizes themes that appear underrepresented in retrieved evidence."
        if selective_emphasis >= 0.35
        else "The article overlaps with retrieved sources but still appears selectively framed in places.",
        "framing_bias_score": round(max(framing_bias, 0.12), 4),
        "selective_emphasis_score": round(max(min(selective_emphasis, 1.0), 0.12), 4),
    }


def _validate_narrative_payload(payload: Any) -> dict[str, Any]:
    data = ensure_dict(payload)
    source_narratives = ensure_list(data.get("source_narratives", []))
    validated_sources: list[dict[str, str]] = []
    for item in source_narratives:
        item_dict = ensure_dict(item)
        validated_sources.append(
            {
                "source": str(item_dict.get("source", "")).strip(),
                "summary": str(item_dict.get("summary", "")).strip(),
            }
        )

    return {
        "article_narrative": str(data.get("article_narrative", "")).strip(),
        "source_narratives": validated_sources,
        "framing_bias": str(data.get("framing_bias", "")).strip(),
        "selective_emphasis": str(data.get("selective_emphasis", "")).strip(),
        "framing_bias_score": max(0.0, min(1.0, float(data.get("framing_bias_score", 0.0)))),
        "selective_emphasis_score": max(0.0, min(1.0, float(data.get("selective_emphasis_score", 0.0)))),
    }


def analyze_narratives(article_text: str, evidence_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare article narrative with retrieved source narratives."""
    fallback = _fallback_narrative_analysis(article_text, evidence_items)
    if not evidence_items:
        return fallback

    evidence_context = "\n\n".join(
        f"Source: {item.get('source', 'Unknown')}\nText: {str(item.get('text', ''))[:500]}"
        for item in evidence_items[:5]
    )
    prompt = f"""
You are a strict media framing analyst.
Compare the input article's narrative to retrieved sources.
Return only valid JSON with this exact schema:
{{
  "article_narrative": "string",
  "source_narratives": [
    {{"source": "string", "summary": "string"}}
  ],
  "framing_bias": "string",
  "selective_emphasis": "string",
  "framing_bias_score": 0.0,
  "selective_emphasis_score": 0.0
}}

Rules:
- Scores must be between 0 and 1.
- Ground everything in the provided text.
- Be strict and skeptical. Do not describe framing as restrained or balanced unless the source material clearly supports that conclusion.
- If the article uses emotionally weighted wording, repeated alarm language, selective foregrounding, or unresolved tension, increase framing_bias_score.
- If the article leaves out moderating context, competing interpretations, or neutral explanation that appears in the retrieved sources, increase selective_emphasis_score.
- Do not treat overlap in topic alone as evidence of narrative alignment.
- Prefer critical wording over flattering wording when the comparison is mixed.
- Framing bias reflects emotionally loaded framing.
- Selective emphasis reflects omission or overemphasis relative to sources.
- Return JSON only, with no commentary before or after it.

ARTICLE:
{article_text[:2500]}

RETRIEVED SOURCES:
{evidence_context}
"""
    result = generate_validated_json(
        prompt=prompt,
        validator=_validate_narrative_payload,
        fallback=fallback,
        model=NARRATIVE_MODEL_NAME,
        timeout=NARRATIVE_TIMEOUT_SECONDS,
        max_retries=NARRATIVE_MAX_RETRIES,
    )
    return result.payload
