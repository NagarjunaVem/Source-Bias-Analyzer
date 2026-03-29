"""
rss_scraper.py
--------------
Fetches RSS feeds, parses entries, and converts them to canonical Articles.
"""
from __future__ import annotations
from typing import Any

from .base import BaseScraper, make_article
from ..extractors import parse_rss_entries, clean_article_html

class RSSScraper(BaseScraper):
    async def scrape(self) -> list[dict[str, Any]]:
        self.logger.info("Fetching RSS feed: %s", self.source.url)
        
        # 1. Fetch the RSS XML
        text, final_url = await self._fetch_text(self.source.url)
        if not text:
            self.logger.warning("Failed to fetch or empty feed: %s", self.source.url)
            return []

        # 2. Parse entries using the extractor helper
        entries = parse_rss_entries(text)
        articles: list[dict[str, Any]] = []

        # 3. Process each entry
        for entry in entries:
            url = entry.get("url")
            
            # Skip invalid URLs or those already globally processed
            article_html, actual_url = await self._fetch_text(url)

            if not actual_url or actual_url in self.global_seen:
                continue
            content = ""
            tags = []
            
            if article_html:
                extracted = clean_article_html(article_html, base_url=actual_url)
                content = str(extracted.get("content", ""))
                tags = extracted.get("keyword_tags", [])
                
            if not content:
                continue # Skip items where we couldn't extract readable text

            articles.append(make_article(
                url=actual_url,
                title=entry.get("title") or "Untitled",
                text=content,
                summary="",  # Could hook up summarize_text() here if desired
                tags=tags,
                source=self.source.name,
                category=self.source.category,
                published_at=entry.get("published_at")
            ))

        self.logger.info("RSS %s yielded %d new articles.", self.source.name, len(articles))
        return articles