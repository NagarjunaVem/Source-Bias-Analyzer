"""
scrapers/base.py
----------------
Abstract contract every scraper must satisfy.

Each concrete scraper:
  - Manages its own BFS queue (WebScraper) or feed entries (RSSScraper).
  - Loads existing URLs from its output JSON at startup.
  - Saves articles to JSON immediately as they are found (parallel check + add).
  - Produces articles matching the DetailedArticleRecord schema from models.py.

The crawler assigns one scraper per source and runs them all concurrently.
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from collections import deque
from hashlib import md5
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

from ..config import CrawlSettings, Source


# ── Canonical Article schema (matches DetailedArticleRecord) ──────────────────

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
    language: str = "en",
) -> dict[str, Any]:
    """
    Produces the canonical Article dict matching DetailedArticleRecord from models.py:
        id, url, title, text, hash, source, published_at, language, tags, summary
    Plus extras: category, scraped_at.
    """
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id":           md5(url.encode()).hexdigest(),
        "url":          url,
        "title":        title,
        "text":         text,
        "hash":         md5(text.encode()).hexdigest(),
        "source":       source,
        "category":     category,
        "published_at": published_at or now,
        "scraped_at":   now,
        "language":     language,
        "tags":         tags,
        "summary":      summary,
    }


# ── JSON I/O helpers ─────────────────────────────────────────────────────────

def get_output_path(output_base: Path, source_type: str, source_name: str) -> Path:
    """Route output to  data/rss/<name>.json  or  data/web/<name>.json."""
    subdir = "rss" if source_type == "rss" else "web"
    dest = output_base / subdir
    dest.mkdir(parents=True, exist_ok=True)
    return dest / f"{source_name}.json"


def load_existing_urls(json_path: Path) -> set[str]:
    """Load all URLs already stored in a source's JSON file for dedup."""
    if not json_path.exists():
        return set()
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {
                entry.get("url", "").strip()
                for entry in data
                if isinstance(entry, dict) and entry.get("url")
            }
    except Exception:
        pass
    return set()


def append_article_to_json(json_path: Path, article: dict) -> None:
    """Append a single article to its source JSON array file."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if json_path.exists():
        try:
            existing = json.loads(json_path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
    existing.append(article)
    json_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── Base scraper ──────────────────────────────────────────────────────────────

class BaseScraper(ABC):
    """
    Abstract base.  Every source type gets exactly one subclass.

    Constructor signature is fixed so ScraperFactory can call it generically:
        scraper_cls(source=source, session=session, settings=settings)

    Each scraper:
      1. Loads its known_urls from its output JSON at startup.
      2. Has its own BFS queue (web) or processes feed entries (rss).
      3. Saves articles immediately and adds URLs to known_urls in real-time.
    """

    def __init__(
        self,
        *,
        source: Source,
        session: aiohttp.ClientSession,
        settings: CrawlSettings,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        self.source = source
        self.session = session
        self.settings = settings
        self.logger = logging.getLogger(f"scraper.{source.name}")

        # Rate limiting: shared semaphore across all scrapers
        self.semaphore = semaphore or asyncio.Semaphore(30)

        # Output file for this specific source
        self.json_path = get_output_path(
            settings.output_base_path, source.source_type, source.name
        )

        # In-memory URL set mirrors the JSON file for O(1) dedup checks.
        # Loaded at startup; updated on every save.
        # This IS the "parallel check" — the set is always current.
        self.known_urls: set[str] = load_existing_urls(self.json_path)

    # ── Public API ────────────────────────────────────────────────────────────

    @abstractmethod
    async def scrape(self) -> None:
        """
        Entry point called by the crawler.
        Scrapes articles and saves them directly to JSON.
        Runs until the BFS queue is exhausted (infinite depth).
        """

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _is_known(self, url: str) -> bool:
        """Check if URL is already in this source's JSON (O(1) set lookup)."""
        return url in self.known_urls

    def _save_article(self, article: dict) -> None:
        """
        Save article to JSON and update the in-memory URL set.
        This is the 'parallel add' — the set is updated immediately
        so concurrent BFS iterations see the new URL right away.
        """
        url = article["url"]
        if url in self.known_urls:
            return  # already saved (race guard)

        self.known_urls.add(url)
        append_article_to_json(self.json_path, article)

        title_preview = article.get("title", "")[:60]
        print(f"  \033[92m✅ [SAVED]\033[0m    {self.source.name:<20} | \"{title_preview}\"")
        print(f"             {'':20} | → {self.json_path}")

    async def _fetch_text(self, url: str) -> tuple[str, str]:
        """
        GET *url*, return (body_text, final_url).
        Returns ("", url) on any error — callers must handle empty strings.
        Uses the shared semaphore for global rate limiting.
        """
        async with self.semaphore:
            for attempt in range(self.settings.max_retries):
                try:
                    async with self.session.get(
                        url,
                        headers={"User-Agent": self.settings.user_agent},
                        ssl=not self.settings.insecure_ssl_fallback,
                    ) as resp:
                        text = await resp.text(errors="replace")
                        return text, str(resp.url)
                except Exception:
                    await asyncio.sleep(
                        self.settings.backoff_base_sec * (2 ** attempt)
                    )

        self.logger.debug("fetch failed after retries: %s", url)
        return "", url