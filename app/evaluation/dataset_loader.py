"""Dataset loading utilities for pipeline evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_dataset(dataset_path: str | Path) -> list[dict[str, Any]]:
    """Load a labeled JSON dataset for evaluation."""
    path = Path(dataset_path)
    with path.open("r", encoding="utf-8") as file_handle:
        data = json.load(file_handle)

    if isinstance(data, dict):
        items = data.get("articles", [])
    else:
        items = data

    if not isinstance(items, list):
        raise ValueError("Dataset must be a list of article records or a dict containing 'articles'.")

    validated: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"Dataset item {index} must be a JSON object.")
        article_text = str(item.get("article_text", "") or item.get("text", "")).strip()
        if not article_text:
            raise ValueError(f"Dataset item {index} is missing article_text.")
        validated.append(
            {
                "id": item.get("id", index),
                "article_text": article_text,
                "expected_bias_label": str(item.get("expected_bias_label", item.get("label", ""))).strip().lower(),
                "expected_claim_stances": item.get("expected_claim_stances", {}),
                "metadata": item.get("metadata", {}),
            }
        )
    return validated

