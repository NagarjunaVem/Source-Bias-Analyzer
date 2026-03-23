from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True, slots=True)
class Source:
    name: str
    url: str
    source_type: str
    category: str


@dataclass(frozen=True, slots=True)
class CrawlSettings:
    global_workers: int
    per_domain_concurrency: int
    request_timeout_sec: int
    max_retries: int
    backoff_base_sec: float
    max_discovery_depth: int
    cycle_interval_minutes: int
    output_detailed_jsonl_path: Path
    output_failed_jsonl_path: Path
    metadata_main_path: Path
    discovery_file_path: Path
    verbose_progress: bool
    progress_interval_sec: int
    insecure_ssl_fallback: bool
    user_agent: str


SEED_SOURCE_DEFINITIONS: list[dict[str, Any]] = [
    # India web
    {"name": "the_hindu_web", "url": "https://www.thehindu.com/latest-news/", "source_type": "web", "category": "india"},
    {"name": "indianexpress_web", "url": "https://indianexpress.com/latest-news/", "source_type": "web", "category": "india"},
    {"name": "ndtv_web", "url": "https://www.ndtv.com/latest", "source_type": "web", "category": "india"},
    {"name": "hindustantimes_web", "url": "https://www.hindustantimes.com/latest-news", "source_type": "web", "category": "india"},
    {"name": "timesofindia_web", "url": "https://timesofindia.indiatimes.com/home/headlines", "source_type": "web", "category": "india"},
    {"name": "news18_web", "url": "https://www.news18.com/news/", "source_type": "web", "category": "india"},
    {"name": "indiatoday_web", "url": "https://www.indiatoday.in/latest-news", "source_type": "web", "category": "india"},
    {"name": "deccanherald_web", "url": "https://www.deccanherald.com/latest-news", "source_type": "web", "category": "india"},
    {"name": "theweek_web", "url": "https://www.theweek.in/news", "source_type": "web", "category": "india"},
    {"name": "business_standard_web", "url": "https://www.business-standard.com/latest-news", "source_type": "web", "category": "india"},
    {"name": "economictimes_web", "url": "https://economictimes.indiatimes.com/news", "source_type": "web", "category": "india"},
    {"name": "livemint_web", "url": "https://www.livemint.com/latest-news", "source_type": "web", "category": "india"},
    {"name": "tribuneindia_web", "url": "https://www.tribuneindia.com/news", "source_type": "web", "category": "india"},
    {"name": "freepressjournal_web", "url": "https://www.freepressjournal.in/latest-news", "source_type": "web", "category": "india"},
    {"name": "firstpost_web", "url": "https://www.firstpost.com/news", "source_type": "web", "category": "india"},
    {"name": "scroll_web", "url": "https://scroll.in/latest", "source_type": "web", "category": "india"},
    {"name": "theprint_web", "url": "https://theprint.in/", "source_type": "web", "category": "india"},
    {"name": "outlookindia_web", "url": "https://www.outlookindia.com/national", "source_type": "web", "category": "india"},
    {"name": "telegraphindia_web", "url": "https://www.telegraphindia.com/", "source_type": "web", "category": "india"},
    {"name": "mid_day_web", "url": "https://www.mid-day.com/news", "source_type": "web", "category": "india"},
    # India RSS
    {"name": "the_hindu_rss", "url": "https://www.thehindu.com/news/feeder/default.rss", "source_type": "rss", "category": "india"},
    {"name": "indianexpress_rss", "url": "https://indianexpress.com/feed/", "source_type": "rss", "category": "india"},
    {"name": "ndtv_rss", "url": "https://feeds.feedburner.com/ndtvnews-top-stories", "source_type": "rss", "category": "india"},
    {"name": "hindustantimes_rss", "url": "https://www.hindustantimes.com/feeds/rss/latest/rssfeed.xml", "source_type": "rss", "category": "india"},
    {"name": "timesofindia_rss", "url": "https://timesofindia.indiatimes.com/rssfeedstopstories.cms", "source_type": "rss", "category": "india"},
    {"name": "news18_rss", "url": "https://www.news18.com/rss/india.xml", "source_type": "rss", "category": "india"},
    {"name": "indiatoday_rss", "url": "https://www.indiatoday.in/rss/home", "source_type": "rss", "category": "india"},
    {"name": "deccanherald_rss", "url": "https://www.deccanherald.com/rss", "source_type": "rss", "category": "india"},
    {"name": "livemint_rss", "url": "https://www.livemint.com/rss/news", "source_type": "rss", "category": "india"},
    {"name": "business_standard_rss", "url": "https://www.business-standard.com/rss/latest.rss", "source_type": "rss", "category": "india"},
    # International web
    {"name": "bbc_web", "url": "https://www.bbc.com/news", "source_type": "web", "category": "international"},
    {"name": "cnn_web", "url": "https://www.cnn.com/world", "source_type": "web", "category": "international"},
    {"name": "reuters_web", "url": "https://www.reuters.com/", "source_type": "web", "category": "international"},
    {"name": "reuters_world", "url": "https://www.reuters.com/world/", "source_type": "web", "category": "international"},
    {"name": "aljazeera_web", "url": "https://www.aljazeera.com/news/", "source_type": "web", "category": "international"},
    {"name": "guardian_web", "url": "https://www.theguardian.com/international", "source_type": "web", "category": "international"},
    {"name": "nytimes_web", "url": "https://www.nytimes.com/section/world", "source_type": "web", "category": "international"},
    {"name": "washingtonpost_web", "url": "https://www.washingtonpost.com/world/", "source_type": "web", "category": "international"},
    {"name": "bloomberg_web", "url": "https://www.bloomberg.com/latest", "source_type": "web", "category": "international"},
    {"name": "apnews_web", "url": "https://apnews.com/hub/world-news", "source_type": "web", "category": "international"},
    {"name": "euronews_web", "url": "https://www.euronews.com/news", "source_type": "web", "category": "international"},
    {"name": "france24_web", "url": "https://www.france24.com/en/news/", "source_type": "web", "category": "international"},
    {"name": "dw_web", "url": "https://www.dw.com/en/top-stories/s-9097", "source_type": "web", "category": "international"},
    {"name": "skynews_web", "url": "https://www.skynews.com.au/world-news", "source_type": "web", "category": "international"},
    {"name": "abcnews_web", "url": "https://abcnews.go.com/International", "source_type": "web", "category": "international"},
    {"name": "cbsnews_web", "url": "https://www.cbsnews.com/world/", "source_type": "web", "category": "international"},
    {"name": "nbcnews_web", "url": "https://www.nbcnews.com/world", "source_type": "web", "category": "international"},
    {"name": "usnews_web", "url": "https://www.usnews.com/news/world", "source_type": "web", "category": "international"},
    {"name": "scmp_web", "url": "https://www.scmp.com/news/world", "source_type": "web", "category": "international"},
    {"name": "japantimes_web", "url": "https://www.japantimes.co.jp/news/", "source_type": "web", "category": "international"},
    {"name": "channelnewsasia_web", "url": "https://www.channelnewsasia.com/world", "source_type": "web", "category": "international"},
    {"name": "who_news_web", "url": "https://www.who.int/news", "source_type": "web", "category": "international"},
    {"name": "world_bank_news_web", "url": "https://www.worldbank.org/ext/en/news", "source_type": "web", "category": "international"},
    # International RSS
    {"name": "bbc_rss", "url": "http://feeds.bbci.co.uk/news/rss.xml", "source_type": "rss", "category": "international"},
    {"name": "cnn_rss", "url": "http://rss.cnn.com/rss/edition.rss", "source_type": "rss", "category": "international"},
    {"name": "reuters_rss", "url": "https://www.reutersagency.com/feed/?best-topics=news&post_type=best", "source_type": "rss", "category": "international"},
    {"name": "aljazeera_rss", "url": "https://www.aljazeera.com/xml/rss/all.xml", "source_type": "rss", "category": "international"},
    {"name": "guardian_rss", "url": "https://www.theguardian.com/world/rss", "source_type": "rss", "category": "international"},
    {"name": "nytimes_rss", "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "source_type": "rss", "category": "international"},
    {"name": "washingtonpost_rss", "url": "https://feeds.washingtonpost.com/rss/world", "source_type": "rss", "category": "international"},
    {"name": "euronews_rss", "url": "https://www.euronews.com/rss?level=theme&name=news", "source_type": "rss", "category": "international"},
    {"name": "apnews_rss", "url": "https://apnews.com/rss", "source_type": "rss", "category": "international"},
    {"name": "france24_rss", "url": "https://www.france24.com/en/rss", "source_type": "rss", "category": "international"},
    # Aggregators web
    {"name": "google_news_web", "url": "https://news.google.com/", "source_type": "web", "category": "aggregator"},
    {"name": "msn_web", "url": "https://www.msn.com/en-in/news", "source_type": "web", "category": "aggregator"},
    {"name": "inshorts_web", "url": "https://inshorts.com/en/read", "source_type": "web", "category": "aggregator"},
    {"name": "onlinenewspapers_web", "url": "https://onlinenewspapers.com/", "source_type": "web", "category": "aggregator"},
    # Aggregators RSS
    {"name": "google_news_rss", "url": "https://news.google.com/rss", "source_type": "rss", "category": "aggregator"},
    {"name": "msn_rss", "url": "https://www.msn.com/en-in/feed", "source_type": "rss", "category": "aggregator"},
    # Google topic + section web and RSS
    {
        "name": "google_topic_web",
        "url": "https://news.google.com/topics/CAAqJQgKIh9DQkFTRVFvSUwyMHZNRE55YXpBU0JXVnVMVWRDS0FBUAE?hl=en-IN&gl=IN&ceid=IN%3Aen",
        "source_type": "google_topic",
        "category": "google_news",
    },
    {
        "name": "google_topic_rss",
        "url": "https://news.google.com/rss/topics/CAAqJQgKIh9DQkFTRVFvSUwyMHZNRE55YXpBU0JXVnVMVWRDS0FBUAE?hl=en-IN&gl=IN&ceid=IN%3Aen",
        "source_type": "rss",
        "category": "google_news",
    },
    {
        "name": "google_section_web",
        "url": "https://news.google.com/topics/CAAqHAgKIhZDQklTQ2pvSWJHOWpZV3hmZGpJb0FBUAE/sections/CAQiUENCSVNOam9JYkc5allXeGZkakpDRUd4dlkyRnNYM1l5WDNObFkzUnBiMjV5Q3hJSkwyMHZNR1kxZGpnd2Vnc0tDUzl0THpCbU5YWTRNQ2dBKjEIACotCAoiJ0NCSVNGem9JYkc5allXeGZkako2Q3dvSkwyMHZNR1kxZGpnd0tBQVABUAE?hl=en-IN&gl=IN&ceid=IN%3Aen",
        "source_type": "google_section",
        "category": "google_news",
    },
    {
        "name": "google_section_rss",
        "url": "https://news.google.com/rss/topics/CAAqHAgKIhZDQklTQ2pvSWJHOWpZV3hmZGpJb0FBUAE/sections/CAQiUENCSVNOam9JYkc5allXeGZkakpDRUd4dlkyRnNYM1l5WDNObFkzUnBiMjV5Q3hJSkwyMHZNR1kxZGpnd2Vnc0tDUzl0THpCbU5YWTRNQ2dBKjEIACotCAoiJ0NCSVNGem9JYkc5allXeGZkako2Q3dvSkwyMHZNR1kxZGpnd0tBQVABUAE?hl=en-IN&gl=IN&ceid=IN%3Aen",
        "source_type": "rss",
        "category": "google_news",
    },
    # Additional source
    {"name": "wikipedia_current_events", "url": "https://en.wikipedia.org/wiki/Portal:Current_events", "source_type": "web", "category": "reference"},
]


def _dict_to_source(row: dict[str, Any]) -> Source | None:
    url = str(row.get("url", "")).strip()
    if not url:
        return None
    source_type = str(row.get("source_type", "web")).strip().lower() or "web"
    category = str(row.get("category", "custom")).strip().lower() or "custom"
    name = str(row.get("name", "")).strip()
    if not name:
        parsed = urlparse(url)
        host = parsed.netloc.replace(".", "_") or "custom_source"
        path = parsed.path.strip("/").replace("/", "_")
        name = f"{host}_{path}" if path else host
    return Source(name=name, url=url, source_type=source_type, category=category)


def load_discovery_sources(discovery_file_path: Path) -> list[Source]:
    if not discovery_file_path.exists():
        return []
    try:
        raw = json.loads(discovery_file_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    rows: list[dict[str, Any]]
    if isinstance(raw, dict) and isinstance(raw.get("sources"), list):
        rows = [x for x in raw["sources"] if isinstance(x, dict)]
    elif isinstance(raw, list):
        rows = [x for x in raw if isinstance(x, dict)]
    else:
        rows = []

    out: list[Source] = []
    for row in rows:
        source = _dict_to_source(row)
        if source:
            out.append(source)
    return out


def build_sources(discovery_file_path: Path) -> list[Source]:
    fixed: list[Source] = []
    for row in SEED_SOURCE_DEFINITIONS:
        source = _dict_to_source(row)
        if source:
            fixed.append(source)

    extra = load_discovery_sources(discovery_file_path)

    combined: list[Source] = []
    seen_urls: set[str] = set()
    for source in [*fixed, *extra]:
        key = source.url.strip().lower()
        if key in seen_urls:
            continue
        seen_urls.add(key)
        combined.append(source)
    return combined


def load_settings() -> CrawlSettings:
    return CrawlSettings(
        global_workers=int(os.getenv("CRAWLER_GLOBAL_WORKERS", "30")),
        per_domain_concurrency=int(os.getenv("CRAWLER_PER_DOMAIN_CONCURRENCY", "3")),
        request_timeout_sec=int(os.getenv("CRAWLER_REQUEST_TIMEOUT_SEC", "30")),
        max_retries=int(os.getenv("CRAWLER_MAX_RETRIES", "3")),
        backoff_base_sec=float(os.getenv("CRAWLER_BACKOFF_BASE_SEC", "1.5")),
        max_discovery_depth=int(os.getenv("CRAWLER_MAX_DISCOVERY_DEPTH", "2")),
        cycle_interval_minutes=int(os.getenv("CRAWLER_CYCLE_INTERVAL_MINUTES", "300")),
        output_detailed_jsonl_path=Path(os.getenv("OUTPUT_DETAILED_JSONL_PATH", "data/new_articles_detailed.jsonl")),
        output_failed_jsonl_path=Path(os.getenv("OUTPUT_FAILED_JSONL_PATH", "data/failed_articles.jsonl")),
        metadata_main_path=Path(os.getenv("MAIN_METADATA_PATH", "data/main_metadata.json")),
        discovery_file_path=Path(os.getenv("DISCOVERY_FILE_PATH", "data/discovery_sources.json")),
        verbose_progress=os.getenv("CRAWLER_VERBOSE_PROGRESS", "true").strip().lower() in {"1", "true", "yes", "on"},
        progress_interval_sec=int(os.getenv("CRAWLER_PROGRESS_INTERVAL_SEC", "5")),
        insecure_ssl_fallback=os.getenv("CRAWLER_INSECURE_SSL_FALLBACK", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        user_agent=os.getenv(
            "CRAWLER_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        ),
    )
