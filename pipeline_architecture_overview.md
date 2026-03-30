# 🏗️ Source-Bias-Analyzer: Architecture & Automated Pipeline Guide

This document maps out the end-to-end structure of the automated **Scraping ➜ FAISS Embedding ➜ Universal Database** pipeline. 

---

## 📁 1. Project Directory Structure

Your project maintains a clear separation between **code (`app/`)** and **permanent data (`data/`)**. Intermediate or "work-in-progress" data is kept safely tucked away inside `app/input/data/`.

```text
Source-Bias-Analyzer/
│
├── app/                                 # 🧠 All Executable Code
│   ├── main.py                          # 🚀 Main Entry Point (Terminal A & B launcher)
│   │
│   ├── input/
│   │   ├── news_pipeline/               # 🕷️ Scraper & Scheduler Code
│   │   │   ├── crawler.py               # Asynchronous crawler execution
│   │   │   ├── config.py                # Pipeline paths and timeout settings
│   │   │   ├── scheduler.py             # ⚙️ The Core Automation loops (Producer & Consumer)
│   │   │   └── scrapers/                # Web & RSS source extractors
│   │   │
│   │   └── data/                        # 🟡 TEMPORARY WORKSPACE (Scraper's current cycle)
│   │       ├── web/                     # Live scraped web JSONs
│   │       ├── rss/                     # Live scraped RSS JSONs
│   │       └── indexing_queue/          # Staging area for completed cycles waiting for embeddings
│   │           └── cycle_N_timestamp/   
│   │
│   ├── embeddings/                      # 🤖 AI & Vector Engine Code
│   │   ├── build_index.py               # Chunking & FAISS Index Orchestrator
│   │   ├── vector_store.py              # Handles saving and ADDING to .npy and .index files
│   │   └── vector_index/                # 🔵 PERMANENT FAISS DATABASES
│   │       ├── bbc_com/                 
│   │       │   ├── articles.index       # Binary FAISS format
│   │       │   ├── embeddings.npy       # Raw numpy cache for dedup
│   │       │   └── metadata.json        # Chunk ID, source, url text data
│   │       └── ndtv_com/ ...
│   │
│   └── analysis/                        # 🕵️ Bias Detection Logic (Friend's Setup)
│
└── data/                                # 🟢 PERMANENT UNIVERSAL DATABASE
    ├── web/                             # Huge, ever-growing JSON logs from all cycles
    │   ├── bbc_news.json
    │   └── ndtv.json
    ├── rss/                             # Huge, ever-growing JSON logs from all cycles
    │   ├── bbc_rss.json
    │   └── ndtv_rss.json
    └── new_articles_detailed.jsonl      # Unified flat file of all scraped data
```

---

## ⚙️ 2. The Core Pipeline: Pin-to-Pin Breakdown

The entire system is a **Producer-Consumer architecture** driven by two continuous loops. They run concurrently but safely isolated from each other.

### 🎭 Actor 1: The Scraper Loop (Producer)
Runs continuously in **Terminal A**. Its job is strictly to fetch articles and bundle them into neat drops format.

1. **Cycle Start:** 39 simultaneous web and RSS scrapers spin up.
2. **Writing Data:** They continuously append JSON articles sequentially to `app/input/data/web/` and `app/input/data/rss/`. 
3. **Timer Expiration:** After the configured limit *(e.g. 120 minutes)*, the loop gracefully force-terminates the async spider tasks.
4. **Handoff (`move_to_index_queue`):** All active `web/` and `rss/` folders are bundled together into a timestamped directory (e.g. `cycle_3_202611...`) under `app/input/data/indexing_queue/`. 
5. **Restart:** The workspace is naturally refreshed/emptied, and the scraper immediately starts the next 120-minute cycle.

### 🕵️ Actor 2: The Index Scanner (Consumer)
Runs continuously in **Terminal B**. It sleeps and checks the `indexing_queue` every 60 seconds. When it spots a newly dropped cycle folder, it kicks off a 4-step processing event:

#### Step A: Consolidate
* It opens all JSONs in the cycle folder.
* Converts them into a single, massive JSONL (Line-delimited JSON) called `new_articles_detailed.jsonl` at the root folder for bulk reference.

#### Step B: AI Chunking & FAISS Appending (`build_index_pipeline`)
* The cycle folder is passed to `build_index.py`.
* **Grouping:** It combines identical sources (e.g., `bbc_news.json` and `bbc_rss.json`) into unified publisher buckets (`bbc_com`).
* **Chunking:** Text is sliced into overlapping ~140-word segments. A unique `cache_key` SHA1 hash is built for each chunk.
* **Deduping Check:** It peaks into `app/embeddings/vector_index/{domain}/embeddings.npy` to see if that `cache_key` already exists. 
* **Ollama Embedding:** Only *brand-new* chunks are passed to the `nomic-embed-text` local model via HTTP request.
* **Appending (`append_to_index`):** The new AI Vectors are added (`index.add()`) to the established FAISS Binary, completely protecting prior historical contexts.

#### Step C: The Universal Archive 
* If FAISS processes safely without crashing, the raw cycle data is committed to the **Universal Database**.
* The cycle's JSON files are safely extracted, URL deduplicated against existing historical data, and appended directly to `data/web/*` and `data/rss/*` arrays.

#### Step D: Deletion & Cleanup
* Now that contexts are merged seamlessly into AI FAISS memory & permanent Root Data storage, the massive temporary `cycle` staging folder inside `app/input/data/indexing_queue/` is deleted via `shutil.rmtree()`.
* **Result:** No massive wasted disk space.

---

## 🛠️ 3. Safety Highlights & Failsafes

* **Ollama Crash Resistance:** If the local AI embedding model (`127.0.0.1:11434`) shuts down or fails while processing Step B, the script explicitly aborts the chain. `Step C` and `Step D` are ignored. The folder remains untouched in the queue and the Index Scanner will simply try again 60 seconds later.
* **Absolute Pathing:** Even if `main.py` is called from inside nested directories, absolute `__file__` system resolution ensures `data/` goes to the top-level root project, preventing misaligned recursive folders.
* **Duplicate URL Check:** `config.py` uses persistent tracking limits and `_append_to_universal_db()` explicitly checks previously saved URLs to avoid duplicates building up inside the root Universal Data storage JSONs over time.
