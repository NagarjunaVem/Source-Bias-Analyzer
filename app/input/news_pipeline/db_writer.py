import asyncio
import asyncpg
import logging
from news_pipeline.models import DetailedArticleRecord
from app.embeddings.embed import get_embedding
from app.embeddings.vector_store import load_index, save_index
import faiss
import numpy as np


class PostgresWriter:
    def __init__(self, dsn: str, logger: logging.Logger):
        self.dsn = dsn
        self.logger = logger
        self.pool = None
        self.count = 0
        self.index = None
        self.metadata = []
        self.index_path = "app/embeddings/vector_index"
        self.save_counter = 0
        self.seen_ids = set()
        self.seen_hashes = set()

    async def connect(self):
        self.pool = await asyncpg.create_pool(self.dsn)
        self.logger.info("Connected to PostgreSQL")
        try:
            self.index, self.metadata = load_index(self.index_path)
            self.logger.info("FAISS index loaded")
            # load existing IDs to avoid duplicates
            for item in self.metadata:
                if "id" in item:
                    self.seen_ids.add(item["id"])
                    self.seen_hashes.add(item["hash"])
        except Exception:
            self.logger.warning("No existing index found, starting fresh")
            self.index = faiss.IndexFlatIP(384)
            self.metadata = []

    async def run(self, queue: asyncio.Queue, stop_event: asyncio.Event):
        await self.connect()
        self.logger.info("Postgres writer started")

        while not stop_event.is_set() or not queue.empty():
            try:
                item = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            try:
                self.logger.info(f"Inserting: {item.url}")
                await self.insert_article(item)
                self.count += 1
                self.logger.info(f"Total inserted: {self.count}")
            except Exception as e:
                self.logger.exception(f"DB ERROR: {e}")
            finally:
                queue.task_done()

    async def insert_article(self, record: DetailedArticleRecord):
        query = """
        INSERT INTO articles (
            id, url, title, content, summary,
            source, published_at, language, tags
        )
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)

        ON CONFLICT (url)
        DO UPDATE SET
            title = EXCLUDED.title,
            content = EXCLUDED.content,
            summary = EXCLUDED.summary,
            tags = EXCLUDED.tags;
        """

        async with self.pool.acquire() as conn:
            result = await conn.execute(
                query,
                record.id,
                record.url,
                record.title,
                record.text,
                record.summary,
                record.source,
                record.published_at,
                record.language,
                record.tags,
            )

            self.logger.info(f"DB RESULT: {result}")

            # Skip duplicate URL
            if record.id in self.seen_ids:
                self.logger.info(f"Duplicate skipped (id): {record.url}")
                return

            # Skip duplicate content
            if record.hash in self.seen_hashes:
                self.logger.info(f"Duplicate skipped (content): {record.url}")
                return
            self.seen_ids.add(record.id)
            self.seen_hashes.add(record.hash)

            vector = get_embedding(record.text)
            # reshape + normalize
            vector = vector.reshape(1, -1)
            faiss.normalize_L2(vector)
            
            # add to index
            self.index.add(vector)

            # store metadata
            self.metadata.append({
            "id": record.id,
            "title": record.title,
            "content": record.text,
            "url": record.url,
            })

            # batch save (every 50 inserts)
            self.save_counter += 1

            if self.save_counter % 50 == 0:
                save_index(self.index, self.metadata, self.index_path)
                self.logger.info("FAISS index saved (batch)")