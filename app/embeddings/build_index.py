from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np

from app.embeddings.chunker import chunk_text
from app.embeddings.vector_store import build_faiss_index, load_embedding_cache, save_index

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_ROOT = PROJECT_ROOT / "app" / "input" / "data"
SAVE_ROOT = PROJECT_ROOT / "app" / "embeddings" / "vector_index"


def _load_records_from_file(file_path: Path) -> list[dict[str, Any]]:
    """Load records from a JSON or JSONL file."""
    if file_path.suffix == ".jsonl":
        records: list[dict[str, Any]] = []
        with file_path.open("r", encoding="utf-8") as file_handle:
            for line in file_handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                if isinstance(record, dict):
                    records.append(record)
        return records

    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("articles"), list):
            return [item for item in payload["articles"] if isinstance(item, dict)]
        return [payload]
    return []


def discover_source_files() -> dict[str, list[Path]]:
    """Discover source-type folders such as rss and web under app/input/data."""
    if not INPUT_ROOT.exists():
        print(f"Input folder not found: {INPUT_ROOT}")
        return {}

    source_files: dict[str, list[Path]] = {}
    for source_dir in sorted(path for path in INPUT_ROOT.iterdir() if path.is_dir()):
        files = sorted(
            [
                *source_dir.glob("*.json"),
                *source_dir.glob("*.jsonl"),
            ]
        )
        if files:
            source_files[source_dir.name] = files
    return source_files


def _slugify_name(value: str) -> str:
    """Convert a publisher/domain label into a safe folder name."""
    slug = value.strip().lower().replace("-", "_").replace(".", "_").replace(" ", "_")
    return slug or "unknown_domain"


def _domain_from_url(url: str) -> str:
    """Extract a normalized domain from a URL."""
    parsed = urlparse(url)
    host = parsed.netloc.lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host


def _infer_domain_group(source_name: str, url: str) -> str:
    """Map RSS and web files from the same publisher into one domain group."""
    host = _domain_from_url(url)
    if host:
        return _slugify_name(host)

    cleaned_name = source_name.lower().strip()
    for suffix in ("_rss", "_web"):
        if cleaned_name.endswith(suffix):
            cleaned_name = cleaned_name[: -len(suffix)]
    return _slugify_name(cleaned_name)


def load_articles_for_source_type(source_type: str, files: list[Path]) -> list[dict[str, str]]:
    """Load all articles for one source type."""
    articles: list[dict[str, str]] = []

    for file_path in files:
        records = _load_records_from_file(file_path)
        source_name = file_path.stem

        for record in records:
            content = str(record.get("content") or record.get("text") or "").strip()
            if not content:
                continue

            articles.append(
                {
                    "id": str(record.get("id", "")),
                    "title": str(record.get("title", "")),
                    "url": str(record.get("url") or record.get("source_url") or ""),
                    "source": str(record.get("source") or source_name),
                    "source_type": source_type,
                    "source_file": source_name,
                    "domain_group": _infer_domain_group(
                        source_name=source_name,
                        url=str(record.get("url") or record.get("source_url") or ""),
                    ),
                    "scraped_at": str(record.get("scraped_at", "")),
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
            article["source_type"],
            article["source_file"],
            article["domain_group"],
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
                    "source_type": article["source_type"],
                    "source_file": article["source_file"],
                    "domain_group": article["domain_group"],
                }
            )

    return chunk_metadata


def group_articles_by_domain(source_files: dict[str, list[Path]]) -> dict[str, list[dict[str, str]]]:
    """Load all articles and group them by publisher/domain across source types."""
    grouped_articles: dict[str, list[dict[str, str]]] = {}

    for source_type, files in source_files.items():
        articles = load_articles_for_source_type(source_type, files)
        for article in articles:
            grouped_articles.setdefault(article["domain_group"], []).append(article)

    return grouped_articles


def build_embeddings_incrementally(
    chunk_metadata: list[dict[str, Any]],
    save_dir: Path,
) -> np.ndarray:
    """Reuse cached embeddings for unchanged chunks and compute only new ones."""
    from app.embeddings.embed import get_embeddings_batch

    cached_embeddings, cached_metadata = load_embedding_cache(str(save_dir))
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


def build_index_for_domain(domain_group: str, articles: list[dict[str, str]]) -> np.ndarray:
    """Build one incremental FAISS index for one publisher/domain group."""
    print()
    print(f"Processing domain group: {domain_group}")
    print(f"Loaded {len(articles)} articles")
    if not articles:
        print(f"No articles found for domain group: {domain_group}")
        return np.empty((0, 0), dtype=np.float32)

    chunk_metadata = build_chunk_metadata(articles)
    print(f"Total chunks created: {len(chunk_metadata)}")
    if not chunk_metadata:
        print(f"No chunks created for domain group: {domain_group}")
        return np.empty((0, 0), dtype=np.float32)

    save_dir = SAVE_ROOT / domain_group
    embeddings = build_embeddings_incrementally(chunk_metadata, save_dir)
    print("Building FAISS index...")
    index = build_faiss_index(embeddings)

    save_dir.mkdir(parents=True, exist_ok=True)
    save_index(
        index=index,
        metadata=chunk_metadata,
        save_dir=str(save_dir),
        embeddings=embeddings,
    )
    print(f"Index saved to: {save_dir}")
    print(f"Embeddings numpy shape: {embeddings.shape}")
    return embeddings


async def build_index_pipeline() -> dict[str, np.ndarray]:
    """Build separate incremental FAISS indexes for every domain group at once."""
    source_files = discover_source_files()
    if not source_files:
        print("No source-type folders with JSON/JSONL files were found.")
        return {}

    print(f"Found {len(source_files)} source types")
    grouped_articles = group_articles_by_domain(source_files)
    print(f"Found {len(grouped_articles)} domain groups")
    results: dict[str, np.ndarray] = {}

    for domain_group, articles in grouped_articles.items():
        results[domain_group] = build_index_for_domain(domain_group, articles)

    print()
    print("Completed domain-group builds:")
    for domain_group, embeddings in results.items():
        print(f"- {domain_group}: {embeddings.shape}")

    return results


if __name__ == "__main__":
    asyncio.run(build_index_pipeline())
