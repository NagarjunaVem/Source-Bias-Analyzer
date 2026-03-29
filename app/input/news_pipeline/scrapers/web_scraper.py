"""
web_scraper.py
--------------
Implements a BFS crawler to discover and scrape articles from web sources.
"""
from __future__ import annotations
import asyncio
from typing import Any
from urllib.parse import urlparse

from .base import BaseScraper, make_article
from ..extractors import (
    extract_links_from_html,
    is_probable_article_url,
    clean_article_html,
    summarize_text
)

class WebScraper(BaseScraper):
    async def scrape(self) -> list[dict[str, Any]]:
        self.logger.info("Starting Web BFS for: %s", self.source.url)
        
        # Queue stores tuples of (url, depth)
        queue = [(self.source.url, 0)]
        
        # local_seen prevents infinite loops within a single scrape cycle
        local_seen = {self.source.url}
        
        articles: list[dict[str, Any]] = []
        seed_domain = urlparse(self.source.url).netloc
        
        # Fallback max depth if set to 0 to prevent true infinite loops
        max_depth = self.settings.max_discovery_depth if self.settings.max_discovery_depth > 0 else 3

        while queue:
            current_url, depth = queue.pop(0)

            # Strict global dedup check
            if current_url in self.global_seen and current_url != self.source.url:
                continue

            text, final_url = await self._fetch_text(current_url)
            if not text:
                continue

            # If it looks like an article URL, parse it
            if current_url != self.source.url and is_probable_article_url(final_url):
                extracted = clean_article_html(text, base_url=final_url)
                content = str(extracted.get("content", ""))

                # Only save if we actually extracted meaningful text
                if len(content) > 150: 
                    articles.append(make_article(
                        url=final_url,
                        title=str(extracted.get("headline", "Untitled")),
                        text=content,
                        summary=summarize_text(content, max_sentences=3),
                        tags=extracted.get("keyword_tags", []),
                        source=self.source.name,
                        category=self.source.category,
                        published_at=None
                    ))

            # Stop extracting new links if we've hit our depth limit
            if depth < max_depth:
                links = extract_links_from_html(text, base_url=final_url)
                for link_url, _ in links:
                    link_domain = urlparse(link_url).netloc
                    
                    # BFS Rules: Stay on the same domain, skip seen URLs
                    if link_domain == seed_domain and link_url not in local_seen and link_url not in self.global_seen:
                        local_seen.add(link_url)
                        queue.append((link_url, depth + 1))

            # Polite delay between internal requests
            await asyncio.sleep(0.2)

        self.logger.info("Web %s yielded %d new articles.", self.source.name, len(articles))
        return articles