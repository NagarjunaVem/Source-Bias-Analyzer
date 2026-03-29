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
        for source, entries in grouped_by_source.items():
            stances = {str(entry.get("stance", "NEUTRAL")) for entry in entries}
            if "CONTRADICT" in stances:
                source_stances[source] = "CONTRADICT"
                contradictory_evidence.extend(entry for entry in entries if entry.get("stance") == "CONTRADICT")
            elif "SUPPORT" in stances:
                source_stances[source] = "SUPPORT"
            else:
                source_stances[source] = "NEUTRAL"

        if "SUPPORT" in source_stances.values() and "CONTRADICT" in source_stances.values():
            contradictions.append(
                {
                    "claim": str(item.get("claim", "")),
                    "sources": sorted(source_stances),
                    "type": _classify_contradiction_type(contradictory_evidence),
                }
            )

    return {"contradictions": contradictions}

