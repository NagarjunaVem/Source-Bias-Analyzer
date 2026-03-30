# 🏗️ Source-Bias-Analyzer: Full Architecture & Pipeline Reference

> **Every file. Every path. Every step. Pin-to-pin.**

---

## 📁 1. Complete Project Tree (Annotated)

```
C:\Users\NAGARJUNA\Desktop\New folder\                     ← PROJECT ROOT
│
├── app/                                                    ← ALL EXECUTABLE CODE
│   ├── main.py                                            ← Entry point (Terminal launcher)
│   ├── __init__.py
│   │
│   ├── input/                                             ← DATA INGESTION LAYER
│   │   ├── loader.py                                      ← Stub: reads article text for bias test
│   │   ├── scraper.py                                     ← Stub placeholder
│   │   │
│   │   ├── data/                                          ← 🟡 SCRAPER WORKSPACE (temporary)
│   │   │   ├── web/                                       ← Live JSON files written during a cycle
│   │   │   │   ├── bbc_news.json
│   │   │   │   ├── the_guardian.json
│   │   │   │   └── ... (one file per web source)
│   │   │   ├── rss/                                       ← Live JSON files written during a cycle
│   │   │   │   ├── bbc_rss.json
│   │   │   │   ├── guardian_rss.json
│   │   │   │   └── ... (one file per rss source)
│   │   │   └── indexing_queue/                            ← Completed cycle folders waiting for FAISS
│   │   │       └── cycle_N_YYYYMMDD_HHMMSS/              ← One folder per scraping cycle
│   │   │           ├── web/
│   │   │           │   ├── bbc_news.json
│   │   │           │   └── ...
│   │   │           └── rss/
│   │   │               ├── bbc_rss.json
│   │   │               └── ...
│   │   │
│   │   └── news_pipeline/                                 ← SCRAPER + SCHEDULER CODE
│   │       ├── config.py                                  ← All settings, paths, source definitions
│   │       ├── crawler.py                                 ← Async task runner (one task per source)
│   │       ├── scheduler.py                               ← Producer loop + Consumer loop
│   │       ├── metadata_gate.py                           ← URL dedup tracker (main_metadata.json)
│   │       ├── models.py                                  ← DetailedArticleRecord Pydantic schema
│   │       ├── extractors.py                              ← HTML → clean article text (trafilatura)
│   │       ├── queue_embedder.py                          ← [RETIRED] old raw .npy embedder
│   │       ├── test_classifier.py                         ← URL allow/block classifier
│   │       └── scrapers/
│   │           ├── __init__.py                            ← ScraperFactory (routes rss/web)
│   │           ├── base.py                                ← BaseScraper, JSON I/O, article schema
│   │           ├── web_scraper.py                         ← BFS web crawler
│   │           └── rss_scraper.py                         ← RSS feed parser (feedparser)
│   │
│   ├── embeddings/                                        ← AI VECTOR ENGINE
│   │   ├── build_index.py                                 ← Orchestrator: chunk→embed→FAISS
│   │   ├── chunker.py                                     ← Text → overlapping word windows
│   │   ├── embed.py                                       ← Ollama nomic-embed-text wrapper
│   │   ├── vector_store.py                                ← FAISS save/load/append helpers
│   │   ├── query.py                                       ← Standalone query test utility
│   │   ├── test_similarity.py                             ← Dev test
│   │   └── vector_index/                                  ← 🔵 PERMANENT FAISS DATABASES (21 domains)
│   │       ├── bbc_com/
│   │       │   ├── articles.index                         ← Binary FAISS (IndexFlatIP, cosine sim)
│   │       │   ├── embeddings.npy                         ← numpy float32 cache (for dedup)
│   │       │   └── metadata.json                          ← Chunk records (source, url, text, cache_key...)
│   │       ├── theguardian_com/
│   │       ├── techcrunch_com/
│   │       ├── aljazeera_com/
│   │       ├── apnews_com/
│   │       ├── arstechnica_com/
│   │       ├── artificialintelligence_news_com/
│   │       ├── cnbc_com/
│   │       ├── engadget_com/
│   │       ├── hindustantimes_com/
│   │       ├── indianexpress_com/
│   │       ├── indiatoday_in/
│   │       ├── livemint_com/
│   │       ├── npr_org/
│   │       ├── sciencedaily_com/
│   │       ├── space_com/
│   │       ├── thehindu_com/
│   │       ├── theverge_com/
│   │       ├── timesofindia_indiatimes_com/
│   │       ├── wired_com/
│   │       └── aajtak_in/
│   │
│   ├── retrieval/                                         ← SEARCH & RETRIEVAL LAYER
│   │   ├── faiss_retriever.py                             ← Main search orchestrator
│   │   ├── index_loader.py                                ← Loads all 21 domain indexes + BM25
│   │   ├── hybrid_search.py                               ← Combines FAISS vector + BM25 keyword
│   │   ├── query_planner.py                               ← Decides which domains to search
│   │   ├── cross_encoder_reranker.py                      ← Re-ranks results for precision
│   │   ├── weighting.py                                   ← Recency + credibility score boosts
│   │   ├── reranker.py                                    ← Thin reranker wrapper
│   │   ├── empty_results.py                               ← Fallback when results = 0
│   │   └── constants.py                                   ← TOP_K and shared constants
│   │
│   ├── analysis/                                          ← BIAS DETECTION LAYER
│   │   ├── bias_detector.py                               ← Master pipeline: claims→stances→scores
│   │   ├── claim_extractor.py                             ← Pulls core factual claims from article
│   │   ├── stance_detector.py                             ← Evaluates support/contradict per claim
│   │   ├── contradiction_detector.py                      ← Finds conflicting evidence
│   │   ├── narrative_analyzer.py                          ← Lexicon-based narrative bias scan
│   │   ├── summarizer.py                                  ← Summarizes retrieved evidence with LLM
│   │   ├── scorer.py                                      ← Weighted scoring formulas
│   │   ├── scoring_v2.py                                  ← Updated scoring variant
│   │   ├── lexicon.py                                     ← Bias term dictionary + category weights
│   │   └── json_utils.py                                  ← JSON parsing helpers
│   │
│   └── prompts/                                           ← LLM prompt templates
│
├── data/                                                  ← 🟢 UNIVERSAL DATABASE (permanent)
│   ├── web/
│   │   ├── bbc_news.json                                  ← ALL BBC web articles from ALL cycles
│   │   ├── the_guardian.json
│   │   └── ... (one file per web source, grows with every cycle)
│   └── rss/
│       ├── bbc_rss.json                                   ← ALL BBC RSS articles from ALL cycles
│       ├── guardian_rss.json
│       └── ... (one file per rss source, grows with every cycle)
│
├── logs/                                                  ← Log output directory
├── streamlit_app.py                                       ← Frontend UI (Streamlit dashboard)
├── requirements.txt                                       ← Python dependencies
├── README.md
├── SCRAPING_ARCHITECTURE.md                               ← Scraper design reference
├── SCRAPING_TO_FAISS_HANDOFF.md                           ← Handoff design reference
└── pipeline_architecture_overview.md                     ← This document
```

