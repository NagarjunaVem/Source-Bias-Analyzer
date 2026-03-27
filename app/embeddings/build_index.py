from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from app.embeddings.chunker import chunk_text
from app.embeddings.vector_store import build_faiss_index, load_embedding_cache, save_index

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "new_articles_detailed.jsonl"
FALLBACK_INPUT_PATH = PROJECT_ROOT / "data" / "articles.jsonl"
SAVE_DIR = PROJECT_ROOT / "app" / "embeddings" / "vector_index"


def _resolve_input_path() -> Path:
    """Pick the best available article input file."""
    if DEFAULT_INPUT_PATH.exists():
        return DEFAULT_INPUT_PATH
    return FALLBACK_INPUT_PATH


def load_articles() -> list[dict[str, str]]:
    """Load article records from JSONL."""
    input_path = _resolve_input_path()
    if not input_path.exists():
        print(f"File not found: {input_path}")
        return []

    articles: list[dict[str, str]] = []
    with input_path.open("r", encoding="utf-8") as file_handle:
        for line in file_handle:
            if not line.strip():
                continue

            record = json.loads(line)
            content = str(record.get("content") or record.get("text") or "").strip()
            if not content:
                continue

            articles.append(
                {
                    "id": record.get("id", ""),
                    "title": record.get("title", ""),
                    "url": record.get("url", ""),
                    "source": record.get("source", ""),
                    "scraped_at": record.get("scraped_at", ""),
                    "content": content,
                }
            )

    return articles


def _build_cache_key(article: dict[str, str], chunk_id: int, content: str) -> str:
    """Create a stable key so unchanged chunks can reuse cached embeddings."""
    raw_value = "||".join(
        [
            article["id"],
            article["title"],
            article["url"],
            article["source"],
            article["scraped_at"],
            str(chunk_id),
            content,
        ]
    )
    return hashlib.sha1(raw_value.encode("utf-8")).hexdigest()


def build_chunk_metadata(articles: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Split articles into chunk metadata records."""
    chunk_metadata: list[dict[str, Any]] = []

    for article in articles:
        chunks = chunk_text(article["content"])
        for chunk_id, chunk in enumerate(chunks):
            chunk_metadata.append(
                {
                    "id": article["id"],
                    "title": article["title"],
                    "url": article["url"],
                    "content": chunk,
                    "chunk_id": chunk_id,
                    "cache_key": _build_cache_key(article, chunk_id, chunk),
                    "scraped_at": article["scraped_at"],
                    "source": article["source"],
                }
            )

    return chunk_metadata


def build_embeddings_incrementally(chunk_metadata: list[dict[str, Any]]) -> np.ndarray:
    """Reuse cached embeddings for unchanged chunks and compute only new ones."""
    from app.embeddings.embed import get_embeddings_batch

    cached_embeddings, cached_metadata = load_embedding_cache(str(SAVE_DIR))
    cache_lookup: dict[str, np.ndarray] = {}

    if len(cached_embeddings) == len(cached_metadata):
        for index, metadata in enumerate(cached_metadata):
            cache_key = str(metadata.get("cache_key", ""))
            if cache_key:
                cache_lookup[cache_key] = np.asarray(cached_embeddings[index], dtype=np.float32)

    embeddings_in_order: list[np.ndarray | None] = [None] * len(chunk_metadata)
    new_texts: list[str] = []
    new_positions: list[int] = []
    reused_count = 0

    for index, metadata in enumerate(chunk_metadata):
        cached_vector = cache_lookup.get(str(metadata["cache_key"]))
        if cached_vector is not None:
            embeddings_in_order[index] = cached_vector
            reused_count += 1
            continue

        new_texts.append(str(metadata["content"]))
        new_positions.append(index)

    print(f"Reused {reused_count} cached embeddings")
    print(f"Generating {len(new_texts)} new embeddings")

    if new_texts:
        new_embeddings = get_embeddings_batch(new_texts)
        for position, embedding in zip(new_positions, new_embeddings):
            embeddings_in_order[position] = np.asarray(embedding, dtype=np.float32)

    if not embeddings_in_order:
        return np.empty((0, 0), dtype=np.float32)

    return np.vstack([embedding for embedding in embeddings_in_order if embedding is not None]).astype(np.float32)


async def build_index_pipeline() -> np.ndarray:
    """Build the FAISS index and return embeddings as a numpy array."""
    articles = load_articles()
    print(f"Loaded {len(articles)} articles")
    if not articles:
        print("No articles found. Run crawler first.")
        return np.empty((0, 0), dtype=np.float32)

    chunk_metadata = build_chunk_metadata(articles)
    print(f"Total chunks created: {len(chunk_metadata)}")
    if not chunk_metadata:
        print("No chunks created from the input articles.")
        return np.empty((0, 0), dtype=np.float32)

    embeddings = build_embeddings_incrementally(chunk_metadata)
    print("Building FAISS index...")
    index = build_faiss_index(embeddings)

    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    save_index(
        index=index,
        metadata=chunk_metadata,
        save_dir=str(SAVE_DIR),
        embeddings=embeddings,
    )
    print("Index saved to:", SAVE_DIR)
    print("Embeddings numpy shape:", embeddings.shape)
    return embeddings


if __name__ == "__main__":
    asyncio.run(build_index_pipeline())
