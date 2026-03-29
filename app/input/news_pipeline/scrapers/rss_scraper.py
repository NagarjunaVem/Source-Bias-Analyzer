"""
rss_scraper.py
--------------
Fetches RSS/Atom feeds, follows each entry link to extract the full
article body, and saves articles to JSON immediately with parallel dedup.

Flow
----
1. Fetch the RSS XML from the feed URL.
2. Parse entries using feedparser → list of {url, title, published_at}.
3. For each entry:
   a. Check if URL is already in this source's JSON (known_urls set).
   b. If new → fetch the full article page.
   c. Extract text, tags, summary.
   d. Save to JSON immediately.
"""
from __future__ import annotations

import asyncio
from typing import Any

from .base import BaseScraper, make_article
from ..extractors import (
    parse_rss_entries,
    clean_article_html,
    summarize_text,
    generate_tags,
)


class RSSScraper(BaseScraper):

    async def scrape(self) -> None:
        print(f"\n\033[95m{'='*70}\033[0m")
        print(f"\033[95m📡 [RSS START] {self.source.name}\033[0m")
        print(f"\033[95m   Feed: {self.source.url}\033[0m")
        print(f"\033[95m   Already in JSON: {len(self.known_urls)} articles\033[0m")
        print(f"\033[95m{'='*70}\033[0m\n")

        # 1. Fetch the RSS XML
        text, final_url = await self._fetch_text(self.source.url)
        if not text:
            print(f"  \033[91m❌ [FAILED]\033[0m   {self.source.name:<20} | Could not fetch feed")
            return

        # 2. Parse entries
        entries = parse_rss_entries(text)
        print(f"  \033[94m📋 [ENTRIES]\033[0m  {self.source.name:<20} | Found {len(entries)} entries in feed")

        saved_count = 0

        # 3. Process each entry
        for i, entry in enumerate(entries, 1):
            url = entry.get("url")
            if not url:
                continue

            # ── Parallel check: skip if already in this source's JSON ─────
            if self._is_known(url):
                print(f"  \033[90m⏭️  [SKIP]\033[0m     {self.source.name:<20} | Already in JSON: {url[:80]}")
                continue

            print(f"  \033[93m🔍 [SCRAPING]\033[0m  {self.source.name:<20} | [{i}/{len(entries)}] {url[:90]}")

            # Fetch the full article page
            article_html, actual_url = await self._fetch_text(url)

            if not article_html:
                print(f"  \033[91m❌ [FAILED]\033[0m   {self.source.name:<20} | Could not fetch: {url[:80]}")
                continue

            # Check the actual URL (after redirects) too
            if self._is_known(actual_url):
                print(f"  \033[90m⏭️  [SKIP]\033[0m     {self.source.name:<20} | Redirect already in JSON: {actual_url[:80]}")
                continue

            # Extract article content
            extracted = clean_article_html(article_html, base_url=actual_url)
            content = str(extracted.get("content", ""))

            if not content or len(content) < 100:
                print(f"  \033[90m⏭️  [SKIP]\033[0m     {self.source.name:<20} | Too short ({len(content)} chars)")
                continue

            headline = entry.get("title") or str(extracted.get("headline", "Untitled"))
            keyword_tags = extracted.get("keyword_tags", [])
            tags = generate_tags(headline, content, keyword_tags)
            summary = summarize_text(content, max_sentences=3)

            article = make_article(
                url=actual_url,
                title=headline,
                text=content,
                summary=summary,
                tags=tags,
                source=self.source.name,
                category=self.source.category,
                published_at=entry.get("published_at"),
            )

            # ── Parallel add: save to JSON + update known_urls set ────────
            self._save_article(article)
            saved_count += 1

            # Small delay between fetches
            await asyncio.sleep(0.1)

        print(f"\n\033[95m{'='*70}\033[0m")
        print(f"\033[95m🏁 [RSS DONE] {self.source.name}\033[0m")
        print(f"\033[95m   Saved: {saved_count} new articles\033[0m")
        print(f"\033[95m   Total in JSON: {len(self.known_urls)}\033[0m")
        print(f"\033[95m{'='*70}\033[0m\n")