---

## ⚙️ 2. Configuration: `app/input/news_pipeline/config.py`

This is the single source of truth for every path and timing setting.

```python
# Key settings (resolved to absolute paths at runtime)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
# → C:\Users\NAGARJUNA\Desktop\New folder\

output_base_path     = PROJECT_ROOT / "app" / "input" / "data"
# → C:\...\app\input\data\         ← SCRAPER WORKSPACE

output_failed_jsonl  = PROJECT_ROOT / "data" / "failed_articles.jsonl"
metadata_main_path   = PROJECT_ROOT / "data" / "main_metadata.json"
discovery_file_path  = PROJECT_ROOT / "data" / "discovery_sources.json"

cycle_interval_minutes = 120    # Force-terminate scraper after 2 hours
global_workers         = 30     # Max concurrent HTTP requests across all scrapers
per_domain_concurrency = 3      # Max concurrent requests to same domain
```

**39 sources defined** in `SEED_SOURCE_DEFINITIONS` list spanning:

| Category | Sources |
|----------|---------|
| India Web | times_of_india, the_hindu, hindustan_times, india_today, indian_express |
| World Web | bbc_news, reuters, al_jazeera, the_guardian, associated_press |
| Tech Web | techcrunch |
| India RSS | the_hindu_rss, india_today_rss, firstpost_rss, livemint_rss |
| World RSS | bbc_rss, reuters_rss, al_jazeera_rss, guardian_rss, ap_rss, npr_rss |
| Tech RSS | techcrunch_rss, ars_technica_rss, the_verge_rss, wired_rss, engadget_rss |
| AI RSS | mit_ai_rss, ai_news_rss |
| Science RSS | nature_rss, science_daily_rss, space_com_rss |
| Business RSS | cnbc_rss |
| Aggregators RSS | google_news_world, google_news_india, google_news_tech, google_news_science |

