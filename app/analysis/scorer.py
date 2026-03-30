"""Calibrated scoring agent for source bias analysis."""

from __future__ import annotations

import re
from typing import Any

from app.analysis.json_utils import StructuredOutputError, generate_validated_json
from app.analysis.lexicon import BIAS_LEXICON, CATEGORY_WEIGHTS, TERM_TO_CATEGORY

MODEL_NAME = "phi3:mini"
SCORER_TIMEOUT_SECONDS = 60
SCORER_MAX_RETRIES = 1
MAX_ARTICLE_CHARS = 1600
MAX_EVIDENCE_CHARS = 1800
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

SCORER_PROMPT = """You are a severe source-bias scoring agent.

Score the input article using only the article text and the related evidence provided.
Your goal is consistency, skepticism, and non-generosity. Default to lower scores unless the evidence clearly supports a stronger score. Use the score bands carefully:

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
- Be conservative: do not call the article balanced, neutral, or well-supported unless the evidence clearly shows multiple competing viewpoints with solid attribution
- Treat executive opinion, analyst opinion, predictions, and forward-looking warnings as weaker support than directly verified facts
- If the article contains strong claims, emotional framing, or one-sided emphasis, lower narrative bias and viewpoint coverage scores accordingly
- If the evidence mostly repeats the article's framing rather than independently verifying it, lower factual accuracy and evidence_support
- When evidence is sparse, mixed, forecast-driven, or only partially relevant, do not assign high confidence
- Prefer "mixed", "uncertain", or "partially supported" over overly positive judgments
- Factual accuracy measures alignment with evidence and internal consistency
- Narrative bias measures framing, imbalance, and selective emphasis
- Lower viewpoint coverage when important perspectives are absent
- Lower source reliability when the evidence is sparse, unclear, or weakly attributable
- Keep explanation concise, evidence-based, and critical
- Return JSON only, with no prose before or after it

ARTICLE:
{article}

RELATED EVIDENCE:
{evidence}
"""


def _clamp_score(value: Any) -> float:
    """Clamp scores into a stable 0 to 1 range."""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score))


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", text.lower())


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


def _normalize_explanation(explanation: str, component_scores: dict[str, float]) -> str:
    """Tone down overly generous model explanations when the scores do not support them."""
    normalized = str(explanation or "").strip()
    if not normalized:
        return normalized

    lower = normalized.lower()
    viewpoint_coverage = component_scores.get("viewpoint_coverage", 0.0)
    narrative_bias = component_scores.get("narrative_bias", 0.0)
    evidence_support = component_scores.get("evidence_support", 0.0)
    factual_accuracy = component_scores.get("factual_accuracy", 0.0)

    if "balanced" in lower and (
        viewpoint_coverage < 0.72
        or narrative_bias > 0.40
        or evidence_support < 0.70
        or factual_accuracy < 0.75
    ):
        normalized = re.sub(r"\bbalanced view\b", "mixed view", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\bbalanced\b", "mixed", normalized, flags=re.IGNORECASE)

    if "neutral" in normalized.lower() and narrative_bias > 0.35:
        normalized = re.sub(r"\bneutral\b", "mixed", normalized, flags=re.IGNORECASE)

    return normalized


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
        "explanation": _normalize_explanation(str(parsed.get("explanation", "")).strip(), component_scores),
        "missing_viewpoints": [str(item).strip() for item in missing_viewpoints if str(item).strip()],
        "evidence_summary": str(parsed.get("evidence_summary", "")).strip(),
        "ranked_perspectives": _normalize_ranked_perspectives(parsed.get("ranked_perspectives", [])),
        "model": MODEL_NAME,
        "used_fallback": False,
        "normalization": {
            "score_range": "0_to_1",
            "weighted_formulas": WEIGHTS,
            "json_validity": _clamp_score(json_validity),
        },
        "raw_output": raw_output,
    }


