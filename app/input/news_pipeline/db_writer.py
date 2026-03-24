import asyncio
import asyncpg
import logging
from news_pipeline.models import DetailedArticleRecord


class PostgresWriter:
    def __init__(self, dsn: str, logger: logging.Logger):
        self.dsn = dsn
        self.logger = logger
        self.pool = None
        self.count = 0

    async def connect(self):
        self.pool = await asyncpg.create_pool(self.dsn)
        self.logger.info("Connected to PostgreSQL")

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
        ON CONFLICT (id) DO NOTHING
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