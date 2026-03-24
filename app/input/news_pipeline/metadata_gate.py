from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .extractors import canonicalize_url


class MetadataGate:
    """Read-only URL gate backed by an existing metadata JSON file."""

    def __init__(self, metadata_path: Path, logger: logging.Logger) -> None:
        self._metadata_path = metadata_path
        self._logger = logger
        self._known_urls: set[str] = set()
        self._loaded_once = False

    def load(self) -> None:
        self._known_urls = set()
        if not self._metadata_path.exists():
            self._loaded_once = True
            self._logger.warning("Metadata file not found: %s (continuing with empty gate)", self._metadata_path)
            return

        try:
            raw = json.loads(self._metadata_path.read_text(encoding="utf-8"))
        except Exception:
            self._loaded_once = True
            self._logger.exception("Failed to parse metadata file: %s", self._metadata_path)
            return

        self._collect_urls(raw)
        self._loaded_once = True
        self._logger.info("Metadata gate loaded %s known article URLs", len(self._known_urls))

    def exists(self, url: str) -> bool:
        if not self._loaded_once:
            self.load()
        normalized = canonicalize_url(url)
        return bool(normalized and normalized in self._known_urls)

    def _collect_urls(self, node: Any) -> None:
        if isinstance(node, dict):
            maybe_url = node.get("url")
            if isinstance(maybe_url, str):
                norm = canonicalize_url(maybe_url)
                if norm:
                    self._known_urls.add(norm)
            for value in node.values():
                self._collect_urls(value)
            return

        if isinstance(node, list):
            for item in node:
                self._collect_urls(item)
            return

