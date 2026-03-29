# 🧠 Evidence-Based News Bias Analyzer

An end-to-end **local-first AI system** for analyzing news articles using multi-source retrieval, structured reasoning, and explainable scoring.

---

# 🚀 Overview

This project combines:

* 🔍 Hybrid retrieval (FAISS + BM25 + reranking)
* 🧾 Claim-level verification
* ⚖️ Stance + contradiction detection
* 🧠 Narrative & framing analysis
* 📊 Calibrated scoring system
* 🌐 Continuous scraping + indexing pipeline
* 🖥️ Streamlit UI + PDF reports

---

# 🏗️ System Architecture

## 🔁 End-to-End Analysis Flow

```mermaid
graph TD
    A[User Input / URL / PDF]
    B[Text Extraction]
    C[Query Planning]
    D[Hybrid Retrieval]
    E[Evidence Processing]
    F[Claim Extraction]
    G[Stance Detection]
    H[Contradiction Detection]
    I[Narrative Analysis]
    J[Scoring Engine]
    K[UI + PDF Report]

    A --> B --> C --> D --> E
    E --> F --> G --> H
    H --> I --> J --> K
```

---

## ⚙️ Scraper → FAISS Handoff (Producer–Consumer)

```mermaid
graph TD
    A[Scraper Loop \n Producer] -->|Downloads Articles| B[data/web & data/rss]
    B -->|Moves every 5 hrs| C{data/indexing_queue}
    C -->|Worker polls every 60s| D[Index Worker \n Consumer]
    D -->|Aggregates JSON| E[data/new_articles_detailed.jsonl]
    E -->|Triggers| F[build_index_pipeline]
    F -->|Embeddings| G[FAISS Vector DB]
    F -->|On Success| H(Delete cycle folder)
```

---

# 📂 Project Structure

```text
.
+-- streamlit_app.py
+-- README.md
+-- requirements.txt
+-- SCRAPING_TO_FAISS_HANDOFF.md
+-- app/
|   +-- main.py
|   +-- analysis/
|   +-- embeddings/
|   +-- evaluation/
|   +-- input/
|   +-- prompts/
|   +-- retrieval/
+-- data/
+-- logs/
```

---

# 🧩 Core Modules

## 🧠 Analysis (`app/analysis/`)

Core reasoning layer:

* bias detection
* claim extraction
* stance detection
* contradiction detection
* narrative analysis
* scoring (raw + calibrated)
* summarization

Pipeline:

```text
Article → Claims → Evidence → Stance → Contradictions → Narrative → Scores
```

---

## 🔍 Retrieval (`app/retrieval/`)

Hybrid retrieval system:

* FAISS semantic search
* BM25 lexical fallback
* hybrid fusion
* reranking (cross-encoder)
* credibility weighting
* recency weighting
* filtering + diversification

Flow:

```text
Query → FAISS + BM25 → Merge → Filter → Rerank → Results
```

### Safeguards

* corrupted index handling
* embedding failure fallback
* reranker fallback
* BM25-only fallback

---

## 📦 Embeddings (`app/embeddings/`)

Vector pipeline:

```text
Articles → Chunking → Embeddings → FAISS Indexes
```

Features:

* incremental indexing
* embedding caching
* per-site indexes
* batching + backoff handling

---

## 🌐 Input Pipeline (`app/input/`)

Scraping system:

* RSS scraping
* web scraping (BFS discovery)
* async crawling
* deduplication (metadata gate)
* scheduler-driven cycles

### Scraper Cycle Design

* runs in timed cycles (default: 5 hours)
* moves results to indexing queue
* restarts immediately

---

## 📊 Evaluation (`app/evaluation/`)

Supports:

* dataset loading
* bias label evaluation
* stance evaluation
* aggregate metrics

---

# 🔬 Detailed Analysis Pipeline

```text
Input Article
  → Retrieval Planning
  → Hybrid Retrieval (FAISS + BM25)
  → Credibility / Recency Weighting
  → Reranking
  → Claim Extraction
  → Claim-Level Retrieval
  → Stance Detection
  → Contradiction Detection
  → Narrative Analysis
  → Loaded Language Detection
  → Evidence Summarization
  → Top-Level Scores
  → Calibrated Scores
```

---

# 📊 Scoring System

## Top-Level Metrics

* factual accuracy
* narrative bias
* completeness
* confidence

## Calibrated Metrics

* credibility score
* bias score
* completeness score
* confidence

