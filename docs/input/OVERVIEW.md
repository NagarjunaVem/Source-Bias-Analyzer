# 🗞️ `input/` — Data Ingestion Layer: Complete Pipeline Overview

> **Directory:** `app/input/`
> **Role:** Fetches, cleans, deduplicates, and queues news articles from 30+ sources for downstream embedding & FAISS indexing.

---

## 📁 Directory Structure

```
input/
├── loader.py                  ← Stub: reads article text for bias test
├── scraper.py                 ← Entry point (calls scheduler.main)
│
├── data/                      ← 🟡 Scraper workspace (ephemeral)
│   ├── web/                   ← Live JSON files per web source
│   │   ├── bbc_news.json
│   │   └── the_guardian.json
│   ├── rss/                   ← Live JSON files per RSS source
│   │   ├── bbc_rss.json
│   │   └── guardian_rss.json
│   └── indexing_queue/        ← Completed cycles waiting for FAISS
│       └── cycle_N_YYYYMMDD_HHMMSS/
│           ├── web/
│           └── rss/
│
└── news_pipeline/             ← Core scraper + scheduler code
    ├── config.py              ← Settings, paths, source registry
    ├── crawler.py             ← Async task runner
    ├── scheduler.py           ← Producer + Consumer loops
    ├── metadata_gate.py       ← Global URL dedup gate
    ├── models.py              ← Article schema (dataclasses)
    ├── extractors.py          ← HTML → clean text
    ├── queue_embedder.py      ← [RETIRED] raw .npy embedder
    ├── test_classifier.py     ← URL allow/block classifier
    └── scrapers/
        ├── __init__.py        ← ScraperFactory
        ├── base.py            ← BaseScraper + JSON I/O
        ├── web_scraper.py     ← BFS web crawler
        └── rss_scraper.py     ← RSS feed parser
```

---

## 🔄 High-Level Pipeline Flow

```mermaid
flowchart TD
    A([🚀 scraper.py\nEntry Point]) --> B[scheduler.py\nOrchestrator]

    B --> C[🏭 PRODUCER\ncrawler_loop]
    B --> D[🧠 CONSUMER\nindex_worker]

    C --> E[config.py\nLoad Sources + Settings]
    E --> F[crawler.py\nNewsCrawler.run]

    F --> G{Source Type?}
    G -->|rss| H[RSSScraper\nrss_scraper.py]
    G -->|web| I[WebScraper\nweb_scraper.py]

    H --> J[extractors.py\nparse_rss_entries]
    I --> K[extractors.py\nextract_links_from_html]

    J --> L[_fetch_text\nbase.py]
    K --> L

    L --> M[extractors.py\nclean_article_html]
    M --> N[make_article\nbase.py]
    N --> O[models.py\nDetailedArticleRecord schema]
    O --> P[💾 data/web/*.json\ndata/rss/*.json]

    P --> Q[move_to_index_queue\nscheduler.py]
    Q --> R[📦 indexing_queue/\ncycle_N_TIMESTAMP/]

    R --> D
    D --> S[_append_to_master_jsonl]
    D --> T[build_index.process_cycle\n🔗 embeddings layer]
    D --> U[_append_to_universal_db]
    D --> V[🗑️ Delete cycle folder]

    style A fill:#4CAF50,color:#fff
    style B fill:#2196F3,color:#fff
    style C fill:#FF9800,color:#fff
    style D fill:#9C27B0,color:#fff
    style P fill:#607D8B,color:#fff
    style R fill:#795548,color:#fff
    style T fill:#E91E63,color:#fff
```

---

## 🔁 Producer–Consumer Model

The scheduler runs **two concurrent async loops**:

| Role | Loop | Responsibility |
|------|------|----------------|
| 🏭 **Producer** | `crawler_loop()` | Runs scrapers for N minutes, then moves data to `indexing_queue/` |
| 🧠 **Consumer** | `index_worker()` | Watches queue, embeds + indexes each cycle, then deletes it |

