"""LLM-based query planning and retrieval filter helpers."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

AVAILABLE_SOURCES = ["bbc", "reuters", "cnn", "aljazeera", "thehindu", "ndtv"]
AVAILABLE_TOPICS = ["politics", "economy", "technology", "sports", "world", "general"]

PLANNER_PROMPT = ChatPromptTemplate.from_template(
    """You are an intelligent retrieval planner for a news bias analysis system.

Your task is to analyze a user query and generate structured metadata filters
to improve retrieval quality.

You MUST output STRICT JSON only.

AVAILABLE METADATA FIELDS:
- source (string): {sources}
- recency_days (integer)
- topic (string): {topics}
- diversity_required (boolean)
- credibility_priority (boolean)

INSTRUCTIONS:
1. Carefully analyze the user query.
2. Infer the intent:
   - Is the user asking about recent news?
   - Is the topic specific?
   - Should credible sources be preferred?
   - Should multiple perspectives be included?
3. Generate appropriate filters.
4. If a field is not relevant, set it to null.
5. Keep filters minimal and precise.

OUTPUT FORMAT:
{{
  "sources": [list or null],
  "recency_days": integer or null,
  "topic": string or null,
  "diversity_required": boolean,
  "credibility_priority": boolean
}}

USER QUERY:
{query}
"""
)

PLANNER_MODEL = ChatOllama(
    model="gemma2:9b",
    temperature=0.0,
)


def _extract_json(text: str) -> str | None:
    """Extract the first JSON object from the model output."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else None


def _normalize_source_name(value: str) -> str:
    """Normalize a source/site label for comparison."""
    return value.lower().replace(" ", "").replace("_", "").replace("-", "").replace(".", "")


def _fallback_plan() -> dict[str, Any]:
    """Return a safe default plan when the model output is unusable."""
    return {
        "sources": None,
        "recency_days": None,
        "topic": None,
        "diversity_required": True,
        "credibility_priority": True,
    }


def _normalize_plan(raw_plan: dict[str, Any]) -> dict[str, Any]:
    """Normalize the planner output into the expected schema."""
    raw_sources = raw_plan.get("sources")
    normalized_sources: list[str] | None = None
    if isinstance(raw_sources, list):
        normalized_sources = []
        for item in raw_sources:
            source = _normalize_source_name(str(item))
            if source in AVAILABLE_SOURCES and source not in normalized_sources:
                normalized_sources.append(source)
        if not normalized_sources:
            normalized_sources = None

    raw_topic = raw_plan.get("topic")
    topic = str(raw_topic).strip().lower() if raw_topic is not None else None
    if topic not in AVAILABLE_TOPICS:
        topic = None

    try:
        recency_days = int(raw_plan["recency_days"]) if raw_plan.get("recency_days") is not None else None
    except (TypeError, ValueError):
        recency_days = None
    if recency_days is not None and recency_days <= 0:
        recency_days = None

    return {
        "sources": normalized_sources,
        "recency_days": recency_days,
        "topic": topic,
        "diversity_required": bool(raw_plan.get("diversity_required", True)),
        "credibility_priority": bool(raw_plan.get("credibility_priority", True)),
    }


def plan_retrieval(query: str) -> dict[str, Any]:
    """Plan retrieval filters for a user query."""
    chain = PLANNER_PROMPT | PLANNER_MODEL
    response = chain.invoke(
        {
            "sources": json.dumps(AVAILABLE_SOURCES),
            "topics": json.dumps(AVAILABLE_TOPICS),
            "query": query.strip(),
        }
    )

    raw_output = response.content if isinstance(response.content, str) else str(response.content)
    json_text = _extract_json(raw_output)
    if not json_text:
        return _fallback_plan()

    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError:
        return _fallback_plan()
    return _normalize_plan(parsed)


def filter_site_indexes(site_indexes: list[dict], plan: dict[str, Any]) -> list[dict]:
    """Filter loaded site indexes by the planned source list."""
    planned_sources = plan.get("sources")
    if not planned_sources:
        return site_indexes

    filtered_sites: list[dict] = []
    for site in site_indexes:
        site_name = _normalize_source_name(str(site.get("site", "")))
        if any(source in site_name or site_name in source for source in planned_sources):
            filtered_sites.append(site)
    if not filtered_sites:
        print("Planner source filter matched no indexed sites; falling back to all sites.")
        return site_indexes
    return filtered_sites


def filter_results(results: list[dict], plan: dict[str, Any]) -> list[dict]:
    """Filter retrieval results using source and recency constraints."""
    filtered_results = list(results)
    source_filtered_results = list(filtered_results)

    planned_sources = plan.get("sources")
    if planned_sources:
        source_filtered_results = [
            result
            for result in filtered_results
            if any(
                source in _normalize_source_name(str(result.get("site_name", "")))
                or source in _normalize_source_name(str(result.get("website_name", "")))
                for source in planned_sources
            )
        ]
        if source_filtered_results:
            filtered_results = source_filtered_results
        else:
            print("Planner result filter matched no retrieved sources; keeping unfiltered results.")

    recency_days = plan.get("recency_days")
    if recency_days is not None:
        today = datetime.today()
        recent_results: list[dict] = []
        for result in filtered_results:
            raw_date = str(result.get("scraped_date", "")).strip()
            if not raw_date:
                continue
            try:
                if "T" in raw_date:
                    scraped = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).replace(tzinfo=None)
                else:
                    scraped = datetime.strptime(raw_date, "%Y-%m-%d")
            except ValueError:
                continue

            days_old = (today - scraped).days
            if days_old <= recency_days:
                recent_results.append(result)
        filtered_results = recent_results

    return filtered_results


def diversify_results(results: list[dict], top_k: int) -> list[dict]:
    """Reorder results to encourage multiple perspectives across sources."""
    if top_k <= 0:
        return results

    buckets: dict[str, list[dict]] = defaultdict(list)
    for result in results:
        site_name = str(result.get("site_name", "") or result.get("website_name", "")).strip() or "unknown"
        buckets[site_name].append(result)

    ordered_sites = sorted(
        buckets,
        key=lambda site_name: max(float(item.get("score", 0.0)) for item in buckets[site_name]),
        reverse=True,
    )

    diversified: list[dict] = []
    while ordered_sites and len(diversified) < top_k:
        next_round: list[str] = []
        for site_name in ordered_sites:
            if buckets[site_name] and len(diversified) < top_k:
                diversified.append(buckets[site_name].pop(0))
            if buckets[site_name]:
                next_round.append(site_name)
        ordered_sites = next_round

    return diversified