---

## 🚀 3. Entry Point: `app/main.py`

Run from the project root OR from inside `app/` — paths are absolute so it works either way.

```bash
# Terminal A — Start the Scraper
python app/main.py  → Select 1

# Terminal B — Start the Index Scanner
python app/main.py  → Select 2
```

**Menu:**
```
1. Start Continuous Scraper Loop           (Terminal A)
   → calls scheduler.start_scraper_only()
   → runs crawler_loop() until Ctrl+C

2. Start Index Scanner (FAISS Builder)      (Terminal B)
   → calls scheduler.start_embedder_only()
   → runs index_worker() polling every 60s until Ctrl+C

3. Run Manual Bias Analyzer Test           (Friend's Setup)
   → calls test_bias_analyzer()
   → feeds article → FAISS retrieval → bias analysis
```

---

## 🕷️ 4. PART 1 — Scraper Loop (Producer)

### `scheduler.py` → `crawler_loop()`

```
CYCLE START
│
├── NewsCrawler(settings).run()
│   ├── Builds aiohttp.ClientSession (shared across all scrapers)
│   ├── Creates one asyncio.Task per source (via ScraperFactory)
│   └── asyncio.gather(*tasks) → all 39 scrapers run concurrently
│
├── [Timer = cycle_interval_minutes × 60 seconds]
│   asyncio.wait_for(..., timeout=...) force-kills all tasks when timer expires
│
└── move_to_index_queue(output_base_path, cycle_number)
    ├── Checks: app/input/data/web/ and app/input/data/rss/ have .json files
    ├── Creates: app/input/data/indexing_queue/cycle_N_YYYYMMDD_HHMMSS/
    ├── shutil.move(web/) → cycle_N/web/
    ├── shutil.move(rss/) → cycle_N/rss/
    └── app/input/data/web/ and rss/ are now EMPTY → scraper restarts fresh
```

### `crawler.py` → `NewsCrawler`

```
NewsCrawler.run()
├── build_sources(discovery_file_path)
│   └── Merges SEED_SOURCE_DEFINITIONS + any dynamic sources from discovery_sources.json
│
├── For each source → ScraperFactory.for_source(source, session, settings, semaphore)
│   ├── source_type == "rss"  → RSSScraper
│   └── source_type == "web"  → WebScraper (BFS)
│
└── asyncio.gather(*tasks, return_exceptions=True)
    └── Each scraper runs independently until its queue is exhausted or timeout hits
```

### `scrapers/base.py` — The Article Schema

Every saved article is a **canonical dict**:

```python
{
    "id":           md5(url).hexdigest(),           # Stable unique ID
    "url":          "https://...",
    "title":        "Article headline",
    "text":         "Full article body",
    "hash":         md5(text).hexdigest(),          # Content fingerprint
    "source":       "bbc_news",                     # Source name slug
    "category":     "world",                        # Category tag
    "published_at": "2026-03-30T22:00:00+00:00",
    "scraped_at":   "2026-03-30T22:05:12+00:00",
    "language":     "en",
    "tags":         ["politics", "economy"],
    "summary":      "Short summary of article"
}
```

