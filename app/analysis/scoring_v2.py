"""Improved scoring for evidence-based bias analysis."""

from __future__ import annotations

from typing import Any


WEIGHTS_V2 = {
    "factual_accuracy": 0.35,
    "narrative_bias": 0.25,
    "completeness": 0.20,
    "confidence": 0.20,
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def compute_scores(
    claim_analyses: list[dict[str, Any]],
    contradictions: dict[str, list[dict[str, Any]]],
    missing_viewpoints: dict[str, Any],
    narrative_analysis: dict[str, Any],
) -> dict[str, float]:
    """Compute calibrated quality scores from the structured analysis output."""
    support_total = sum(int(item.get("support_count", 0)) for item in claim_analyses)
    contradict_total = sum(int(item.get("contradict_count", 0)) for item in claim_analyses)
    neutral_total = sum(int(item.get("neutral_count", 0)) for item in claim_analyses)
    analyzed_claims = max(len(claim_analyses), 1)
    contradiction_count = len(contradictions.get("contradictions", []))
    evidence_density = _average(
        [len(item.get("all_evidence", [])) / 5.0 for item in claim_analyses]
    )
    stance_confidence = _average([float(item.get("stance_confidence", 0.0)) for item in claim_analyses])
    support_ratio = support_total / max(support_total + contradict_total + neutral_total, 1)
    contradiction_ratio = contradict_total / max(support_total + contradict_total + neutral_total, 1)
    neutral_ratio = neutral_total / max(support_total + contradict_total + neutral_total, 1)

    factual_accuracy = _clamp(
        0.55 * support_ratio
        + 0.20 * min(evidence_density, 1.0)
        + 0.15 * stance_confidence
        + 0.10 * (1.0 - contradiction_ratio)
        - 0.20 * neutral_ratio
        - 0.12 * contradiction_count
    )
    narrative_bias = _clamp(
        0.55 * float(narrative_analysis.get("framing_bias_score", 0.0))
        + 0.45 * float(narrative_analysis.get("selective_emphasis_score", 0.0))
    )

    imbalance = float(missing_viewpoints.get("imbalance_score", 1.0))
    completeness = _clamp(
        0.45 * (1.0 - imbalance)
        + 0.20 * min(evidence_density, 1.0)
        + 0.15 * support_ratio
        + 0.10 * (1.0 - contradiction_ratio)
        - 0.20 * neutral_ratio
    )
    confidence = _clamp(
        0.45 * min(evidence_density, 1.0)
        + 0.35 * stance_confidence
        + 0.20 * (1.0 if contradiction_count <= analyzed_claims / 2 else 0.6)
    )

    final_score = _clamp(
        factual_accuracy * WEIGHTS_V2["factual_accuracy"]
        + (1.0 - narrative_bias) * WEIGHTS_V2["narrative_bias"]
        + completeness * WEIGHTS_V2["completeness"]
        + confidence * WEIGHTS_V2["confidence"]
    )

    return {
        "factual_accuracy": round(factual_accuracy, 4),
        "narrative_bias": round(narrative_bias, 4),
        "completeness": round(completeness, 4),
        "confidence": round(confidence, 4),
        "final_score": round(final_score, 4),
    }
