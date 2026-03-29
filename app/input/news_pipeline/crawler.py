"""
crawler.py
----------
Main async crawling pipeline — one task per source, concurrent execution.

Architecture
------------
* For each source, one async task is created.
* Each task creates the right scraper (RSS or WebBFS) via ScraperFactory.
* Each scraper manages its own BFS queue, its own JSON file, and its own
  in-memory known_urls set for instant dedup.
* All tasks run concurrently via asyncio.gather().
* A shared semaphore limits total concurrent HTTP requests across all scrapers.

Output
------
    data/rss/<source_name>.json   (for RSS sources)
    data/web/<source_name>.json   (for Web sources)

Each JSON file is a valid JSON array of article objects matching
the DetailedArticleRecord schema from models.py.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import aiohttp

from .config import CrawlSettings, build_sources, load_settings
from .scrapers import ScraperFactory


class NewsCrawler:
    def __init__(self, settings: CrawlSettings | None = None) -> None:
        self.settings = settings or load_settings()
        self.logger = self._build_logger()

    # ── Public entry point ────────────────────────────────────────────────────

    async def run(self) -> None:
        """
        Main entry point.  Loads all sources, creates one async task per
        source, and runs them all concurrently.

        Each scraper runs until its BFS queue is exhausted (web) or all
        feed entries are processed (rss).
        """
        timeout = aiohttp.ClientTimeout(total=self.settings.request_timeout_sec)
        semaphore = asyncio.Semaphore(self.settings.global_workers)

        sources = build_sources(self.settings.discovery_file_path)

        rss_count = sum(1 for s in sources if s.source_type == "rss")
        web_count = sum(1 for s in sources if s.source_type == "web")

        print(f"\n\033[1m{'='*70}\033[0m")
        print(f"\033[1m🚀 NEWS CRAWLER STARTING\033[0m")
        print(f"\033[1m   Total sources: {len(sources)} ({web_count} web + {rss_count} rss)\033[0m")
        print(f"\033[1m   Concurrency:   {self.settings.global_workers} workers\033[0m")
        print(f"\033[1m   Output:        {self.settings.output_base_path}/\033[0m")
        print(f"\033[1m{'='*70}\033[0m\n")

        async with aiohttp.ClientSession(timeout=timeout) as session:
            tasks = []
            for source in sources:
                task = asyncio.create_task(
                    self._run_source(source, session, semaphore),
                    name=f"scraper-{source.name}",
                )
                tasks.append(task)

            # Run all scrapers concurrently. Each runs until BFS queue is empty.
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Report any failures
            for source, result in zip(sources, results):
                if isinstance(result, Exception):
                    self.logger.error(
                        "Scraper %s crashed: %s", source.name, result
                    )

        print(f"\n\033[1m{'='*70}\033[0m")
        print(f"\033[1m🏁 ALL SCRAPERS FINISHED\033[0m")
        print(f"\033[1m{'='*70}\033[0m\n")

    # ── Per-source task ───────────────────────────────────────────────────────

    async def _run_source(
        self,
        source,
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
    ) -> None:
        """
        Create a scraper for one source and run it.
        The scraper handles everything: BFS, extraction, dedup, JSON I/O.
        """
        try:
            scraper = ScraperFactory.for_source(
                source=source,
                session=session,
                settings=self.settings,
                semaphore=semaphore,
            )
            await scraper.scrape()
        except Exception as exc:
            self.logger.error(
                "Error in scraper %s: %s", source.name, exc, exc_info=True
            )

    # ── Logger ────────────────────────────────────────────────────────────────

    def _build_logger(self) -> logging.Logger:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(message)s",
        )
        return logging.getLogger("news_pipeline")