**File routing** (via `get_output_path()`):
```
source_type == "rss" → app/input/data/rss/{source_name}.json
source_type == "web" → app/input/data/web/{source_name}.json
```

**In-memory URL dedup** (`known_urls: set[str]`):
- Loaded from JSON at scraper startup
- Updated on every `_save_article()` call
- O(1) lookup — prevents duplicate articles within one cycle

### `extractors.py` — HTML Cleaning

```
Raw HTML (from aiohttp GET)
    → trafilatura.extract()           ← main extraction engine
    → BeautifulSoup fallback          ← if trafilatura fails
    → returns: clean plaintext article body
```

### Web Scraper BFS Loop (`scrapers/web_scraper.py`)

```
Seed URL (e.g. https://www.bbc.com/news)
    → fetch HTML
    → extract all <a href="..."> links
    → filter: same domain, not already known, passes test_classifier
    → push new links to BFS queue (deque)
    → extract article text for current page → save JSON
    → repeat until queue empty or timeout
```

### RSS Scraper (`scrapers/rss_scraper.py`)

```
RSS Feed URL
    → feedparser.parse(url)
    → for each entry in feed.entries:
        → skip if URL in known_urls
        → fetch full article page → extract text
        → build canonical article dict → save JSON
```

---

## 🧠 5. PART 2 — Index Worker (Consumer)

### `scheduler.py` → `index_worker(output_base_path)`

Polls every 60 seconds. Processes cycle folders **oldest-first**.

```
EVERY 60 SECONDS:
│
├── Scan: app/input/data/indexing_queue/ for subdirectories
│
└── For each cycle_N_timestamp/ folder found:
    │
    ├── STEP A: _append_to_master_jsonl(folder, output_base)
    │   └── Reads all .json files in cycle folder (rglob)
    │       Appends each article as one JSON line to:
    │       → app/input/data/new_articles_detailed.jsonl
    │
    ├── STEP B: await process_cycle(folder)        ← build_index.py
    │   └── [See Section 6 below]
    │   └── Returns True (success) or False (failure)
    │
    ├── IF success == False:
    │   └── BREAK — cycle folder kept, retry next tick (60s)
    │
    ├── STEP C: _append_to_universal_db(folder)
    │   └── For each source_type in ("web", "rss"):
    │       For each .json file in cycle_N/{source_type}/:
    │           Load new_articles = json.loads(file)
    │           Load existing = json.loads(data/{source_type}/{file.name})
    │           Deduplicate by URL
    │           Write merged list back to:
    │           → data/web/{source_name}.json      ← UNIVERSAL DB
    │           → data/rss/{source_name}.json      ← UNIVERSAL DB
    │
    └── STEP D: shutil.rmtree(cycle_N_timestamp/)
        └── Cycle folder permanently deleted ✅
```

**Safety:** If Ollama is down or `build_index` throws, `success=False` → `break` → cycle folder untouched → retry in 60 seconds.

---

## 🤖 6. FAISS Pipeline: `app/embeddings/build_index.py`

### `process_cycle(cycle_folder: Path) → bool`

This is the function called by `index_worker` for each cycle.

