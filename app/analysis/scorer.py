"""Calibrated scoring agent for source bias analysis using LangChain Ollama."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from app.analysis.json_utils import StructuredOutputError

MODEL_NAME = "gemma2:9b"

WEIGHTS = {
    "credibility": {
        "factual_accuracy": 0.60,
        "evidence_support": 0.25,
        "source_reliability": 0.15,
    },
    "completeness": {
        "viewpoint_coverage": 0.60,
        "context_depth": 0.25,
        "evidence_support": 0.15,
    },
    "bias": {
        "narrative_bias": 0.70,
        "loaded_language": 0.30,
    },
    "confidence": {
        "evidence_support": 0.45,
        "source_reliability": 0.20,
        "viewpoint_coverage": 0.20,
        "json_validity": 0.15,
    },
}

SCORER_PROMPT = ChatPromptTemplate.from_template(
    """You are a strict source-bias scoring agent.

Score the input article using only the article text and the related evidence provided.
Your goal is consistency, not generosity. Use the score bands carefully:

0.00-0.20 = very weak
0.21-0.40 = weak
0.41-0.60 = mixed
0.61-0.80 = strong
0.81-1.00 = very strong

Separate factual accuracy from narrative bias. Narrative bias can be high even when factual accuracy is moderate or high.

Return only valid JSON with this exact schema:
{{
  "component_scores": {{
    "factual_accuracy": 0.0,
    "narrative_bias": 0.0,
    "loaded_language": 0.0,
    "evidence_support": 0.0,
    "source_reliability": 0.0,
    "viewpoint_coverage": 0.0,
    "context_depth": 0.0
  }},
  "tone": "",
  "bias_type": "",
  "explanation": "",
  "missing_viewpoints": [],
  "evidence_summary": "",
  "ranked_perspectives": [
    {{
      "source": "",
      "score": 0.0,
      "reason": ""
    }}
  ]
}}

Rules:
- All component scores must be between 0 and 1
- Use only the provided text
- Do not hallucinate
- Factual accuracy measures alignment with evidence and internal consistency
- Narrative bias measures framing, imbalance, and selective emphasis
- Lower viewpoint coverage when important perspectives are absent
- Lower source reliability when the evidence is sparse, unclear, or weakly attributable
- Keep explanation concise and evidence-based

ARTICLE:
{article}

