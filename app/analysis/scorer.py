"""Scoring agent for source bias analysis using LangChain Ollama."""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

MODEL_NAME = "gemma2:9b"

SCORER_PROMPT = ChatPromptTemplate.from_template(
    """You are a strict source-bias scoring agent.

Score the input article using only the article text and the related evidence provided.

Return only valid JSON with this exact schema:
{{
  "bias_score": 0.0,
  "credibility_score": 0.0,
  "completeness_score": 0.0,
  "confidence": 0.0,
  "bias_type": "",
  "tone": "",
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
- All scores must be between 0 and 1
- Use only the provided text
- Do not hallucinate
- If evidence is weak, lower confidence
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


def _extract_json(text: str) -> str | None:
    """Extract the first JSON object from model output."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else None


def _fallback_result(raw_output: str) -> dict[str, Any]:
    """Return a safe fallback payload if JSON parsing fails."""
    return {
        "bias_score": 0.0,
        "credibility_score": 0.0,
        "completeness_score": 0.0,
        "confidence": 0.0,
        "bias_type": "Unknown",
        "tone": "Unknown",
        "explanation": "Model output could not be parsed as valid JSON.",
        "missing_viewpoints": [],
        "evidence_summary": "",
        "ranked_perspectives": [],
        "raw_output": raw_output,
    }


def score_article(article: str, evidence: str = "") -> dict[str, Any]:
    """Score one article against related evidence using LangChain Ollama."""
    chain = SCORER_PROMPT | SCORER_MODEL
    response = chain.invoke(
        {
            "article": article.strip(),
            "evidence": evidence.strip() or "No external evidence provided.",
        }
    )

    raw_output = response.content if isinstance(response.content, str) else str(response.content)
    json_text = _extract_json(raw_output)
    if not json_text:
        return _fallback_result(raw_output)

    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError:
        return _fallback_result(raw_output)

    return parsed