Component signals:

* factual_accuracy
* narrative_bias
* loaded_language
* evidence_support
* source_reliability
* viewpoint_coverage
* context_depth

---

# 🧾 Loaded Language Analysis

Categories:

* alarmist
* certainty_overclaim
* conflict_escalation
* moral_judgment
* propaganda_framing
* derision_ridicule

UI includes:

* category distribution charts
* highlighted sentences
* word grouping

---

# 🤖 Models Used (Ollama)

| Task               | Model            |
| ------------------ | ---------------- |
| Embeddings         | nomic-embed-text |
| Narrative analysis | qwen2.5:7b       |
| Scoring            | phi3:mini        |
| Summarization      | gemma2:9b        |

---

# 🧪 Test Article Generation

Test articles used for evaluation are **generated using a local LLM**.

### ⚙️ Model Used

* llama2-uncensored:7b

### 🎯 Purpose

These generated articles are used strictly for **evaluation and testing**, not for training or production inference.

They help:

* benchmark bias detection accuracy
* test stance and contradiction detection
* validate scoring calibration
* simulate controlled edge cases

### 🧾 Types of Generated Articles

The evaluation setup includes:

* balanced articles
* biased / one-sided articles
* emotionally loaded articles
* misleading or framed narratives
* factually incorrect articles
* contradictory articles
* weak evidence articles

### 🔍 Why This Matters

Using generated data allows:

* controlled and reproducible testing
* targeted evaluation of specific failure cases
* consistent benchmarking without relying on noisy real-world datasets

### 🔗 Integration

Generated articles are passed into:

```text
Evaluation → Analysis Pipeline → Metrics
```

This ensures the system can be tested systematically across different bias and reasoning scenarios.

---

---

# 🖥️ Running the Project

## Setup

```bash
pip install -r requirements.txt
```

## Run UI

```bash
streamlit run streamlit_app.py
```

## CLI Mode

```bash
python app/main.py
```

Options:

```text
1 → continuous scraper + indexing
2 → manual analyzer
```

---

# 🔁 Scraping & Indexing

## Scraper

```bash
python -m app.input.scraper
```

Features:

* RSS + web scraping
* BFS discovery
* deduplication
* queue-based indexing handoff

## Index Builder

Located at:

```text
app/embeddings/build_index.py
```

Responsibilities:

* load JSON/JSONL data
* filter valid articles
* chunk text
* reuse embeddings
* build FAISS indexes

---

# 📄 PDF Reporting

Generated via Streamlit + PyMuPDF.

Includes:

* summary
* calibrated scores
* evidence context
* claim verification
* contradictions
* narrative analysis
* source comparison
* loaded language

---

# ⚠️ Limitations

* heuristic claim extraction
* model latency varies by hardware
* retrieval noise in edge cases
* scoring still evolving

---

# 💡 Strengths

### 🧵 Multi-Scraper Architecture

* concurrent async scraping across multiple sources
* supports both RSS and full web crawling
* BFS-style discovery for deeper coverage
* per-source configuration and scaling

### 🧠 Multi-Index FAISS Architecture

* separate FAISS index per publisher/domain
* avoids single-index bottlenecks
* improves retrieval diversity
* enables source-level weighting and filtering

### 🔀 Hybrid Retrieval System

* FAISS (semantic) + BM25 (lexical)
* fusion of results across multiple sources
* fallback-safe design (works even if embeddings fail)

### ⚖️ Advanced Ranking & Weighting

* cross-encoder reranking
* credibility-based weighting per source
* recency-based scoring adjustments
* adaptive thresholds per site

### 🔄 Continuous Data Pipeline

* producer-consumer architecture
* scraper and indexing fully decoupled
* automatic FAISS updates
* zero blocking between ingestion and ML pipeline

### 🛡️ Fault Tolerance

* safe fallbacks for embedding failures
* reranker failure recovery
* corrupted index handling
* retry-safe indexing queue

### 🧪 Evaluation-Ready System

* synthetic test article generation
* structured dataset evaluation
* reproducible benchmarking

### 🧩 Modular Design

* clean separation of concerns

* independently testable modules

* scalable architecture

* local-first (privacy friendly)

* explainable outputs

* modular architecture

* fault-tolerant pipeline

* production-style ingestion + indexing

---

# 🛣️ Future Work

* improved claim extraction
* stronger contradiction reasoning
* distributed indexing
* real-time ingestion
* advanced evaluation benchmarks

---