```
cycle_N_timestamp/
    ├── web/ → collected as source_type "web"
    └── rss/ → collected as source_type "rss"

STEP 1: Discover
─────────────────
source_files = {
    "web": [Path("cycle_N/web/bbc_news.json"), Path("cycle_N/web/the_guardian.json"), ...],
    "rss": [Path("cycle_N/rss/bbc_rss.json"), Path("cycle_N/rss/guardian_rss.json"), ...]
}

STEP 2: Group by Domain  (group_articles_by_domain)
─────────────────────────────────────────────────────
Load all articles from all files.
For each article → _infer_domain_group(source_name, url)
    → urlparse(url).netloc → strip "www." → slugify
    → bbc_news.json (web) + bbc_rss.json (rss) → both → "bbc_com"
    → the_guardian.json + guardian_rss.json    → both → "theguardian_com"

Result:
{
    "bbc_com":          [article1, article2, ...],
    "theguardian_com":  [article1, article2, ...],
    "techcrunch_com":   [article1, ...],
    ...
}

STEP 3: Per domain → chunk → embed → append FAISS
────────────────────────────────────────────────────
For each domain_group, articles:
    │
    ├── build_chunk_metadata(articles)          ← chunker.py
    │       chunk_text(article["content"])
    │       → 140-word windows, 25-word overlap
    │       → chunk_id 0, 1, 2...
    │       → cache_key = SHA1(id||title||url||source||source_type||source_file||domain_group||scraped_at||chunk_id||content)
    │
    ├── build_embeddings_incrementally(chunk_metadata, save_dir)
    │       load_embedding_cache("vector_index/{domain}/")
    │       → loads embeddings.npy + metadata.json
    │       Build cache_lookup: { cache_key: vector }
    │       For each chunk:
    │           if cache_key in cache_lookup → reuse vector (INSTANT, no Ollama)
    │           else                         → queue for Ollama embedding
    │       get_embeddings_batch(new_texts)  ← embed.py → Ollama
    │       Returns: full numpy array of all vectors
    │
    └── append_to_index(embeddings, chunk_metadata, "vector_index/{domain}/")
            ← vector_store.py
            [See Section 7 below]
```

---

## 💾 7. Vector Store: `app/embeddings/vector_store.py`

### Constants (filenames inside each domain folder)
```python
INDEX_FILENAME     = "articles.index"    # Binary FAISS index
METADATA_FILENAME  = "metadata.json"     # Chunk metadata list
EMBEDDINGS_FILENAME = "embeddings.npy"   # numpy cache
```

### `append_to_index(new_embeddings, new_metadata, save_dir)`

```
CASE A: Index already exists
─────────────────────────────
Load existing_index  ← faiss.read_index("articles.index")
Load existing_meta   ← json.loads("metadata.json")
Load existing_emb    ← np.load("embeddings.npy")
Build existing_keys  = { chunk["cache_key"] for chunk in existing_meta }

Filter: new_mask = [i for i, chunk in enumerate(new_metadata) if chunk["cache_key"] NOT in existing_keys]
→ Only truly new chunks get added (dedup by cache_key)

faiss.normalize_L2(filtered_embeddings)   ← normalize for cosine similarity
existing_index.add(filtered_embeddings)   ← APPEND to live FAISS index

merged_metadata  = existing_meta + filtered_metadata
merged_embeddings = np.vstack([existing_emb, filtered_embeddings])

Write back:
→ faiss.write_index(existing_index, "articles.index")
→ metadata.json  ← json.dumps(merged_metadata)
→ embeddings.npy ← np.save(merged_embeddings)

CASE B: No index exists yet (first cycle for this domain)
──────────────────────────────────────────────────────────
faiss.normalize_L2(new_embeddings)
index = faiss.IndexFlatIP(dimension=768)   ← nomic-embed-text dim
index.add(new_embeddings)
Write: articles.index, metadata.json, embeddings.npy
```

### `chunk metadata.json` entry structure (per chunk)

```json
{
    "id":           "3f2a1b...",         ← md5(url) from article
    "title":        "BBC headline",
    "url":          "https://bbc.com/...",
    "content":      "chunk text (140 words)...",
    "chunk_id":     2,                   ← chunk number within article
    "cache_key":    "sha1hex...",        ← dedup fingerprint
    "scraped_at":   "2026-03-30T22:...",
    "source":       "bbc_news",          ← original source slug
    "source_type":  "web",              ← "web" or "rss"
    "source_file":  "bbc_news",         ← JSON filename stem
    "domain_group": "bbc_com"           ← FAISS index folder name
}
```

---

## 🔤 8. Chunk Text: `app/embeddings/chunker.py`

```python
chunk_text(text, chunk_size=140, overlap=25)

# Algorithm:
words = text.split()
step  = 140 - 25 = 115          # slide forward by 115 words each time

Chunk 0: words[0:140]
Chunk 1: words[115:255]
Chunk 2: words[230:370]
...

# Each chunk shares 25 words with the previous → preserves context across boundaries
# Returns: List[str]
```

---

## 🔌 9. Embedding Model: `app/embeddings/embed.py`

