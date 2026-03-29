"""
scrapers/base.py
----------------
Abstract contract every scraper must satisfy.

Each concrete scraper is self-contained:
  - It knows how to fetch its source URL.
  - It knows how to parse the response into Article dicts.
  - It handles its own BFS / depth logic.
  - It never touches another scraper's logic.

The crawler just calls:
    articles = await scraper.scrape()

and receives a list of clean Article dicts.

global_seen
-----------
The crawler injects a shared ``global_seen`` set before calling scrape().
It contains every URL already persisted to disk across ALL previous crawl
cycles.  A scraper that sees a URL in global_seen must skip it entirely —
no fetch, no link-extraction — because we know its info AND all its
outgoing links were already captured in a prior run.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from hashlib import md5
from datetime import datetime, timezone
from typing import Any

import aiohttp

from ..config import CrawlSettings, Source


# ── Canonical Article schema ──────────────────────────────────────────────────

def make_article(
    *,
    url: str,
    title: str,
    text: str,
    summary: str,
    tags: list[str],
    source: str,
    category: str,
    published_at: str | None,
    scraped_at: str | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """
    Single place that produces the canonical Article dict.
    All scrapers call this — enforces the final JSON schema.
    """
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id":           md5(url.encode()).hexdigest(),
        "url":          url,
        "title":        title,
        "text":         text,
        "summary":      summary,
        "tags":         tags,
        "source":       source,
        "category":     category,
        "published_at": published_at or scraped_at or now,
        "updated_at":   updated_at,
        "scraped_at":   scraped_at or now,
    }


# ── Base scraper ──────────────────────────────────────────────────────────────

class BaseScraper(ABC):
    """
    Abstract base.  Every source type gets exactly one subclass.

    Constructor signature is fixed so ScraperFactory can call it generically:
        scraper_cls(source=source, session=session, settings=settings)

    global_seen is injected by the crawler after construction:
        scraper.global_seen = crawler._global_seen
    """

    def __init__(
        self,
        *,
        source: Source,
        session: aiohttp.ClientSession,
        settings: CrawlSettings,
    ) -> None:
        self.source = source
        self.session = session
        self.settings = settings
        self.logger = logging.getLogger(f"scraper.{source.name}")

        # Injected by the crawler before scrape() is called.
        # Contains every URL already persisted to any output JSON file.
        # A URL in global_seen means: article saved + links extracted → skip entirely.
        self.global_seen: set[str] = set()

    # ── Public API ────────────────────────────────────────────────────────────

    @abstractmethod
    async def scrape(self) -> list[dict[str, Any]]:
        """
        Entry point called by the crawler.
        Returns a (possibly empty) list of canonical Article dicts.
        """

    # ── Shared helpers ────────────────────────────────────────────────────────

    async def _fetch_text(self, url: str) -> tuple[str, str]:
        """
        GET *url*, return (body_text, final_url).
        Returns ("", url) on any error — callers must handle empty strings.
        """
        for i in range(self.settings.max_retries):
            try:
                async with self.session.get(
                    url,
                    headers={"User-Agent": self.settings.user_agent},
                    ssl=not self.settings.insecure_ssl_fallback,
                ) as resp:
                    text = await resp.text(errors="replace")
                    return text, str(resp.url)
            except Exception as exc:
                await asyncio.sleep(self.settings.backoff_base_sec * (2 ** i))

        self.logger.debug("fetch failed after retries: %s", url)
        return "", url
        