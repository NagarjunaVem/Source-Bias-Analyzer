from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from hashlib import md5
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import CrawlSettings, build_sources, load_settings
from .extractors import (
    canonicalize_url,
    clean_article_html,
    extract_links_from_html,
    generate_tags,
    is_probable_article_url,
    summarize_text,
)
from .models import ArticleTask, FetchTask
from .test_classifier import classify_url


OUTPUT_FILE = Path(__file__).resolve().parents[3] / "data" / "articles.jsonl"
SEEN_FILE = Path(__file__).resolve().parents[3] / "data" / "seen_urls.json"


def save_to_jsonl(record):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_seen_urls():
    if not SEEN_FILE.exists():
        return set()
    try:
        return set(json.loads(SEEN_FILE.read_text()))
    except:
        return set()


def save_seen_urls(urls: set[str]):
    SEEN_FILE.write_text(json.dumps(list(urls), indent=2))


class NewsCrawler:
    def __init__(self, settings: CrawlSettings | None = None) -> None:
        self.settings = settings or load_settings()
        self.logger = self._build_logger()

        self.fetch_queue = asyncio.Queue()
        self.article_queue = asyncio.Queue()

        self.stop_event = asyncio.Event()
        self._lock = asyncio.Lock()

        self._session = None

        self._seen_urls = load_seen_urls()
        
        # HTTP session (retry)
        self._requests_session = requests.Session()
        self._requests_session.headers.update({"User-Agent": self.settings.user_agent})

        retry_cfg = Retry(
            total=self.settings.max_retries,
            backoff_factor=self.settings.backoff_base_sec,
            status_forcelist=(429, 500, 502, 503, 504),
        )
        adapter = HTTPAdapter(max_retries=retry_cfg)
        self._requests_session.mount("http://", adapter)
        self._requests_session.mount("https://", adapter)

        self._stats = defaultdict(int)

    async def run(self, run_once: bool = False):
        timeout = aiohttp.ClientTimeout(total=self.settings.request_timeout_sec)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            self._session = session

            fetch_workers = [
                asyncio.create_task(self._fetch_worker(i))
                for i in range(4)
            ]
            article_workers = [
                asyncio.create_task(self._article_worker(i))
                for i in range(6)
            ]

            try:
                if run_once:
                    await self._run_cycle()
                    await self.fetch_queue.join()
                    await self.article_queue.join()

                else:
                    while True:
                        self.logger.info("Starting new crawl cycle...")

                        await self._run_cycle()

                        # wait for completion
                        await self.fetch_queue.join()
                        await self.article_queue.join()

                        # save dedup state
                        save_seen_urls(self._seen_urls)
                        self.logger.info("Crawl cycle completed.")
                        await asyncio.sleep(self.settings.cycle_interval_minutes * 60)

            finally:
                self.stop_event.set()
                for t in fetch_workers + article_workers:
                    t.cancel()
                await asyncio.gather(*fetch_workers, *article_workers, return_exceptions=True)

    async def _run_cycle(self):
        sources = build_sources(self.settings.discovery_file_path)

        for source in sources:
            await self.fetch_queue.put(
                FetchTask(
                    source_name=source.name,
                    source_url=source.url,
                    source_type=source.source_type,
                    category=source.category,
                )
            )

    async def _fetch_worker(self, worker_id: int):
        while not self.stop_event.is_set():
            try:
                task = await asyncio.wait_for(self.fetch_queue.get(), timeout=1)
            except asyncio.TimeoutError:
                continue

            try:
                await self._process_fetch_task(task)
            finally:
                self.fetch_queue.task_done()

    async def _article_worker(self, worker_id: int):
        while not self.stop_event.is_set():
            try:
                task = await asyncio.wait_for(self.article_queue.get(), timeout=1)
            except asyncio.TimeoutError:
                continue

            try:
                await self._process_article_task(task)
            finally:
                self.article_queue.task_done()

    async def _process_fetch_task(self, task: FetchTask):
        text, final_url, _ = await self._fetch_text(task.source_url)
        if not text:
            return

        links = extract_links_from_html(text, base_url=final_url)

        for url, title in links:
            if is_probable_article_url(url) and classify_url(url):
                await self.article_queue.put(
                    ArticleTask(
                        url=url,
                        source_name=task.source_name,
                        category=task.category,
                        title_hint=title,
                    )
                )

    async def _process_article_task(self, task: ArticleTask):
        normalized_url = canonicalize_url(task.url)
        if not normalized_url:
            return

        async with self._lock:
            if normalized_url in self._seen_urls:
                return
            self._seen_urls.add(normalized_url)

        text, final_url, _ = await self._fetch_text(normalized_url)
        if not text:
            return

        extracted = clean_article_html(text, base_url=final_url)

        title = str(extracted.get("headline") or task.title_hint or "").strip()
        content = str(extracted.get("content") or "").strip()

        if not classify_url(normalized_url, content):
            return

        if len(content) < 100:
            content = text[:2000]

        if len(content) < 100:
            return

        summary = summarize_text(content)
        tags = generate_tags(title, content, [], max_tags=5) or ["news"]

        record = {
            "id": md5(normalized_url.encode()).hexdigest(),
            "url": normalized_url,
            "title": title,
            "text": content,
            "source": urlparse(normalized_url).netloc,
            "summary": summary,
            "tags": tags,
        }

        self.logger.info(f"Saved: {title[:60]}")
        save_to_jsonl(record)

    async def _fetch_text(self, url: str):
        try:
            async with self._session.get(url) as response:
                text = await response.text()
                return text, str(response.url), ""
        except Exception:
            return "", url, ""

    def _build_logger(self):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(message)s"
        )
        return logging.getLogger("news_pipeline")