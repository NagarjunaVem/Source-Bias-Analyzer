"""Structured JSON generation helpers with validation and retries."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

import requests

LOGGER = logging.getLogger(__name__)
OLLAMA_URL = "http://localhost:11434/api/generate"


class StructuredOutputError(RuntimeError):
    """Raised when a structured LLM response cannot be validated."""


Validator = Callable[[Any], Any]


@dataclass(slots=True)
class JsonGenerationResult:
    """Container for structured generation responses."""

    payload: Any
    raw_output: str
    attempts: int
    used_fallback: bool


def generate_validated_json(
    prompt: str,
    validator: Validator,
    fallback: Any,
    *,
    model: str = "qwen2.5:7b",
    timeout: int = 12,
    max_retries: int = 2,
) -> JsonGenerationResult:
    """Generate JSON with validation, retries, and a safe fallback."""
    last_raw_output = ""
    retry_prompt = prompt.strip()

    # Load-on-demand log for the user
    print(f"Loading {model} into RAM for calibrated scoring...")
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": model,
                    "prompt": retry_prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 700,
                    },
                    "keep_alive": "1m", 
                },
                timeout=timeout,
            )
            response.raise_for_status()
            raw_output = str(response.json().get("response", "")).strip()
            last_raw_output = raw_output
            parsed = json.loads(raw_output)
            validated = validator(parsed)
            return JsonGenerationResult(
                payload=validated,
                raw_output=raw_output,
                attempts=attempt,
                used_fallback=False,
            )
        except Exception as error:
            is_last_attempt = attempt == max_retries
            if is_last_attempt:
                LOGGER.warning(
                    "Structured generation attempt %s failed: %s. Falling back to heuristic result.",
                    attempt,
                    error,
                )
            else:
                LOGGER.warning("Structured generation attempt %s failed: %s", attempt, error)
            retry_prompt = (
                f"{prompt.strip()}\n\n"
                "Your previous response was invalid. Return only one JSON object that matches the requested schema."
            )

    return JsonGenerationResult(
        payload=fallback,
        raw_output=last_raw_output,
        attempts=max_retries,
        used_fallback=True,
    )


def ensure_dict(value: Any) -> dict[str, Any]:
    """Validate that the provided object is a dictionary."""
    if not isinstance(value, dict):
        raise StructuredOutputError("Expected a JSON object.")
    return value


def ensure_list(value: Any) -> list[Any]:
    """Validate that the provided object is a list."""
    if not isinstance(value, list):
        raise StructuredOutputError("Expected a JSON array.")
    return value
