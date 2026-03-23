from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from news_pipeline.models import DetailedArticleRecord


class JsonlWriter:
    def __init__(self, path: Path, logger: logging.Logger) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logger
        self.count = 0

    async def run(self, queue: asyncio.Queue[DetailedArticleRecord], stop_event: asyncio.Event) -> None:
        self._logger.info("Detailed JSON writer started: %s", self._path)
        with self._path.open("a", encoding="utf-8") as handle:
            while not stop_event.is_set() or not queue.empty():
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                try:
                    handle.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
                    handle.flush()
                    self.count += 1
                except Exception:
                    self._logger.exception("Failed writing detailed record: %s", item.url)
                finally:
                    queue.task_done()


class FailedJsonlWriter:
    def __init__(self, path: Path, logger: logging.Logger) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logger
        self.count = 0

    async def run(self, queue: asyncio.Queue[dict[str, Any]], stop_event: asyncio.Event) -> None:
        self._logger.info("Failure JSON writer started: %s", self._path)
        with self._path.open("a", encoding="utf-8") as handle:
            while not stop_event.is_set() or not queue.empty():
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                try:
                    handle.write(json.dumps(item, ensure_ascii=False) + "\n")
                    handle.flush()
                    self.count += 1
                except Exception:
                    self._logger.exception("Failed writing failure record")
                finally:
                    queue.task_done()

