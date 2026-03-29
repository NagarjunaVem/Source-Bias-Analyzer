"""Cross-source contradiction detection."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _classify_contradiction_type(evidence_items: list[dict[str, Any]]) -> str:
    reasons = {str(item.get("reason", "")) for item in evidence_items}
    if "entity_or_quantity_conflict" in reasons:
        return "factual"
    return "narrative"


def detect_contradictions(claim_analyses: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Detect source-level contradictions for the same underlying claim."""
    contradictions: list[dict[str, Any]] = []

    for item in claim_analyses:
        all_evidence = list(item.get("all_evidence", []))
        grouped_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for evidence in all_evidence:
            source = str(evidence.get("source", "Unknown"))
            grouped_by_source[source].append(evidence)

        source_stances: dict[str, str] = {}
        contradictory_evidence: list[dict[str, Any]] = []
        support_sources: set[str] = set()
        contradict_sources: set[str] = set()
        for source, entries in grouped_by_source.items():
            strong_contradictions = [
                entry for entry in entries
                if entry.get("stance") == "CONTRADICT"
                and (
                    (
                        entry.get("reason") == "entity_or_quantity_conflict"
                        and float(entry.get("stance_confidence", 0.0)) >= 0.75
                    )
                    or float(entry.get("stance_confidence", 0.0)) >= 0.85
                )
            ]
            strong_support = [
                entry for entry in entries
                if entry.get("stance") == "SUPPORT" and float(entry.get("stance_confidence", 0.0)) >= 0.65
            ]
            if strong_contradictions:
                source_stances[source] = "CONTRADICT"
                contradict_sources.add(source)
                contradictory_evidence.extend(strong_contradictions)
            elif strong_support:
                source_stances[source] = "SUPPORT"
                support_sources.add(source)
            else:
                source_stances[source] = "NEUTRAL"

        if support_sources and contradict_sources and len(contradictory_evidence) >= 2:
            contradictions.append(
                {
                    "claim": str(item.get("claim", "")),
                    "sources": sorted(support_sources | contradict_sources),
                    "type": _classify_contradiction_type(contradictory_evidence),
                }
            )

    return {"contradictions": contradictions}
