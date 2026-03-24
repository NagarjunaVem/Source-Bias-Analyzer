import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from news_pipeline.crawler import NewsCrawler


def setup_logger():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    return logging.getLogger("scheduler")


logger = setup_logger()


async def run_crawler_once():
    logger.info("Starting crawler job...")

    try:
        crawler = NewsCrawler()
        await crawler.run(run_once=True)
        logger.info("Crawler job finished")
    except Exception as e:
        logger.exception(f"Crawler crashed: {e}")


async def main():
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        run_crawler_once,
        trigger="interval",
        minutes=30,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    logger.info("Scheduler started")

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())