```python
MODEL       = OllamaEmbeddings(model="nomic-embed-text")
# Connected to: http://127.0.0.1:11434  (local Ollama server)
# Output dim:   768-dimensional float32 vectors

BATCH_SIZE      = 8        # chunks sent per HTTP request to Ollama
MAX_EMBED_CHARS = 2500     # max characters per chunk (trims if longer)
MIN_EMBED_CHARS = 400      # floor when shrinking to fit context window
```

**`get_embeddings_batch(texts)`** — shown as tqdm progress bar in terminal:
```
Embedding chunks:  77%|████████████| 1272/1639 [03:13<00:47, 7.79batch/s]
```

---

## 🔍 10. Retrieval Pipeline: `app/retrieval/faiss_retriever.py`

Called when bias analysis needs evidence from the vector index.

```
search(query_text, base_dir="app/embeddings/vector_index", top_k=8)
│
├── plan_retrieval(query_text)           ← query_planner.py
│       Uses LLM to decide: which domains, recency filter, diversity requirements
│
├── load_all_indexes(base_dir)           ← index_loader.py  [lru_cache]
│       For each of 21 domain folders:
│           faiss.read_index("articles.index")     → FAISS index
│           json.load("metadata.json")             → chunks list
│           BM25Okapi(corpus)                      → BM25 keyword index
│       Returns: list of { site, index, metadata, bm25 }
│
├── filter_site_indexes(site_indexes, retrieval_plan)
│       Keeps only domains relevant to the query plan
│
├── embed_query(query_text)              ← nomic-embed-text via Ollama
│       Normalizes L2 → cosine-compatible query vector
│
├── search_all_sites_hybrid(site_indexes, query_embedding, query_text)
│       For each domain:
│           FAISS inner product search   → semantic similarity scores
│           BM25 keyword search          → lexical match scores
│           Combine + normalize scores
│
├── apply_recency_weight(results)        ← boosts recent articles
├── apply_credibility_weight(results)    ← boosts trusted sources
├── filter_results(results, plan)        ← removes off-topic results
├── cross_encoder_rerank(query, results) ← precision re-ranking
├── diversify_results(results, top_k)   ← ensures source diversity
└── _filter_irrelevant_results(query, results)
    └── Final keyword-overlap relevance filter
    └── Returns top_k most relevant chunks
```

**Fallback chain:**
```
Ollama available?  → Hybrid (FAISS vector + BM25)
Ollama down?       → BM25-only fallback
BM25 also fails?   → Returns []
```

---

## 🕵️ 11. Bias Analysis: `app/analysis/bias_detector.py`

```
analyze_bias(article_text)
│
├── _validate_input()             → must be ≥ 80 chars
│
├── _retrieve_evidence()          → search() from faiss_retriever
│       Retrieves top-8 most relevant chunks from vector_index
│
├── extract_claims(article)       → claim_extractor.py
│       Pulls up to 3 core factual claims from the article
│
├── For each claim:
│   └── _retrieve_evidence(claim, top_k=2)   ← per-claim evidence
│       detect_claim_stance(claim, evidence)  ← stance_detector.py
│       → "support" / "contradict" / "neutral"
│
├── detect_contradictions(claim_analyses)    ← contradiction_detector.py
├── analyze_narratives(article, evidence)    ← narrative_analyzer.py + BIAS_LEXICON
├── _detect_missing_viewpoints(claim_analyses)
├── _highlight_biased_language(article)      ← lexicon.py term matching
├── _compute_weighted_language_score()
│
└── compute_scores(...)                      ← scorer.py / scoring_v2.py
    Returns final dict with:
    {
        "claims":               [...],
        "claim_analysis":       [...],
        "contradictions":       [...],
        "narrative_analysis":   {...},
        "missing_viewpoints":   {...},
        "scores": {
            "narrative_bias":   0.0-1.0,
            "factual_accuracy": 0.0-1.0,
            "completeness":     0.0-1.0,
            "confidence":       0.0-1.0
        },
        "biased_language":      [...],
        "retrieved_sources":    [...],
        "evidence_coverage":    {...}
    }
```

