from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import md5
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp
import requests
from dateutil import parser as dt_parser
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from news_pipeline.config import CrawlSettings, Source, build_sources, load_settings
from news_pipeline.extractors import (
    canonicalize_url,
    clean_article_html,
    extract_links_from_html,
    generate_tags,
    is_probable_article_url,
    parse_rss_entries,
    summarize_text,
)
from news_pipeline.metadata_gate import MetadataGate
from news_pipeline.models import ArticleTask, DetailedArticleRecord, DiscoveryTask, FetchTask
from news_pipeline.storage import FailedJsonlWriter, JsonlWriter


class NewsCrawler:
    def __init__(self, settings: CrawlSettings | None = None) -> None:
        self.settings = settings or load_settings()
        self.logger = self._build_logger()
        self.metadata_gate = MetadataGate(self.settings.metadata_main_path, self.logger)

        self.fetch_queue: asyncio.Queue[FetchTask] = asyncio.Queue()
        self.article_queue: asyncio.Queue[ArticleTask] = asyncio.Queue()
        self.discovery_queue: asyncio.Queue[DiscoveryTask] = asyncio.Queue()
        self.write_queue: asyncio.Queue[DetailedArticleRecord] = asyncio.Queue()
        self.failed_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        self.stop_event = asyncio.Event()
        self._seen_article_urls: set[str] = set()
        self._seen_discovery_urls: set[str] = set()
        self._processed_article_urls: set[str] = set()
        self._lock = asyncio.Lock()

        self._domain_limits: dict[str, asyncio.Semaphore] = {}
        self._session: aiohttp.ClientSession | None = None
        self._requests_session = requests.Session()
        self._requests_session.headers.update({"User-Agent": self.settings.user_agent})
        self._requests_session.trust_env = True
        retry_cfg = Retry(
            total=self.settings.max_retries,
            connect=self.settings.max_retries,
            read=self.settings.max_retries,
            status=self.settings.max_retries,
            backoff_factor=self.settings.backoff_base_sec,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "HEAD"]),
        )
        adapter = HTTPAdapter(max_retries=retry_cfg, pool_connections=64, pool_maxsize=64)
        self._requests_session.mount("http://", adapter)
        self._requests_session.mount("https://", adapter)

        self._stats = defaultdict(int)
        self._active_sources: list[Source] = []

    async def run(self, run_once: bool = False) -> None:
        self.settings.output_detailed_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.output_failed_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.discovery_file_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_discovery_file(self.settings.discovery_file_path)

        timeout = aiohttp.ClientTimeout(total=self.settings.request_timeout_sec)
        connector = aiohttp.TCPConnector(
            limit=max(self.settings.global_workers * 2, 48),
            limit_per_host=max(self.settings.per_domain_concurrency, 1),
        )
        headers = {"User-Agent": self.settings.user_agent}

        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers=headers,
            trust_env=True,
        ) as session:
            self._session = session

            detailed_writer = JsonlWriter(self.settings.output_detailed_jsonl_path, self.logger)
            failed_writer = FailedJsonlWriter(self.settings.output_failed_jsonl_path, self.logger)

            writer_tasks = [
                asyncio.create_task(detailed_writer.run(self.write_queue, self.stop_event), name="detailed-writer"),
                asyncio.create_task(failed_writer.run(self.failed_queue, self.stop_event), name="failed-writer"),
            ]
            monitor_task = asyncio.create_task(self._progress_monitor(), name="progress-monitor")

            fetch_workers = max(4, self.settings.global_workers // 3)
            article_workers = max(6, self.settings.global_workers // 2)
            discovery_workers = max(4, self.settings.global_workers // 3)

            worker_tasks: list[asyncio.Task[Any]] = []
            worker_tasks.extend(
                asyncio.create_task(self._fetch_worker(i), name=f"fetch-{i}") for i in range(fetch_workers)
            )
            worker_tasks.extend(
                asyncio.create_task(self._article_worker(i), name=f"article-{i}") for i in range(article_workers)
            )
            worker_tasks.extend(
                asyncio.create_task(self._discovery_worker(i), name=f"discovery-{i}")
                for i in range(discovery_workers)
            )

            try:
                if run_once:
                    await self._run_cycle()
                else:
                    while not self.stop_event.is_set():
                        await self._run_cycle()
                        await self._sleep_until_next_cycle()
            except KeyboardInterrupt:
                self.logger.info("Stop requested by user.")
            finally:
                self.stop_event.set()
                await self._drain_queues()

                for task in worker_tasks + writer_tasks + [monitor_task]:
                    task.cancel()
                await asyncio.gather(*worker_tasks, *writer_tasks, monitor_task, return_exceptions=True)
                self._requests_session.close()

                self.logger.info(
                    "Stopped. scraped=%s skipped_known=%s failed=%s discovered=%s",
                    self._stats["scraped"],
                    self._stats["skipped_known"],
                    self._stats["failed"],
                    self._stats["discovered_links"],
                )

    async def _run_cycle(self) -> None:
        cycle_started = time.monotonic()
        self.metadata_gate.load()
        self._active_sources = build_sources(self.settings.discovery_file_path)

        self.logger.info("Cycle start: %s discovery sources", len(self._active_sources))
        for idx, source in enumerate(self._active_sources, start=1):
            await self.fetch_queue.put(
                FetchTask(
                    source_name=source.name,
                    source_url=source.url,
                    source_type=source.source_type,
                    category=source.category,
                )
            )
            self._progress("SOURCE_ENQUEUED", index=idx, total=len(self._active_sources), source=source.name, url=source.url)

        await self._wait_for_cycle_idle()
        elapsed = time.monotonic() - cycle_started
        self.logger.info(
            "Cycle complete in %.1fs | fetched=%s queued_articles=%s scraped=%s skipped_known=%s failed=%s",
            elapsed,
            self._stats["fetched_sources"],
            self._stats["queued_articles"],
            self._stats["scraped"],
            self._stats["skipped_known"],
            self._stats["failed"],
        )

    async def _fetch_worker(self, worker_id: int) -> None:
        while not self.stop_event.is_set() or not self.fetch_queue.empty():
            try:
                task = await asyncio.wait_for(self.fetch_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            try:
                await self._process_fetch_task(task)
            except Exception:
                self.logger.exception("Fetch worker %s crashed while processing %s", worker_id, task.source_url)
            finally:
                self.fetch_queue.task_done()

    async def _article_worker(self, worker_id: int) -> None:
        while not self.stop_event.is_set() or not self.article_queue.empty():
            try:
                task = await asyncio.wait_for(self.article_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            try:
                await self._process_article_task(task)
            except Exception:
                self.logger.exception("Article worker %s crashed for %s", worker_id, task.url)
            finally:
                self.article_queue.task_done()

    async def _discovery_worker(self, worker_id: int) -> None:
        while not self.stop_event.is_set() or not self.discovery_queue.empty():
            try:
                task = await asyncio.wait_for(self.discovery_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            try:
                await self._process_discovery_task(task)
            except Exception:
                self.logger.exception("Discovery worker %s crashed for %s", worker_id, task.url)
            finally:
                self.discovery_queue.task_done()

    async def _process_fetch_task(self, task: FetchTask) -> None:
        self._progress("FETCH_START", source=task.source_name, url=task.source_url, kind=task.source_type)
        text, final_url, content_type = await self._fetch_text(task.source_url)
        if not text:
            self._progress("FETCH_FAIL", source=task.source_name, url=task.source_url)
            return

        self._stats["fetched_sources"] += 1
        self._progress("FETCH_OK", source=task.source_name, url=final_url, content_type=content_type or "unknown")
        is_feed = self._is_feed_content(task, content_type, text)
        if is_feed:
            entries = parse_rss_entries(text)
            self._progress("FEED_PARSED", source=task.source_name, entries=len(entries))
            for item in entries:
                await self._enqueue_article(
                    url=str(item.get("url", "")),
                    source_name=task.source_name,
                    category=task.category,
                    title_hint=item.get("title"),
                    published_at=item.get("published_at"),
                    depth=0,
                    discovered_from=task.source_url,
                )
            return

        links = extract_links_from_html(text, base_url=final_url)[:150]
        self._progress("LISTING_PARSED", source=task.source_name, links=len(links))
        for link, anchor_text in links:
            await self._handle_discovered_link(
                url=link,
                anchor_text=anchor_text,
                source_name=task.source_name,
                category=task.category,
                depth=0,
                parent_url=final_url,
            )

    async def _process_discovery_task(self, task: DiscoveryTask) -> None:
        if task.depth > self.settings.max_discovery_depth:
            return
        self._progress("DISCOVERY_START", url=task.url, depth=task.depth, source=task.source_name)
        text, final_url, _ = await self._fetch_text(task.url)
        if not text:
            self._progress("DISCOVERY_FAIL", url=task.url, depth=task.depth)
            return

        links = extract_links_from_html(text, base_url=final_url)[:120]
        self._progress("DISCOVERY_PARSED", url=final_url, links=len(links), depth=task.depth)
        for link, anchor_text in links:
            await self._handle_discovered_link(
                url=link,
                anchor_text=anchor_text,
                source_name=task.source_name,
                category=task.category,
                depth=task.depth,
                parent_url=final_url,
            )

    async def _process_article_task(self, task: ArticleTask) -> None:
        self._progress("ARTICLE_START", url=task.url, source=task.source_name, depth=task.depth)
        resolved_url = await self._resolve_google_news_redirect(task.url)
        normalized_url = canonicalize_url(resolved_url)
        if not normalized_url:
            return

        if self.metadata_gate.exists(normalized_url):
            self._stats["skipped_known"] += 1
            self._progress("SKIP_KNOWN", url=normalized_url)
            return

        async with self._lock:
            if normalized_url in self._processed_article_urls:
                return
            self._processed_article_urls.add(normalized_url)

        text, final_url, _ = await self._fetch_text(normalized_url)
        if not text:
            self._progress("ARTICLE_FETCH_FAIL", url=normalized_url)
            return

        extracted = clean_article_html(text, base_url=final_url)
        title = (str(extracted.get("headline") or task.title_hint or "").strip()).lower()
        content = str(extracted.get("content") or "").strip().lower()
        if len(content) < 100:
            await self._record_failure(normalized_url, task.source_name, "content too short", "article")
            self._progress("ARTICLE_CONTENT_SHORT", url=normalized_url, length=len(content))
            return

        summary = await self._safe_summarize(content)
        keyword_tags = extracted.get("keyword_tags") if isinstance(extracted.get("keyword_tags"), list) else []
        tags = generate_tags(title, content, keyword_tags, max_tags=5)
        tags = tags[:5] if tags else ["news"]

        published_day = self._to_yyyy_mm_dd(task.published_at)
        source = self._infer_source_name(final_url, task.source_name)

        normalized_text_for_hash = " ".join(content.split())
        hash_value = md5(normalized_text_for_hash.encode("utf-8")).hexdigest()

        record = DetailedArticleRecord(
            id=hash_value,
            url=normalized_url,
            title=title,
            text=normalized_text_for_hash,
            hash=hash_value,
            source=source,
            published_at=published_day,
            language="en",
            tags=tags,
            summary=summary,
        )
        await self.write_queue.put(record)
        self._stats["scraped"] += 1
        self._progress(
            "ARTICLE_SCRAPED",
            url=normalized_url,
            chars=len(content),
            tags=",".join(tags),
            source=source,
            method=str(extracted.get("extraction_method") or "heuristic"),
        )

        links = extracted.get("links") if isinstance(extracted.get("links"), list) else []
        for link_tuple in links[:100]:
            if not isinstance(link_tuple, tuple) or len(link_tuple) != 2:
                continue
            link, anchor_text = link_tuple
            await self._handle_discovered_link(
                url=link,
                anchor_text=anchor_text,
                source_name=task.source_name,
                category=task.category,
                depth=task.depth + 1,
                parent_url=normalized_url,
            )

    async def _handle_discovered_link(
        self,
        url: str,
        anchor_text: str,
        source_name: str,
        category: str,
        depth: int,
        parent_url: str,
    ) -> None:
        normalized = canonicalize_url(url)
        if not normalized:
            return

        if self.metadata_gate.exists(normalized):
            self._stats["skipped_known"] += 1
            self._progress("SKIP_KNOWN", url=normalized)
            return

        if is_probable_article_url(normalized):
            await self._enqueue_article(
                url=normalized,
                source_name=source_name,
                category=category,
                title_hint=anchor_text or None,
                published_at=None,
                depth=depth + 1,
                discovered_from=parent_url,
            )
            return

        if depth + 1 > self.settings.max_discovery_depth:
            return

        if not self._is_discovery_candidate(normalized, parent_url):
            return

        async with self._lock:
            if normalized in self._seen_discovery_urls:
                return
            self._seen_discovery_urls.add(normalized)

        await self.discovery_queue.put(
            DiscoveryTask(
                url=normalized,
                source_name=source_name,
                category=category,
                depth=depth + 1,
                parent_url=parent_url,
            )
        )
        self._stats["discovered_links"] += 1
        self._progress("DISCOVERY_ENQUEUED", url=normalized, depth=depth + 1)

    async def _enqueue_article(
        self,
        url: str,
        source_name: str,
        category: str,
        title_hint: str | None,
        published_at: str | None,
        depth: int,
        discovered_from: str | None,
    ) -> None:
        normalized = canonicalize_url(url)
        if not normalized:
            return

        if self.metadata_gate.exists(normalized):
            self._stats["skipped_known"] += 1
            self._progress("SKIP_KNOWN", url=normalized)
            return

        async with self._lock:
            if normalized in self._seen_article_urls or normalized in self._processed_article_urls:
                return
            self._seen_article_urls.add(normalized)

        await self.article_queue.put(
            ArticleTask(
                url=normalized,
                source_name=source_name,
                category=category,
                title_hint=title_hint,
                published_at=published_at,
                depth=depth,
                discovered_from=discovered_from,
            )
        )
        self._stats["queued_articles"] += 1
        self._progress("ARTICLE_ENQUEUED", url=normalized, depth=depth, source=source_name)

    async def _fetch_text(self, url: str) -> tuple[str, str, str]:
        if self._session is None:
            return "", url, ""

        normalized = canonicalize_url(url)
        if not normalized:
            return "", url, ""

        parsed = urlparse(normalized)
        domain = parsed.netloc.lower()
        limiter = self._domain_limits.get(domain)
        if limiter is None:
            limiter = asyncio.Semaphore(self.settings.per_domain_concurrency)
            self._domain_limits[domain] = limiter

        variants = self._build_url_variants(normalized)
        methods_tried: list[str] = []
        last_error = "unknown fetch error"
        for attempt in range(self.settings.max_retries):
            for variant in variants:
                try:
                    methods_tried.append(f"aiohttp:{variant}")
                    text, final_url, content_type = await self._fetch_text_aiohttp(variant, limiter)
                    self._progress("FETCH_METHOD_OK", method="aiohttp", attempt=attempt + 1, url=variant)
                    return text, final_url, content_type
                except Exception as exc:
                    last_error = str(exc)
                    self._progress(
                        "FETCH_RETRY",
                        method="aiohttp",
                        attempt=attempt + 1,
                        url=variant,
                        error=self._trim_error(last_error),
                    )

                try:
                    methods_tried.append(f"requests_session:{variant}")
                    text, final_url, content_type = await asyncio.to_thread(
                        self._fetch_text_requests_session, variant, True
                    )
                    self._progress("FETCH_METHOD_OK", method="requests_session", attempt=attempt + 1, url=variant)
                    return text, final_url, content_type
                except Exception as exc:
                    last_error = str(exc)
                    self._progress(
                        "FETCH_RETRY",
                        method="requests_session",
                        attempt=attempt + 1,
                        url=variant,
                        error=self._trim_error(last_error),
                    )

                try:
                    methods_tried.append(f"requests_fresh:{variant}")
                    text, final_url, content_type = await asyncio.to_thread(
                        self._fetch_text_requests_fresh, variant, self.settings.insecure_ssl_fallback
                    )
                    self._progress("FETCH_METHOD_OK", method="requests_fresh", attempt=attempt + 1, url=variant)
                    return text, final_url, content_type
                except Exception as exc:
                    last_error = str(exc)
                    self._progress(
                        "FETCH_RETRY",
                        method="requests_fresh",
                        attempt=attempt + 1,
                        url=variant,
                        error=self._trim_error(last_error),
                    )

            await asyncio.sleep(self.settings.backoff_base_sec * (2 ** attempt))

        await self._record_failure(
            normalized,
            domain,
            last_error,
            "fetch_http",
            {
                "attempts": self.settings.max_retries,
                "methods_tried": methods_tried,
            },
        )
        return "", normalized, ""

    async def _fetch_text_aiohttp(self, url: str, limiter: asyncio.Semaphore) -> tuple[str, str, str]:
        if self._session is None:
            raise RuntimeError("HTTP session not available")
        async with limiter:
            async with self._session.get(url, allow_redirects=True) as response:
                if response.status >= 400:
                    raise RuntimeError(f"HTTP {response.status}")
                text = await response.text(errors="ignore")
                final_url = str(response.url)
                content_type = response.headers.get("Content-Type", "")
                return text, final_url, content_type

    def _fetch_text_requests_session(self, url: str, verify_ssl: bool) -> tuple[str, str, str]:
        response = self._requests_session.get(
            url,
            timeout=self.settings.request_timeout_sec,
            allow_redirects=True,
            verify=verify_ssl,
        )
        response.raise_for_status()
        return response.text, response.url, response.headers.get("Content-Type", "")

    def _fetch_text_requests_fresh(self, url: str, verify_ssl: bool) -> tuple[str, str, str]:
        with requests.Session() as session:
            session.headers.update({"User-Agent": self.settings.user_agent})
            session.trust_env = True
            response = session.get(
                url,
                timeout=self.settings.request_timeout_sec,
                allow_redirects=True,
                verify=verify_ssl,
            )
            response.raise_for_status()
            return response.text, response.url, response.headers.get("Content-Type", "")

    async def _resolve_google_news_redirect(self, url: str) -> str:
        parsed = urlparse(url)
        if "news.google.com" not in parsed.netloc.lower():
            return url

        params = parse_qs(parsed.query)
        for key in ("url", "q"):
            values = params.get(key) or []
            if values:
                candidate = canonicalize_url(values[0])
                if candidate:
                    return candidate

        if self._session is None:
            return url
        try:
            async with self._session.get(url, allow_redirects=True) as response:
                return str(response.url)
        except Exception:
            return url

    async def _record_failure(
        self,
        url: str,
        source_name: str,
        error: str,
        stage: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._stats["failed"] += 1
        payload: dict[str, Any] = {
            "url": url,
            "source": source_name,
            "stage": stage,
            "error": error,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            payload.update(extra)
        await self.failed_queue.put(payload)
        self._progress("FAIL", stage=stage, url=url, error=self._trim_error(error))

    def _is_feed_content(self, task: FetchTask, content_type: str, body: str) -> bool:
        if task.source_type == "rss":
            return True
        low = content_type.lower()
        if "xml" in low or "rss" in low or "atom" in low:
            return True
        head = body[:400].lower()
        return "<rss" in head or "<feed" in head

    def _is_discovery_candidate(self, url: str, parent_url: str) -> bool:
        target = urlparse(url).netloc.lower()
        parent = urlparse(parent_url).netloc.lower()
        if target == parent:
            return True
        low = url.lower()
        keywords = ("news", "latest", "world", "india", "story", "article", "topic", "section")
        return any(token in low for token in keywords)

    async def _safe_summarize(self, text: str) -> str:
        return summarize_text(text)

    def _to_yyyy_mm_dd(self, raw_date: str | None) -> str | None:
        if not raw_date:
            return None
        try:
            return dt_parser.parse(raw_date).date().isoformat()
        except Exception:
            return None

    def _infer_source_name(self, url: str, fallback: str) -> str:
        host = urlparse(url).netloc.lower().replace("www.", "")
        if not host:
            return fallback
        major = host.split(".")[0]
        if len(major) <= 4:
            return major.upper()
        return major.replace("-", " ").title()

    async def _wait_for_cycle_idle(self) -> None:
        idle_rounds = 0
        while idle_rounds < 3:
            await asyncio.sleep(1.0)
            if self.fetch_queue.empty() and self.article_queue.empty() and self.discovery_queue.empty():
                idle_rounds += 1
            else:
                idle_rounds = 0

        await self.fetch_queue.join()
        await self.article_queue.join()
        await self.discovery_queue.join()
        await self.write_queue.join()
        await self.failed_queue.join()

    async def _sleep_until_next_cycle(self) -> None:
        delay = max(1, self.settings.cycle_interval_minutes * 60)
        started = time.monotonic()
        while not self.stop_event.is_set():
            elapsed = time.monotonic() - started
            if elapsed >= delay:
                return
            await asyncio.sleep(1.0)

    async def _drain_queues(self) -> None:
        await self.fetch_queue.join()
        await self.article_queue.join()
        await self.discovery_queue.join()
        await self.write_queue.join()
        await self.failed_queue.join()

    async def _progress_monitor(self) -> None:
        while not self.stop_event.is_set():
            self._progress(
                "MONITOR",
                fetch_q=self.fetch_queue.qsize(),
                article_q=self.article_queue.qsize(),
                discovery_q=self.discovery_queue.qsize(),
                write_q=self.write_queue.qsize(),
                failed_q=self.failed_queue.qsize(),
                scraped=self._stats["scraped"],
                queued=self._stats["queued_articles"],
                failed=self._stats["failed"],
                skipped=self._stats["skipped_known"],
            )
            await asyncio.sleep(max(1, self.settings.progress_interval_sec))

    def _progress(self, step: str, **fields: object) -> None:
        if not self.settings.verbose_progress:
            return
        details = " ".join(f"{k}={fields[k]}" for k in sorted(fields))
        self.logger.info("[%s] %s", step, details)

    def _build_url_variants(self, url: str) -> list[str]:
        parsed = urlparse(url)
        host = parsed.netloc
        variants: list[str] = [url]

        if host.startswith("www."):
            variants.append(url.replace(f"//{host}", f"//{host[4:]}", 1))
        else:
            variants.append(url.replace(f"//{host}", f"//www.{host}", 1))

        if parsed.scheme == "https":
            variants.append(url.replace("https://", "http://", 1))
        elif parsed.scheme == "http":
            variants.append(url.replace("http://", "https://", 1))

        deduped: list[str] = []
        seen: set[str] = set()
        for item in variants:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped

    def _trim_error(self, error: str, limit: int = 180) -> str:
        message = (error or "").strip()
        if len(message) <= limit:
            return message
        return message[: limit - 3] + "..."

    def _build_logger(self) -> logging.Logger:
        logger = logging.getLogger("news_pipeline")
        if logger.handlers:
            return logger

        logger.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

        Path("logs").mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler("logs/news_pipeline.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        return logger

    def _ensure_discovery_file(self, path: Path) -> None:
        if path.exists():
            return
        payload = {
            "sources": [
                {
                    "name": "who_news_web",
                    "url": "https://www.who.int/news",
                    "source_type": "web",
                    "category": "international",
                },
                {
                    "name": "world_bank_news_web",
                    "url": "https://www.worldbank.org/ext/en/news",
                    "source_type": "web",
                    "category": "international",
                },
            ]
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
