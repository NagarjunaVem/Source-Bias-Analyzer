"""
news_pipeline/__init__.py
-------------------------
Public surface: re-exports ScraperFactory and scraper classes from the
scrapers sub-package.
"""

from __future__ import annotations

from .scrapers import BaseScraper, RSSScraper, WebScraper, ScraperFactory

__all__ = ["BaseScraper", "RSSScraper", "WebScraper", "ScraperFactory"]