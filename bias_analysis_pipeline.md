# Bias Analysis Pipeline — Architecture & Explanation

## Overview
This project implements a multi-stage AI pipeline to analyze bias in news articles.

---

## 1. System Architecture (Class Diagram)

```mermaid
classDiagram
    class ScraperFactory {
        +for_source(source, session, settings)
    }

    class BaseScraper
    class RSSScraper
    class WebScraper

    BaseScraper <|-- RSSScraper
    BaseScraper <|-- WebScraper
    ScraperFactory --> BaseScraper

    class FetchTask
    class ArticleTask
    class DiscoveryTask
    class DetailedArticleRecord

    class MetadataGate {
        +load()
        +exists(url)
    }

    class Embedding {
        +get_embedding(text)
        +get_embeddings_batch(texts)
    }

    class Chunker {
        +chunk_text(text)
    }

    class VectorStore {
        +build_index()
        +load_index()
    }

    class Retriever {
        +search()
        +retrieve_similar_chunks()
    }

    class Reranker {
        +rerank_results()
    }

    class CrossEncoderReranker {
        +cross_encoder_rerank()
    }

    class ClaimExtractor {
        +extract_claims()
    }

    class StanceDetector {
        +detect_claim_stance()
    }

    class ContradictionDetector {
        +detect_contradictions()
    }

    class NarrativeAnalyzer {
        +analyze_narrative()
    }

    class Scoring {
        +compute_scores()
    }

    class BiasDetector {
        +analyze_bias()
    }

    Chunker --> Embedding
    Embedding --> VectorStore
    Retriever --> VectorStore
    Retriever --> Reranker
    Retriever --> CrossEncoderReranker

    BiasDetector --> ClaimExtractor
    BiasDetector --> Retriever
    BiasDetector --> StanceDetector
    BiasDetector --> ContradictionDetector
    BiasDetector --> NarrativeAnalyzer
    BiasDetector --> Scoring
```

---

## 2. Pipeline Flow

```mermaid
flowchart TD
    A[Input Text] --> B[Claim Extraction]
    B --> C[Evidence Retrieval]
    C --> D[Stance Detection]
    D --> E[Contradiction Detection]
    E --> F[Narrative Analysis]
    F --> G[Scoring Engine]
    G --> H[Final Bias Output]
```

---

## 3. Retrieval System

```mermaid
flowchart LR
    Q[Query Claim] --> E[Embedding]
    E --> F[FAISS Search]

    Q --> B[BM25 Search]

    F --> C[Combine Results]
    B --> C

    C --> D[Reranking]
```

---

## 4. Contradiction Detection

```mermaid
flowchart TD
    A[All Evidence] --> B[Group by Source]
    B --> C[Detect SUPPORT]
    B --> D[Detect CONTRADICT]

    C --> E{Both present?}
    D --> E

    E -->|Yes| F[Mark Contradiction]
    E -->|No| G[No contradiction]
```

---

## 5. Narrative Analysis

```mermaid
flowchart TD
    A[Text] --> B[Tokenize]
    B --> C[Match Lexicon]
    C --> D[Assign Category]
    D --> E[Score Bias]
```

---

## 6. Scoring System

```mermaid
flowchart TD
    A[Factual Accuracy] --> F[Final Score]
    B[Narrative Bias] --> F
    C[Completeness] --> F
    D[Confidence] --> F
```

---

## 7. Execution Flow

```mermaid
sequenceDiagram
    participant U as User
    participant A as Analyzer
    participant R as Retriever
    participant S as Scorer

    U->>A: Input Article
    A->>A: Extract Claims
    A->>R: Retrieve Evidence
    R-->>A: Results
    A->>A: Detect Stance
    A->>A: Detect Contradictions
    A->>A: Narrative Analysis
    A->>S: Compute Scores
    S-->>A: Scores
    A-->>U: Bias Report
```

---

## Summary

This pipeline integrates NLP, retrieval systems, and reasoning to detect bias in articles.
