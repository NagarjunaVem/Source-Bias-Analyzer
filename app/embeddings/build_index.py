from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.embeddings.embed import get_embeddings_batch
from app.embeddings.vector_store import build_faiss_index, save_index

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = PROJECT_ROOT / "data" / "articles.jsonl"
SAVE_DIR = PROJECT_ROOT / "app" / "embeddings" / "vector_index"


def load_articles():
    """Load articles from JSONL file (crawler output)."""

    if not INPUT_PATH.exists():
        print(f"❌ File not found: {INPUT_PATH}")
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

    contents = [article["content"] for article in articles]

    print("Generating embeddings...")
    embeddings = get_embeddings_batch(contents)

    print("Building FAISS index...")
    index = build_faiss_index(embeddings)

    SAVE_DIR.mkdir(parents=True, exist_ok=True)

    save_index(index=index, metadata=articles, save_dir=str(SAVE_DIR))

    print("Index saved to:", SAVE_DIR)


if __name__ == "__main__":
    asyncio.run(build_index_pipeline())