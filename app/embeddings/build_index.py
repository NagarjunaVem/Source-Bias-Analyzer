from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.embeddings.embed import get_embeddings_batch
from app.embeddings.vector_store import build_faiss_index, save_index
from app.embeddings.chunker import chunk_text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = PROJECT_ROOT / "data" / "articles.jsonl"
SAVE_DIR = PROJECT_ROOT / "app" / "embeddings" / "vector_index"


def load_articles():
    if not INPUT_PATH.exists():
        print(f"File not found: {INPUT_PATH}")
        return []

    articles = []

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue

            record = json.loads(line)

            content = str(
                record.get("content") or record.get("text") or ""
            ).strip()

            if not content:
                continue

            articles.append({
                "id": record.get("id", ""),
                "title": record.get("title", ""),
                "source_url": record.get("url", ""),
                "content": content,
            })

    return articles


async def build_index_pipeline():
    articles = load_articles()

    print(f"Loaded {len(articles)} articles")
    if not articles:
        print("No articles found. Run crawler first.")
        return

    chunked_texts = []
    chunk_metadata = []

    # chunking
    for article in articles:
        chunks = chunk_text(article["content"])

        for i, chunk in enumerate(chunks):
            chunked_texts.append(chunk)

            chunk_metadata.append({
                "id": article["id"],
                "title": article["title"],
                "source_url": article["source_url"],
                "content": chunk,
                "chunk_id": i
            })

    print(f"Total chunks created: {len(chunked_texts)}")

    print("Generating embeddings...")
    embeddings = get_embeddings_batch(chunked_texts)
    print("Building FAISS index...")
    index = build_faiss_index(embeddings)

    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    save_index(
        index=index,
        metadata=chunk_metadata,
        save_dir=str(SAVE_DIR)
    )
    print("Index saved to:", SAVE_DIR)


if __name__ == "__main__":
    asyncio.run(build_index_pipeline())