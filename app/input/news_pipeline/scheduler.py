import asyncio
import logging
import sys
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from news_pipeline.crawler import NewsCrawler

# ─── CONFIGURE INTERVAL HERE ───────────────────────────────────────────────
INTERVAL_MINUTES = 30
# ───────────────────────────────────────────────────────────────────────────


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

    # Run immediately on startup, then every INTERVAL_MINUTES
    scheduler.add_job(
        run_crawler_once,
        trigger="interval",
        minutes=INTERVAL_MINUTES,
        max_instances=1,
        coalesce=True,
        next_run_time=__import__("datetime").datetime.now(),  # fire immediately
    )

    scheduler.start()
    logger.info(
        "Scheduler started — running immediately, then every %d minutes. "
        "Scraper will restart itself after each cycle.",
        INTERVAL_MINUTES,
    )

    try:
        while True:
            await asyncio.sleep(INTERVAL_MINUTES * 60)

            # After each full interval, restart the whole process so there is
            # zero memory/state accumulation across long-running cycles.
            logger.info(
                "Interval elapsed — restarting scraper process now..."
            )
            scheduler.shutdown(wait=False)

            # Re-execute this exact script with the same interpreter and args.
            # os.execv replaces the current process — no orphan processes.
            os.execv(sys.executable, [sys.executable] + sys.argv)

    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())