---

## 🌊 12. Complete End-to-End Data Flow

```
TERMINAL A                                    TERMINAL B
──────────                                    ──────────

python app/main.py → 1                        python app/main.py → 2
        │                                             │
        ▼                                             ▼
crawler_loop()                              index_worker()
        │                                     polls every 60s
        │ [120 min cycle]                             │
        │                                             │
   39 scrapers                                        │
   run concurrently                                   │
        │                                             │
        │ Writes JSON articles to:                    │
        │ app/input/data/web/*.json                   │
        │ app/input/data/rss/*.json                   │
        │                                             │
        │ [120 min timeout]                           │
        │                                             │
        ▼                                             │
move_to_index_queue()                                 │
        │                                             │
        │ Creates:                                    │
        │ app/input/data/indexing_queue/              │
        │   cycle_N_20260330_221500/                  │
        │     web/ ← moved                           │
        │     rss/ ← moved                           │
        │                                             │
        │ Scraper restarts immediately                │
        │                                             │
        │◄──── cycle folder detected ────────────────►│
                                                      │
                                             STEP A: _append_to_master_jsonl
                                                      │
                                                      ▼
                                             app/input/data/
                                               new_articles_detailed.jsonl
                                                      │
                                             STEP B: process_cycle(folder)
                                                      │
                                                      ▼
                                             build_index.py
                                               group_articles_by_domain()
                                               build_chunk_metadata()
                                               build_embeddings_incrementally()
                                                 → CACHE HIT: reuse .npy
                                                 → NEW CHUNKS: Ollama HTTP
                                               append_to_index()
                                                      │
                                                      ▼
                                             app/embeddings/vector_index/
                                               bbc_com/articles.index  ← updated
                                               bbc_com/metadata.json   ← appended
                                               bbc_com/embeddings.npy  ← appended
                                               (+ 20 other domains)
                                                      │
                                             STEP C: _append_to_universal_db()
                                                      │
                                                      ▼
                                             data/web/bbc_news.json    ← appended
                                             data/web/the_guardian.json← appended
                                             data/rss/bbc_rss.json     ← appended
                                             (deduplicated by URL)
                                                      │
                                             STEP D: shutil.rmtree(cycle_N/)
                                                      │
                                                      ▼
                                             ✅ Cycle complete. Back to sleep (60s).
```

---

## 🛡️ 13. Safety & Failsafes

| Risk | Protection |
|------|-----------|
| Ollama down during embedding | `try/except ImportError` + `success=False` → cycle folder kept → retried in 60s |
| Duplicate chunks across cycles | `cache_key` SHA1 in `build_embeddings_incrementally` + `append_to_index` |
| Duplicate articles in universal DB | URL-based dedup in `_append_to_universal_db()` |
| Scraper writes to wrong path | All paths built via `Path(__file__).resolve().parents[N]` — absolute, not relative |
| Domain FAISS not yet created | `append_to_index` creates fresh index if no existing `.index` file found |
| FAISS index type mismatch | `index_loader.ensure_cosine_index()` rebuilds as `IndexFlatIP` if needed |
| Article too short to embed | `MIN_EMBED_CHARS = 400` in embed.py + chunker returns `[]` for empty text |
| Ollama context overflow | Progressive shrink loop: reduces to 70% until it fits |
| Scraper crash mid-cycle | `asyncio.gather(return_exceptions=True)` — one crashed scraper doesn't stop others |
| Discovery file missing | `load_discovery_sources()` returns `[]` gracefully — still runs seed sources |

---

## 📊 14. Data Volume Reference

| Stage | Data Volume |
|-------|------------|
| One cycle (120 min) | ~10-50 MB of JSON per source |
| FAISS dimension | 768 (nomic-embed-text) |
| Chunk size | 140 words (~1000 chars) |
| Chunk overlap | 25 words |
| Batch size (Ollama) | 8 chunks per HTTP request |
| bbc_com vector index | ~1,130 vectors (grows each cycle) |
| Total domain indexes | 21 |
| Cycle cleanup | Cycles deleted after successful processing |
