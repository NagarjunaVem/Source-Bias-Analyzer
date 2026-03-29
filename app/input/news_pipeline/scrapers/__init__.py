"""
scrapers/__init__.py
--------------------
Public surface: ScraperFactory.
"""

from __future__ import annotations

import asyncio

import aiohttp

from .base import BaseScraper
from .rss_scraper import RSSScraper
from .web_scraper import WebScraper
from ..config import CrawlSettings, Source


class ScraperFactory:
    """
    Maps source_type → scraper class.
    """

    _REGISTRY: dict[str, type[BaseScraper]] = {
        "rss": RSSScraper,
        "web": WebScraper,
    }

    @classmethod
    def for_source(
        cls,
        source: Source,
        session: aiohttp.ClientSession,
        settings: CrawlSettings,
        semaphore: asyncio.Semaphore | None = None,
    ) -> BaseScraper:
        """
        Return the correct scraper instance for *source*.
        """
        scraper_cls = cls._REGISTRY.get(source.source_type, WebScraper)
        return scraper_cls(
            source=source,
            session=session,
            settings=settings,
            semaphore=semaphore,
        )


__all__ = ["BaseScraper", "RSSScraper", "WebScraper", "ScraperFactory"]
