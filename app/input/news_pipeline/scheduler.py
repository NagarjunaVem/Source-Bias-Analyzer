import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from news_pipeline.crawler import NewsCrawler


async def run_crawler_once():
    crawler = NewsCrawler()
    await crawler.run(run_once=True)


def start_scheduler():
    scheduler = AsyncIOScheduler()

    # Run every 30 minutes
    scheduler.add_job(
        lambda: asyncio.create_task(run_crawler_once()),
        trigger="interval",
        minutes=30
    )

    scheduler.start()

    print("Scheduler started...")

    asyncio.get_event_loop().run_forever()