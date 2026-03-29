"""
web_scraper.py
--------------
Infinite-depth BFS crawler for web sources.

Algorithm
---------
1. Start with the seed URL in a FIFO queue.
2. Pop the front URL from the queue.
3. Skip if already in this source's JSON (known_urls set — O(1) check).
4. Fetch the page HTML.
5. Extract article text — if content > 200 chars, save to JSON immediately.
6. Extract all same-domain links from the page, add new ones to the back of the queue.
7. Repeat until the queue is empty (all reachable same-domain pages visited).

There is NO depth limit.  The BFS runs until the domain is exhausted.
Dedup is per-source: a URL is skipped if it already exists in that source's JSON file.
"""
from __future__ import annotations

import asyncio
from collections import deque
from typing import Any
from urllib.parse import urlparse

from .base import BaseScraper, make_article
from ..extractors import (
    extract_links_from_html,
    clean_article_html,
    summarize_text,
    generate_tags,
)


class WebScraper(BaseScraper):

    async def scrape(self) -> None:
        seed_url = self.source.url
        seed_domain = urlparse(seed_url).netloc

        # BFS queue: FIFO — true breadth-first traversal, NO depth limit
        queue: deque[str] = deque([seed_url])

        # local_seen prevents adding the same link to the queue twice
        # within a single scrape session (even before it's saved to JSON)
        local_seen: set[str] = {seed_url}

        saved_count = 0
        visited_count = 0

        print(f"\n\033[96m{'='*70}\033[0m")
        print(f"\033[96m🌐 [WEB BFS START] {self.source.name}\033[0m")
        print(f"\033[96m   Seed: {seed_url}\033[0m")
        print(f"\033[96m   Already in JSON: {len(self.known_urls)} articles\033[0m")
        print(f"\033[96m{'='*70}\033[0m\n")

        while queue:
            current_url = queue.popleft()

            # ── Parallel check: skip if already in this source's JSON ─────
            if self._is_known(current_url):
                print(f"  \033[90m⏭️  [SKIP]\033[0m     {self.source.name:<20} | Already in JSON: {current_url[:80]}")
                continue

            visited_count += 1
            print(f"  \033[93m🔍 [SCRAPING]\033[0m  {self.source.name:<20} | ({len(queue)} queued) {current_url[:90]}")

            # ── Fetch the page ────────────────────────────────────────────
            html, final_url = await self._fetch_text(current_url)
            if not html:
                print(f"  \033[91m❌ [FAILED]\033[0m   {self.source.name:<20} | Could not fetch: {current_url[:80]}")
                continue

            # ── Extract article content ───────────────────────────────────
            extracted = clean_article_html(html, base_url=final_url)
            content = str(extracted.get("content", ""))

            # Save if we got meaningful text (skip the seed page itself
            # unless it also has substantial article content)
            if len(content) > 200:
                headline = str(extracted.get("headline", "Untitled"))
                keyword_tags = extracted.get("keyword_tags", [])
                tags = generate_tags(headline, content, keyword_tags)
                summary = summarize_text(content, max_sentences=3)

                article = make_article(
                    url=final_url,
                    title=headline,
                    text=content,
                    summary=summary,
                    tags=tags,
                    source=self.source.name,
                    category=self.source.category,
                    published_at=None,
                )

                # ── Parallel add: save to JSON + update known_urls set ────
                self._save_article(article)
                saved_count += 1

            # ── Extract links and enqueue new same-domain ones ────────────
            links = extract_links_from_html(html, base_url=final_url)
            new_links = 0
            for link_url, _ in links:
                link_domain = urlparse(link_url).netloc
                if (
                    link_domain == seed_domain
                    and link_url not in local_seen
                    and not self._is_known(link_url)
                ):
                    local_seen.add(link_url)
                    queue.append(link_url)
                    new_links += 1

            if new_links > 0:
                print(f"  \033[94m🔗 [LINKS]\033[0m    {self.source.name:<20} | +{new_links} new links, queue: {len(queue)}")

            # Polite delay between requests
            await asyncio.sleep(0.15)

        print(f"\n\033[96m{'='*70}\033[0m")
        print(f"\033[96m🏁 [WEB BFS DONE] {self.source.name}\033[0m")
        print(f"\033[96m   Visited: {visited_count} pages | Saved: {saved_count} articles\033[0m")
        print(f"\033[96m   Total in JSON: {len(self.known_urls)}\033[0m")
        print(f"\033[96m{'='*70}\033[0m\n")