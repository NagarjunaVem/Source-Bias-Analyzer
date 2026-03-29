"""
scheduler.py
-------------
Entry point for the news scraping pipeline.
Creates and runs the NewsCrawler.
"""
import asyncio
import logging

from .crawler import NewsCrawler


def setup_logger():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    return logging.getLogger("scheduler")


logger = setup_logger()


async def main():
    logger.info("Starting news crawler...")

    try:
        crawler = NewsCrawler()
        await crawler.run()
        logger.info("Crawler finished — all BFS queues exhausted.")
    except KeyboardInterrupt:
        logger.info("Crawler stopped by user (Ctrl+C).")
    except Exception as e:
        logger.exception(f"Crawler crashed: {e}")


if __name__ == "__main__":
    asyncio.run(main())