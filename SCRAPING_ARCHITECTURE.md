# Scraping Architecture — How Articles Are Collected & Stored

> Complete documentation of the news scraping pipeline, infinite-depth BFS crawling,
> RSS feed scraping, parallel JSON save, and the per-source deduplication model.

---

## Table of Contents

1. [High-Level Overview](#high-level-overview)
2. [File Structure](#file-structure)
3. [Pipeline Flow](#pipeline-flow)
4. [BFS Web Scraping (Infinite Depth)](#bfs-web-scraping-infinite-depth)
5. [RSS Scraping](#rss-scraping)
6. [Article Extraction](#article-extraction)
7. [Deduplication (Parallel Check + Add)](#deduplication-parallel-check--add)
8. [JSON Storage Schema](#json-storage-schema)
9. [Console Output](#console-output)
10. [Configuration](#configuration)
11. [Adding a New Source](#adding-a-new-source)

---

## High-Level Overview

The scraping pipeline is an **async, per-source concurrent system** that:

1. Loads **39 seed sources** (27 RSS + 12 Web) across 8 categories
2. Creates **one scraper per source** — each with its own BFS queue
3. Runs all scrapers **concurrently** via `asyncio.gather()`
4. Each scraper **saves articles to its own JSON file immediately** as they are found
5. Dedup is done via an **in-memory URL set per source** — check and add happen in parallel

```
    39 Sources (12 web + 27 rss)
         │
         ▼
    ┌────────────────────────────────────────────────┐
    │              NewsCrawler.run()                  │
    │                                                │
    │   asyncio.gather(                              │
    │       scraper_1.scrape(),  ← ndtv (BFS)        │
    │       scraper_2.scrape(),  ← bbc_news (BFS)    │
    │       scraper_3.scrape(),  ← bbc_rss (RSS)     │
    │       ...                                      │
    │       scraper_39.scrape(), ← google_news (RSS) │
    │   )                                            │
    │                                                │
    │   Shared: semaphore (30 concurrent requests)   │
    └────────────────────────────────────────────────┘
         │
         ▼
    data/web/ndtv.json          ← each scraper writes to its own file
    data/web/bbc_news.json
    data/rss/bbc_rss.json
    data/rss/ndtv_rss.json
    ...
```

---

## File Structure

```
Source-Bias-Analyzer/
│
├── app/
│   └── input/
│       ├── scraper.py                  ← Entry point (python app/input/scraper.py)
│       │
│       └── news_pipeline/
│           ├── __init__.py             ← Re-exports ScraperFactory
│           ├── config.py               ← 39 source definitions + CrawlSettings
│           ├── models.py               ← DetailedArticleRecord schema
│           ├── extractors.py           ← HTML/RSS parsing, text cleaning
│           ├── crawler.py              ← Orchestrator: one task per source
│           ├── scheduler.py            ← Entry: creates & runs crawler
│           │
│           └── scrapers/
│               ├── __init__.py         ← ScraperFactory
│               ├── base.py            ← BaseScraper + make_article() + JSON I/O
│               ├── rss_scraper.py     ← RSSScraper
│               └── web_scraper.py     ← WebScraper (infinite BFS)
│
└── data/                               ← OUTPUT (auto-created)
    ├── web/                            ← One JSON file per web source
    │   ├── ndtv.json
    │   ├── bbc_news.json
    │   └── ...
    └── rss/                            ← One JSON file per RSS source
        ├── bbc_rss.json
        ├── ndtv_rss.json
        └── ...
```

---

## Pipeline Flow

```
    python app/input/scraper.py
         │
    ┌────▼────────────────┐
    │  scheduler.main()   │
    └────┬────────────────┘
         │
    ┌────▼────────────────┐
    │  NewsCrawler.run()  │
    │                     │
    │  1. Load 39 sources │
    │  2. Open aiohttp    │
    │  3. Create semaphore│
    └────┬────────────────┘
         │
         │  For EACH source → create async task
         │
    ┌────▼──────────────────────────────────────────┐
    │  _run_source(source)                          │
    │                                               │
    │  ScraperFactory.for_source(source)            │
    │    ├── "rss" → RSSScraper                     │
    │    └── "web" → WebScraper                     │
    │                                               │
    │  scraper.scrape()  ← runs until exhausted     │
    └───────────────────────────────────────────────┘
         │
         │  Each scraper independently:
         │
    ┌────▼──────────────────────────────────────────┐
    │  1. Load known_urls from its JSON file        │
    │  2. Run BFS (web) or process entries (rss)    │
    │  3. For each page:                            │
    │     a. CHECK: url in known_urls? → skip       │
    │     b. Fetch HTML                             │
    │     c. Extract text, tags, summary            │
    │     d. ADD: save to JSON + known_urls.add()   │
    │  4. Extract links → add to BFS queue          │
    │  5. Repeat until queue empty                  │
    └───────────────────────────────────────────────┘
```

---

## BFS Web Scraping (Infinite Depth)

The `WebScraper` implements **infinite Breadth-First Search** link discovery.
There is **NO depth limit** — the BFS runs until every reachable same-domain
page has been visited.

```
    SEED URL  (e.g. https://www.ndtv.com/latest)
    ┌───────────────────────────────────────────────────┐
    │                  BFS QUEUE (FIFO)                  │
    │  [seed]                                           │
    │  [link_A, link_B, link_C]           ← from seed  │
    │  [link_B, link_C, D, E, F]         ← from A      │
    │  [link_C, D, E, F, G, H]          ← from B       │
    │  [D, E, F, G, H, I, J, K]         ← from C       │
    │  ...continues until queue is empty...             │
    └───────────────────────────────────────────────────┘
```

### Algorithm (Pseudocode)

```python
queue = deque([seed_url])
local_seen = {seed_url}
known_urls = load_from_json()       # what's already saved

while queue:                        # NO depth limit — runs until empty
    url = queue.popleft()           # BFS: FIFO order

    if url in known_urls:           # PARALLEL CHECK: O(1) set lookup
        skip
        continue

    html = fetch(url)
    content = extract_article(html)

    if len(content) > 200:
        article = make_article(...)
        save_to_json(article)       # PARALLEL ADD: immediate write
        known_urls.add(url)         # update set so next iteration sees it

    for link in extract_links(html):
        if same_domain(link) and link not in local_seen and link not in known_urls:
            local_seen.add(link)
            queue.append(link)      # add to BACK of queue (BFS)

    sleep(0.15)                     # polite delay
```

### Key Properties

| Property | Behavior |
|---|---|
| **Queue type** | `deque.popleft()` — true BFS (FIFO) |
| **Depth limit** | **NONE** — runs until queue is empty |
| **Domain constraint** | Only follows same-domain links |
| **Content threshold** | > 200 chars of extracted text to be saved |
| **Dedup (check)** | `url in known_urls` (O(1) in-memory set) |
| **Dedup (add)** | `known_urls.add(url)` + append to JSON |
| **Politeness** | 0.15s sleep between requests |
| **Rate limiting** | Shared semaphore (30 concurrent across all scrapers) |

---

## RSS Scraping

The `RSSScraper` processes RSS/Atom feeds:

```
    Feed URL → Parse entries → For each entry:
         │
         ├── Check known_urls → skip if exists
         ├── Fetch full article page
         ├── Extract text + tags + summary
         └── Save to JSON immediately
```

All **27 major RSS feeds** are included without exception:
- 5 Indian: NDTV, The Hindu, India Today, Firstpost, LiveMint
- 7 International: BBC, Reuters, Al Jazeera, Guardian, AP, NPR, France24
- 5 Tech: TechCrunch, Ars Technica, The Verge, Wired, Engadget
- 2 AI: MIT AI, AI News
- 3 Science: Nature, ScienceDaily, Space.com
- 1 Business: CNBC
- 4 Aggregators: Google News (World, India, Tech, Science)

---

## Article Extraction

`extractors.py` uses a **multi-strategy extraction pipeline** — the longest
text output wins:

| Strategy | Library | Method |
|---|---|---|
| `bs4_article_main` | BeautifulSoup | `<article>` or `<main>` tag content |
| `bs4_body_paragraphs` | BeautifulSoup | All `<p>` tags from `<body>` |
| `readability` | readability-lxml | Mozilla Reader View algorithm |
| `trafilatura` | trafilatura | ML-based content extraction |

---

## Deduplication (Parallel Check + Add)

Each scraper has its own `known_urls` set that mirrors its JSON file:

```
    ┌─────────────────────────────────────────────────┐
    │           Per-Source known_urls Set              │
    │                                                 │
    │  At startup: loaded from data/web/source.json   │
    │                                                 │
    │  CHECK: url in known_urls → O(1), instant       │
    │  ADD:   known_urls.add(url) → immediate         │
    │         + append to JSON file on disk            │
    │                                                 │
    │  ✓ Check and Add happen in the same BFS loop    │
    │  ✓ The set is always up-to-date                 │
    │  ✓ No cross-source dedup needed (per-source)    │
    └─────────────────────────────────────────────────┘
```

**"Parallel" means:** the check (is this URL already saved?) and the add
(save new article to JSON) happen continuously as the BFS runs.  The
in-memory set ensures the check is instantaneous, and the JSON is updated
immediately after each save.  There is no batching — articles appear in
JSON the moment they're discovered.

---

## JSON Storage Schema

### Output Directory

```
data/
├── web/                    ← One file per web scraper
│   ├── ndtv.json
│   ├── bbc_news.json
│   ├── reuters.json
│   └── ...
└── rss/                    ← One file per RSS scraper
    ├── bbc_rss.json
    ├── ndtv_rss.json
    └── ...
```

### Article Record Schema (matches `DetailedArticleRecord`)

```json
{
  "id":           "a1b2c3d4...",
  "url":          "https://www.bbc.com/news/world-12345",
  "title":        "Breaking: Major Event Unfolds",
  "text":         "Full extracted article body...",
  "hash":         "e5f6a7b8...",
  "source":       "bbc_news",
  "category":     "world",
  "published_at": "2026-03-29T10:30:00+00:00",
  "scraped_at":   "2026-03-29T11:45:22+00:00",
  "language":     "en",
  "tags":         ["europe", "politics", "breaking"],
  "summary":      "First 3 sentences of the article..."
}
```

### Field Reference

| Field | Type | Source |
|---|---|---|
| `id` | string | MD5 hash of URL |
| `url` | string | Canonical URL of the article |
| `title` | string | From og:title / `<title>` / readability |
| `text` | string | Full article body (best extraction wins) |
| `hash` | string | MD5 hash of text (content fingerprint) |
| `source` | string | Source name from config |
| `category` | string | Category label from config |
| `published_at` | string | ISO 8601 from feed/page metadata |
| `scraped_at` | string | ISO 8601 UTC when we scraped it |
| `language` | string | Default "en" |
| `tags` | string[] | From meta keywords + frequency analysis |
| `summary` | string | First 3 sentences, max 600 chars |

---

## Console Output

The scraper produces clear, color-coded console output:

```
======================================================================
🚀 NEWS CRAWLER STARTING
   Total sources: 39 (12 web + 27 rss)
   Concurrency:   30 workers
   Output:        data/
======================================================================

======================================================================
🌐 [WEB BFS START] ndtv
   Seed: https://www.ndtv.com/latest
   Already in JSON: 0 articles
======================================================================

  🔍 [SCRAPING]  ndtv                 | (0 queued) https://www.ndtv.com/latest
  🔗 [LINKS]     ndtv                 | +45 new links, queue: 45
  🔍 [SCRAPING]  ndtv                 | (44 queued) https://www.ndtv.com/india-news/...
  ✅ [SAVED]     ndtv                 | "PM Modi Addresses Parliament on..." 
                                      | → data/web/ndtv.json
  ⏭️  [SKIP]     ndtv                 | Already in JSON: https://...

======================================================================
📡 [RSS START] bbc_rss
   Feed: https://feeds.bbci.co.uk/news/rss.xml
   Already in JSON: 12 articles
======================================================================

  📋 [ENTRIES]   bbc_rss              | Found 30 entries in feed
  🔍 [SCRAPING]  bbc_rss              | [1/30] https://www.bbc.com/news/...
  ✅ [SAVED]     bbc_rss              | "Climate Summit Opens in..." 
  ⏭️  [SKIP]     bbc_rss              | Already in JSON: https://...
```

---

## Configuration

### Sources (39 total)

| Category | Web Sources | RSS Sources |
|---|---|---|
| India | ndtv, times_of_india, the_hindu, hindustan_times, india_today, indian_express | ndtv_rss, the_hindu_rss, india_today_rss, firstpost_rss, livemint_rss |
| World | bbc_news, reuters, al_jazeera, the_guardian, associated_press | bbc_rss, reuters_rss, al_jazeera_rss, guardian_rss, ap_rss, npr_rss, france24_rss |
| Technology | techcrunch | techcrunch_rss, ars_technica_rss, the_verge_rss, wired_rss, engadget_rss |
| AI | — | mit_ai_rss, ai_news_rss |
| Science | — | nature_rss, science_daily_rss, space_com_rss |
| Business | — | cnbc_rss |
| Aggregator | — | google_news_world, google_news_india, google_news_tech, google_news_science |

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `CRAWLER_GLOBAL_WORKERS` | `30` | Max concurrent HTTP requests |
| `CRAWLER_REQUEST_TIMEOUT_SEC` | `30` | HTTP timeout per request |
| `CRAWLER_MAX_RETRIES` | `3` | Retry count with exponential backoff |
| `OUTPUT_BASE_PATH` | `data` | Root of output directory |

---

## Adding a New Source

One line in `config.py`:

```python
{"name": "my_source", "url": "https://example.com/news", "source_type": "web", "category": "custom"}
```

The system automatically creates a scraper, runs infinite BFS, and saves to `data/web/my_source.json`.

---

## Running

```bash
# From app/input/ directory:
python scraper.py

# Or from project root:
python -m app.input.scraper
```

The crawler runs all 39 scrapers concurrently until every BFS queue is exhausted.