def _fallback_result(raw_output: str, article: str = "", evidence: str = "") -> dict[str, Any]:
    """Return a heuristic fallback payload when structured scoring is unavailable."""
    article_tokens = _tokenize(article)
    evidence_tokens = _tokenize(evidence)
    weighted_bias_hits = sum(CATEGORY_WEIGHTS.get(TERM_TO_CATEGORY.get(token, ""), 1.0) for token in article_tokens if token in BIAS_LEXICON)
    source_mentions = re.findall(r"Source:\s*([^|\n]+)", evidence)
    unique_sources = {item.strip() for item in source_mentions if item.strip()}

    loaded_language = _clamp_score((weighted_bias_hits / max(len(article_tokens), 1)) * 28.0)
    evidence_support = _clamp_score(len(evidence_tokens) / 850.0)
    source_reliability = _clamp_score((len(unique_sources) * 0.14) + 0.10 if unique_sources else 0.08)
    viewpoint_coverage = _clamp_score((len(unique_sources) / 6.0) - 0.05)
    context_depth = _clamp_score(len(evidence) / 2200.0)
    factual_accuracy = _clamp_score((0.38 * evidence_support) + (0.27 * source_reliability) + (0.15 * context_depth))
    narrative_bias = _clamp_score((0.75 * loaded_language) + (0.45 * (1.0 - viewpoint_coverage)))

    heuristic_payload = {
        "component_scores": {
            "factual_accuracy": factual_accuracy,
            "narrative_bias": narrative_bias,
            "loaded_language": loaded_language,
            "evidence_support": evidence_support,
            "source_reliability": source_reliability,
            "viewpoint_coverage": viewpoint_coverage,
            "context_depth": context_depth,
        },
        "tone": "Heuristic fallback",
        "bias_type": "Unavailable",
        "explanation": "Calibrated scoring model timed out or returned unusable output, so a stricter heuristic fallback was used.",
        "missing_viewpoints": [],
        "evidence_summary": f"Heuristic fallback based on {len(unique_sources)} detected sources and {len(evidence_tokens)} evidence tokens.",
        "ranked_perspectives": [
            {
                "source": source,
                "score": _clamp_score(0.35 + (index * 0.06)),
                "reason": "Detected in structured evidence block."
            }
            for index, source in enumerate(sorted(unique_sources)[:4])
        ],
    }
    result = _build_result(heuristic_payload, raw_output=raw_output, json_validity=0.0)
    result["used_fallback"] = True
    return result


def _validate_scorer_payload(payload: Any) -> dict[str, Any]:
    """Validate and normalize the scorer model payload."""
    if not isinstance(payload, dict):
        raise StructuredOutputError("Scorer payload must be a dictionary.")

    if not isinstance(payload.get("component_scores", {}), dict):
        raise StructuredOutputError("Scorer payload missing component_scores.")

    return payload


def score_article(article: str, evidence: str = "") -> dict[str, Any]:
    """Score one article against related evidence using calibrated post-processing."""
    normalized_article = article.strip()[:MAX_ARTICLE_CHARS]
    normalized_evidence = (evidence.strip() or "No external evidence provided.")[:MAX_EVIDENCE_CHARS]
    prompt = SCORER_PROMPT.format(
        article=normalized_article,
        evidence=normalized_evidence,
    )
    fallback = _fallback_result("", article=normalized_article, evidence=normalized_evidence)
    result = generate_validated_json(
        prompt=prompt,
        validator=_validate_scorer_payload,
        fallback=fallback,
        model=MODEL_NAME,
        timeout=SCORER_TIMEOUT_SECONDS,
        max_retries=SCORER_MAX_RETRIES,
    )
    if result.used_fallback:
        fallback_payload = dict(result.payload)
        fallback_payload["raw_output"] = result.raw_output
        return fallback_payload
    return _build_result(result.payload, raw_output=result.raw_output, json_validity=1.0)
