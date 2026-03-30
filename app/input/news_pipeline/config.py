from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv, find_dotenv

# Automatically search up the folder tree to find the .env file
load_dotenv(find_dotenv())


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
    cycle_interval_minutes: int
    output_base_path: Path
    output_failed_jsonl_path: Path
    metadata_main_path: Path
    discovery_file_path: Path
    verbose_progress: bool
    progress_interval_sec: int
    insecure_ssl_fallback: bool
    user_agent: str


# ── Seed source definitions ────────────────────────────────────────────────────
#
# source_type:  "rss"  → RSSScraper   (feed URL, parsed via feedparser)
#               "web"  → WebScraper   (seed page, BFS link discovery, infinite)
#
# category:     used as metadata tag on every article from that source
#
# To add a source: append one dict to SEED_SOURCE_DEFINITIONS — nothing else needed.
#
SEED_SOURCE_DEFINITIONS: list[dict[str, str]] = [

    # ── Indian News — Web ──────────────────────────────────────────────────────
    # {"name": "ndtv",                "url": "https://www.ndtv.com/latest",                           "source_type": "web", "category": "india"},
    {"name": "times_of_india",      "url": "https://timesofindia.indiatimes.com/news",               "source_type": "web", "category": "india"},
    {"name": "the_hindu",           "url": "https://www.thehindu.com/news/",                         "source_type": "web", "category": "india"},
    {"name": "hindustan_times",     "url": "https://www.hindustantimes.com/latest-news",             "source_type": "web", "category": "india"},
    {"name": "india_today",         "url": "https://www.indiatoday.in/india",                        "source_type": "web", "category": "india"},
    {"name": "indian_express",      "url": "https://indianexpress.com/section/india/",               "source_type": "web", "category": "india"},

    # ── International News — Web ───────────────────────────────────────────────
    {"name": "bbc_news",            "url": "https://www.bbc.com/news",                              "source_type": "web", "category": "world"},
    {"name": "reuters",             "url": "https://www.reuters.com/news/",                          "source_type": "web", "category": "world"},
    {"name": "al_jazeera",          "url": "https://www.aljazeera.com/news/",                        "source_type": "web", "category": "world"},
    {"name": "the_guardian",        "url": "https://www.theguardian.com/world",                     "source_type": "web", "category": "world"},
    {"name": "associated_press",    "url": "https://apnews.com/",                                   "source_type": "web", "category": "world"},

    # ── Technology — Web ──────────────────────────────────────────────────────
    {"name": "techcrunch",          "url": "https://techcrunch.com/latest/",                        "source_type": "web", "category": "technology"},

    # ── Indian News — RSS ──────────────────────────────────────────────────────
    # {"name": "ndtv_rss",            "url": "https://feeds.feedburner.com/ndtvnews-top-stories",      "source_type": "rss", "category": "india"},
    {"name": "the_hindu_rss",       "url": "https://www.thehindu.com/news/feeder/default.rss",       "source_type": "rss", "category": "india"},
    {"name": "india_today_rss",     "url": "https://www.indiatoday.in/rss/home",                    "source_type": "rss", "category": "india"},
    {"name": "firstpost_rss",       "url": "https://www.firstpost.com/rss/india.xml",               "source_type": "rss", "category": "india"},
    {"name": "livemint_rss",        "url": "https://www.livemint.com/rss/news",                     "source_type": "rss", "category": "india_business"},

    # ── International News — RSS ───────────────────────────────────────────────
    {"name": "bbc_rss",             "url": "https://feeds.bbci.co.uk/news/rss.xml",                 "source_type": "rss", "category": "world"},
    {"name": "reuters_rss",         "url": "https://feeds.reuters.com/reuters/topNews",              "source_type": "rss", "category": "world"},
    {"name": "al_jazeera_rss",      "url": "https://www.aljazeera.com/xml/rss/all.xml",             "source_type": "rss", "category": "world"},
    {"name": "guardian_rss",        "url": "https://www.theguardian.com/world/rss",                 "source_type": "rss", "category": "world"},
    {"name": "ap_rss",              "url": "https://feeds.apnews.com/rss/apf-topnews",              "source_type": "rss", "category": "world"},
    {"name": "npr_rss",             "url": "https://feeds.npr.org/1001/rss.xml",                    "source_type": "rss", "category": "world"},
    # {"name": "france24_rss",        "url": "https://www.france24.com/en/rss",                       "source_type": "rss", "category": "world"},

    # ── Technology — RSS ──────────────────────────────────────────────────────
    {"name": "techcrunch_rss",      "url": "https://techcrunch.com/feed/",                          "source_type": "rss", "category": "technology"},
    {"name": "ars_technica_rss",    "url": "https://feeds.arstechnica.com/arstechnica/index",       "source_type": "rss", "category": "technology"},
    {"name": "the_verge_rss",       "url": "https://www.theverge.com/rss/index.xml",                "source_type": "rss", "category": "technology"},
    {"name": "wired_rss",           "url": "https://www.wired.com/feed/rss",                        "source_type": "rss", "category": "technology"},
    {"name": "engadget_rss",        "url": "https://www.engadget.com/rss.xml",                      "source_type": "rss", "category": "technology"},

    # ── AI / ML — RSS ─────────────────────────────────────────────────────────
    {"name": "mit_ai_rss",          "url": "https://news.mit.edu/topic/artificial-intelligence2/rss.xml", "source_type": "rss", "category": "ai"},
    {"name": "ai_news_rss",         "url": "https://artificialintelligence-news.com/feed/",         "source_type": "rss", "category": "ai"},

    # ── Science — RSS ─────────────────────────────────────────────────────────
    {"name": "nature_rss",          "url": "https://www.nature.com/nature.rss",                     "source_type": "rss", "category": "science"},
    {"name": "science_daily_rss",   "url": "https://www.sciencedaily.com/rss/top/science.xml",      "source_type": "rss", "category": "science"},
    {"name": "space_com_rss",       "url": "https://www.space.com/feeds/all",                       "source_type": "rss", "category": "science"},

    # ── Business / Finance — RSS ───────────────────────────────────────────────
    {"name": "cnbc_rss",            "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "source_type": "rss", "category": "business"},

    # ── Aggregators — RSS ──────────────────────────────────────────────────────
    {"name": "google_news_world",   "url": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXlnQVAB?hl=en-IN&gl=IN&ceid=IN%3Aen", "source_type": "rss", "category": "aggregator"},
    {"name": "google_news_india",   "url": "https://news.google.com/rss/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFYxWVd3U0FtVnVLQUFQAQ?hl=en-IN&gl=IN&ceid=IN%3Aen",       "source_type": "rss", "category": "aggregator"},
    {"name": "google_news_tech",    "url": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTlhRU0FtVnVHZ0pWVXlnQVAB?hl=en-IN&gl=IN&ceid=IN%3Aen", "source_type": "rss", "category": "aggregator"},
    {"name": "google_news_science", "url": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNR1QwTlRJU0FtVnVHZ0pWVXlnQVAB?hl=en-IN&gl=IN&ceid=IN%3Aen", "source_type": "rss", "category": "aggregator"},
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
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    return CrawlSettings(
        global_workers=int(os.getenv("CRAWLER_GLOBAL_WORKERS", "30")),
        per_domain_concurrency=int(os.getenv("CRAWLER_PER_DOMAIN_CONCURRENCY", "3")),
        request_timeout_sec=int(os.getenv("CRAWLER_REQUEST_TIMEOUT_SEC", "30")),
        max_retries=int(os.getenv("CRAWLER_MAX_RETRIES", "3")),
        backoff_base_sec=float(os.getenv("CRAWLER_BACKOFF_BASE_SEC", "1.5")),
        cycle_interval_minutes=int(os.getenv("CRAWLER_CYCLE_INTERVAL_MINUTES", "1")),
        output_base_path=Path(os.getenv("OUTPUT_BASE_PATH", str(PROJECT_ROOT / "app" / "input" / "data"))),
        output_failed_jsonl_path=Path(os.getenv("OUTPUT_FAILED_JSONL_PATH", str(PROJECT_ROOT / "data" / "failed_articles.jsonl"))),
        metadata_main_path=Path(os.getenv("MAIN_METADATA_PATH", str(PROJECT_ROOT / "data" / "main_metadata.json"))),
        discovery_file_path=Path(os.getenv("DISCOVERY_FILE_PATH", str(PROJECT_ROOT / "data" / "discovery_sources.json"))),
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