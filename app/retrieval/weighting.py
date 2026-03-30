"""Score weighting helpers for recency, credibility, and thresholds."""

from __future__ import annotations

from datetime import datetime

from app.retrieval.constants import CREDIBILITY_SCORES, DEFAULT_CREDIBILITY


def apply_recency_weight(results: list[dict]) -> list[dict]:
    """Apply a freshness-based multiplier to each result score."""
    today = datetime.today()
    for result in results:
        try:
            raw_date = str(result.get("scraped_date", "")).strip()
            if "T" in raw_date:
                scraped = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).replace(tzinfo=None)
            else:
                scraped = datetime.strptime(raw_date, "%Y-%m-%d")
            days_old = (today - scraped).days
            if days_old <= 30:
                recency_boost = 1.0
            elif days_old <= 90:
                recency_boost = 0.85
            elif days_old <= 180:
                recency_boost = 0.70
            else:
                recency_boost = 0.55
            result["score"] = float(result["score"]) * recency_boost
            result["recency_boost"] = recency_boost
            result["days_old"] = days_old
        except Exception:
            result["recency_boost"] = 1.0
            result["days_old"] = -1
    return results


def apply_credibility_weight(results: list[dict]) -> list[dict]:
    """Apply source credibility weighting to each result score."""
    for result in results:
        site_key = str(result.get("site_name", "")).lower().replace(" ", "_")
        if not site_key:
            site_key = str(result.get("website_name", "")).lower().replace(" ", "_")
        credibility = CREDIBILITY_SCORES.get(site_key, DEFAULT_CREDIBILITY)
        result["score"] = float(result["score"]) * credibility
        result["credibility_score"] = credibility
    return results


def get_adaptive_threshold(site_name: str, base_threshold: float = 0.3) -> float:
    """Use stricter thresholds for higher-credibility sources and looser ones for others."""
    credibility = CREDIBILITY_SCORES.get(site_name, DEFAULT_CREDIBILITY)
    if credibility >= 0.90:
        return base_threshold + 0.05
    if credibility >= 0.75:
        return base_threshold
    return base_threshold - 0.05
