"""Simple script to build the Stage 3 FAISS index."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.connection import get_pool
from app.embeddings.embed import get_embeddings_batch
from app.embeddings.vector_store import build_faiss_index, save_index

DEFAULT_FALLBACK_INPUT_PATH = PROJECT_ROOT / "data" / "new_articles_detailed.jsonl"
DEFAULT_SAVE_DIR = PROJECT_ROOT / "app" / "embeddings" / "vector_index"
DEFAULT_CHUNK_SIZE = 180
DEFAULT_CHUNK_OVERLAP = 30


async def _load_articles_from_db(dsn: str) -> list[dict[str, str]]:
    """Load articles from PostgreSQL."""
    pool = await get_pool(dsn)
    try:
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT id, title, url AS source_url, content
                FROM articles
                WHERE NULLIF(TRIM(content), '') IS NOT NULL
                ORDER BY created_at DESC
                """
            )
    finally:
        await pool.close()

    articles: list[dict[str, str]] = []
    for row in rows:
        content = str(row["content"] or "").strip()
        if not content:
            continue
        articles.append(
            {
                "id": str(row["id"] or "").strip(),
                "title": str(row["title"] or "").strip(),
                "source_url": str(row["source_url"] or "").strip(),
                "content": content,
            }
        )
    return articles


def _load_json_records(path: Path) -> list[dict[str, Any]]:
    """Load raw article records from a JSON or JSONL path."""
    if not path.exists():
        return []

    files: list[Path]
    if path.is_dir():
        files = sorted(
            [
                *path.rglob("*.json"),
                *path.rglob("*.jsonl"),
            ]
        )
    else:
        files = [path]

    records: list[dict[str, Any]] = []
    for file_path in files:
        if file_path.suffix == ".jsonl":
            for line in file_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if isinstance(row, dict):
                    records.append(row)
            continue

        payload = json.loads(file_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            records.extend(item for item in payload if isinstance(item, dict))
        elif isinstance(payload, dict):
            if isinstance(payload.get("articles"), list):
                records.extend(item for item in payload["articles"] if isinstance(item, dict))
            else:
                records.append(payload)
    return records


def _load_articles_from_fallback(input_path: Path) -> list[dict[str, str]]:
    """Load articles from JSON or JSONL files."""
    articles: list[dict[str, str]] = []
    for record in _load_json_records(input_path):
        content = str(record.get("content") or record.get("text") or "").strip()
        if not content:
            continue
        articles.append(
            {
                "id": str(record.get("id") or record.get("article_id") or "").strip(),
                "title": str(record.get("title") or "").strip(),
                "source_url": str(record.get("source_url") or record.get("url") or "").strip(),
                "content": content,
            }
        )
    return articles


def split_text_into_chunks(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Split text into overlapping word chunks."""
    words = text.split()
    if not words:
        return []

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0.")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap cannot be negative.")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size.")

    chunks: list[str] = []
    start = 0
    step = chunk_size - chunk_overlap

    while start < len(words):
        chunk_words = words[start : start + chunk_size]
        if not chunk_words:
            break
        chunks.append(" ".join(chunk_words))
        start += step

    return chunks


def chunk_articles(articles: list[dict[str, str]]) -> list[dict[str, str | int]]:
    """Convert article records into chunk records for embedding."""
    chunk_size = int(os.getenv("EMBEDDINGS_CHUNK_SIZE", str(DEFAULT_CHUNK_SIZE)))
    chunk_overlap = int(os.getenv("EMBEDDINGS_CHUNK_OVERLAP", str(DEFAULT_CHUNK_OVERLAP)))

    chunked_articles: list[dict[str, str | int]] = []
    for article in articles:
        chunks = split_text_into_chunks(
            article["content"],
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        for chunk_index, chunk_text in enumerate(chunks):
            article_id = article["id"] or "article"
            chunked_articles.append(
                {
                    "id": f"{article_id}_chunk_{chunk_index}",
                    "article_id": article["id"],
                    "chunk_index": chunk_index,
                    "title": article["title"],
                    "source_url": article["source_url"],
                    "content": chunk_text,
                }
            )

    return chunked_articles


async def load_articles() -> list[dict[str, str]]:
    """Load articles from the database, or fall back to local files."""
    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN") or os.getenv("NEWS_DB_DSN")
    fallback_path = Path(os.getenv("EMBEDDINGS_INPUT_PATH", str(DEFAULT_FALLBACK_INPUT_PATH)))
    if not fallback_path.is_absolute():
        fallback_path = PROJECT_ROOT / fallback_path

    if dsn:
        try:
            return await _load_articles_from_db(dsn)
        except Exception as error:
            print(f"Database load failed, falling back to files: {error}")

    return _load_articles_from_fallback(fallback_path)


async def build_index_pipeline() -> None:
    """Build and save the FAISS index for articles."""
    articles = await load_articles()
    print(f"Loaded {len(articles)} articles")
    if not articles:
        raise ValueError("No articles found for embedding.")

    chunked_articles = chunk_articles(articles)
    print(f"Created {len(chunked_articles)} chunks")
    if not chunked_articles:
        raise ValueError("No chunks found for embedding.")

    contents = [str(article["content"]) for article in chunked_articles]
    print("Generating embeddings...")
    embeddings = get_embeddings_batch(contents)

    print("Building FAISS index...")
    index = build_faiss_index(embeddings)
    save_index(index=index, metadata=chunked_articles, save_dir=str(DEFAULT_SAVE_DIR))
    print("Index saved to app/embeddings/vector_index/")


if __name__ == "__main__":
    asyncio.run(build_index_pipeline())