```mermaid
sequenceDiagram
    participant SL as crawler_loop (Producer)
    participant CQ as indexing_queue/
    participant IW as index_worker (Consumer)
    participant FB as FAISS / Embeddings

    loop Every cycle_interval_minutes
        SL->>SL: Run NewsCrawler (all sources concurrently)
        SL->>CQ: move_to_index_queue() → cycle_N_TIMESTAMP/
        SL->>SL: Sleep 5s → restart
    end

    loop Every 60s
        IW->>CQ: Scan for cycle folders
        CQ-->>IW: cycle_N found
        IW->>IW: _append_to_master_jsonl()
        IW->>FB: build_index.process_cycle()
        IW->>IW: _append_to_universal_db()
        IW->>CQ: shutil.rmtree(cycle folder)
    end
```

---

## 🧩 Component Responsibilities (Quick Reference)

| File | What it does | Cross-link |
|------|-------------|-----------|
| `loader.py` | Reads pasted article text (bias test stub) | [loader.md](loader.md) |
| `scraper.py` | CLI entry point | [scraper.md](scraper.md) |
| `config.py` | All env vars, 30+ source definitions, path config | [config.md](config.md) |
| `crawler.py` | One async task per source, shared semaphore | [crawler.md](crawler.md) |
| `scheduler.py` | Producer + Consumer orchestration | [scheduler.md](scheduler.md) |
| `metadata_gate.py` | Read-only global URL dedup | [metadata_gate.md](metadata_gate.md) |
| `models.py` | `DetailedArticleRecord`, `ArticleTask`, etc. | [models.md](models.md) |
| `extractors.py` | HTML cleaning, RSS parsing, tag generation | [extractors.md](extractors.md) |
| `queue_embedder.py` | ⚠️ Retired raw `.npy` embedding helper | [queue_embedder.md](queue_embedder.md) |
| `test_classifier.py` | URL article/non-article scorer | [test_classifier.md](test_classifier.md) |
| `scrapers/__init__.py` | `ScraperFactory` routing | [scrapers_init.md](scrapers_init.md) |
| `scrapers/base.py` | `BaseScraper` + JSON I/O helpers | [base.md](base.md) |
| `scrapers/web_scraper.py` | Infinite BFS crawler | [web_scraper.md](web_scraper.md) |
| `scrapers/rss_scraper.py` | RSS feed fetcher + article extractor | [rss_scraper.md](rss_scraper.md) |

---

## 📦 Article JSON Schema

Every saved article follows the `DetailedArticleRecord` schema from [`models.py`](models.md):

```json
{
  "id":           "md5(url)",
  "url":          "https://...",
  "title":        "Article Headline",
  "text":         "Full extracted body text...",
  "hash":         "md5(text)",
  "source":       "bbc_rss",
  "category":     "world",
  "published_at": "2024-03-15T10:30:00",
  "scraped_at":   "2024-03-15T11:00:00Z",
  "language":     "en",
  "tags":         ["politics", "uk", "election"],
  "summary":      "First 3 sentences of the article..."
}
```

---

## 🌐 Source Categories

| Category | Example Sources |
|----------|----------------|
| `india` | Times of India, The Hindu, India Today, Hindustan Times |
| `world` | BBC, Reuters, Al Jazeera, The Guardian, AP |
| `technology` | TechCrunch, Ars Technica, The Verge, Wired, Engadget |
| `ai` | MIT AI News, AI News RSS |
| `science` | Nature, ScienceDaily, Space.com |
| `business` | CNBC, Livemint |
| `aggregator` | Google News (World, India, Tech, Science) |

---

## ⚙️ Key Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `CRAWLER_GLOBAL_WORKERS` | `30` | Max concurrent HTTP requests |
| `CRAWLER_PER_DOMAIN_CONCURRENCY` | `3` | Per-domain rate limiting |
| `CRAWLER_CYCLE_INTERVAL_MINUTES` | `120` | How long each scrape cycle runs |
| `CRAWLER_REQUEST_TIMEOUT_SEC` | `30` | HTTP timeout per request |
| `OUTPUT_BASE_PATH` | `app/input/data` | Where JSON files are written |
| `MAIN_METADATA_PATH` | `data/main_metadata.json` | Global URL dedup file |

---

## 🔗 Related Layers

- **Embeddings Layer** → `app/embeddings/` — consumes `indexing_queue/` cycle folders
- **FAISS Index** → `app/embeddings/build_index.py` — called by `index_worker`
- **Universal DB** → `data/web/`, `data/rss/` — permanent article archive
