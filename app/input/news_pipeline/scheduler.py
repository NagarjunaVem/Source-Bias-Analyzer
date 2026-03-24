import asyncio
import logging
from .crawler import NewsCrawler


def setup_logger():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    return logging.getLogger("scheduler")


logger = setup_logger()


async def main():
    logger.info("Starting crawler...")

    try:
        crawler = NewsCrawler()
        await crawler.run(run_once=True)
        logger.info("Crawler finished successfully")
    except Exception as e:
        logger.exception(f"Crawler crashed: {e}")


if __name__ == "__main__":
    asyncio.run(main())