RELATED EVIDENCE:
{evidence}
"""
)

SCORER_MODEL = ChatOllama(
    model=MODEL_NAME,
    temperature=0.1,
)


def _clamp_score(value: Any) -> float:
    """Clamp scores into a stable 0 to 1 range."""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score))


def _normalize_component_scores(raw_scores: dict[str, Any]) -> dict[str, float]:
    """Normalize model output into the required component score set."""
    return {
        "factual_accuracy": _clamp_score(raw_scores.get("factual_accuracy")),
        "narrative_bias": _clamp_score(raw_scores.get("narrative_bias")),
        "loaded_language": _clamp_score(raw_scores.get("loaded_language")),
        "evidence_support": _clamp_score(raw_scores.get("evidence_support")),
        "source_reliability": _clamp_score(raw_scores.get("source_reliability")),
        "viewpoint_coverage": _clamp_score(raw_scores.get("viewpoint_coverage")),
        "context_depth": _clamp_score(raw_scores.get("context_depth")),
    }


def _weighted_sum(values: dict[str, float], weights: dict[str, float]) -> float:
    """Compute a weighted score from normalized component values."""
    total = 0.0
    for key, weight in weights.items():
        total += values.get(key, 0.0) * weight
    return round(_clamp_score(total), 4)


def _normalize_ranked_perspectives(raw_items: Any) -> list[dict[str, Any]]:
    """Normalize perspective rankings across model outputs."""
    if not isinstance(raw_items, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "source": str(item.get("source", "")).strip(),
                "score": _clamp_score(item.get("score")),
                "reason": str(item.get("reason", "")).strip(),
            }
        )

    normalized.sort(key=lambda item: item["score"], reverse=True)
    return normalized


def _compute_confidence(component_scores: dict[str, float], json_validity: float) -> float:
    """Compute final confidence from evidence quality and output reliability."""
    confidence_inputs = dict(component_scores)
    confidence_inputs["json_validity"] = _clamp_score(json_validity)
    return _weighted_sum(confidence_inputs, WEIGHTS["confidence"])


def _build_result(parsed: dict[str, Any], raw_output: str, json_validity: float) -> dict[str, Any]:
    """Build the final calibrated scoring payload."""
    component_scores = _normalize_component_scores(parsed.get("component_scores", {}))
    missing_viewpoints = parsed.get("missing_viewpoints", [])
    if not isinstance(missing_viewpoints, list):
        missing_viewpoints = []

    credibility_score = _weighted_sum(component_scores, WEIGHTS["credibility"])
    completeness_score = _weighted_sum(component_scores, WEIGHTS["completeness"])
    bias_score = _weighted_sum(component_scores, WEIGHTS["bias"])
    confidence = _compute_confidence(component_scores, json_validity=json_validity)

    return {
        "component_scores": component_scores,
        "factual_accuracy_score": component_scores["factual_accuracy"],
        "narrative_bias_score": component_scores["narrative_bias"],
        "bias_score": bias_score,
        "credibility_score": credibility_score,
        "completeness_score": completeness_score,
        "confidence": confidence,
        "tone": str(parsed.get("tone", "")).strip() or "Unknown",
        "bias_type": str(parsed.get("bias_type", "")).strip() or "Unknown",
        "explanation": str(parsed.get("explanation", "")).strip(),
        "missing_viewpoints": [str(item).strip() for item in missing_viewpoints if str(item).strip()],
        "evidence_summary": str(parsed.get("evidence_summary", "")).strip(),
        "ranked_perspectives": _normalize_ranked_perspectives(parsed.get("ranked_perspectives", [])),
        "model": MODEL_NAME,
        "normalization": {
            "score_range": "0_to_1",
            "weighted_formulas": WEIGHTS,
            "json_validity": _clamp_score(json_validity),
        },
        "raw_output": raw_output,
    }


def _fallback_result(raw_output: str) -> dict[str, Any]:
    """Return a safe fallback payload if JSON parsing fails."""
    return {
        "component_scores": {
            "factual_accuracy": 0.0,
            "narrative_bias": 0.0,
            "loaded_language": 0.0,
            "evidence_support": 0.0,
            "source_reliability": 0.0,
            "viewpoint_coverage": 0.0,
            "context_depth": 0.0,
        },
        "factual_accuracy_score": 0.0,
        "narrative_bias_score": 0.0,
        "bias_score": 0.0,
        "credibility_score": 0.0,
        "completeness_score": 0.0,
        "confidence": 0.0,
        "tone": "Unknown",
        "bias_type": "Unknown",
        "explanation": "Model output could not be parsed as valid JSON.",
        "missing_viewpoints": [],
        "evidence_summary": "",
        "ranked_perspectives": [],
        "model": MODEL_NAME,
        "normalization": {
            "score_range": "0_to_1",
            "weighted_formulas": WEIGHTS,
            "json_validity": 0.0,
        },
        "raw_output": raw_output,
    }


def _validate_scorer_payload(payload: Any) -> dict[str, Any]:
    """Validate and normalize the scorer model payload."""
    if not isinstance(payload, dict):
        raise StructuredOutputError("Scorer payload must be a dictionary.")

    if not isinstance(payload.get("component_scores", {}), dict):
        raise StructuredOutputError("Scorer payload missing component_scores.")

    return payload


def score_article(article: str, evidence: str = "") -> dict[str, Any]:
    """Score one article against related evidence using calibrated post-processing."""
    chain = SCORER_PROMPT | SCORER_MODEL
    response = chain.invoke(
        {
            "article": article.strip(),
            "evidence": evidence.strip() or "No external evidence provided.",
        }
    )

    raw_output = response.content if isinstance(response.content, str) else str(response.content)
    try:
        parsed = json.loads(raw_output)
        parsed = _validate_scorer_payload(parsed)
    except (json.JSONDecodeError, StructuredOutputError):
        return _fallback_result(raw_output)

    return _build_result(parsed, raw_output=raw_output, json_validity=1.0)
