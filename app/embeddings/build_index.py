"""Standalone builder for article embeddings and the FAISS index."""

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


def _normalize_article(record: dict[str, Any]) -> dict[str, str] | None:
    """Normalize raw article data into the metadata shape used by the index."""
    content = str(record.get("content") or record.get("text") or "").strip()
    if not content:
        return None

    article_id = str(record.get("id") or record.get("article_id") or "").strip()
    title = str(record.get("title") or "").strip()
    source_url = str(record.get("source_url") or record.get("url") or "").strip()
    return {
        "id": article_id,
        "title": title,
        "source_url": source_url,
        "content": content,
    }


async def _load_articles_from_db(dsn: str) -> list[dict[str, str]]:
    """Load articles from PostgreSQL using the existing shared pool factory."""
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
        normalized = _normalize_article(dict(row))
        if normalized:
            articles.append(normalized)
    return articles


def _iter_json_records(path: Path) -> list[dict[str, Any]]:
    """Read JSON or JSONL article records from a file or directory path."""
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
    """Load articles from a configurable JSON or JSONL fallback path."""
    articles: list[dict[str, str]] = []
    for record in _iter_json_records(input_path):
        normalized = _normalize_article(record)
        if normalized:
            articles.append(normalized)
    return articles


async def load_articles() -> list[dict[str, str]]:
    """Load articles from PostgreSQL when available, otherwise from local files."""
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
    """Load articles, generate embeddings, and save the FAISS index."""
    articles = await load_articles()
    print(f"Loaded {len(articles)} articles")
    if not articles:
        raise ValueError("No articles found for embedding.")

    contents = [article["content"] for article in articles]
    print("Generating embeddings...")
    embeddings = get_embeddings_batch(contents)

    print("Building FAISS index...")
    index = build_faiss_index(embeddings)
    save_index(index=index, metadata=articles, save_dir=str(DEFAULT_SAVE_DIR))
    print("Index saved to app/embeddings/vector_index/")


if __name__ == "__main__":
    asyncio.run(build_index_pipeline())
