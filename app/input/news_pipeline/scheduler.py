"""
scheduler.py
-------------
Runs the news crawler and the indexing pipeline using a Producer-Consumer model.

1. PRODUCER (Scraper Loop):
   - Runs all scrapers continuously.
   - Every 5 hours, force-terminates the crawler.
   - Moves all JSON data (data/web/*.json + data/rss/*.json) into
     a new timestamped queue folder (data/indexing_queue/cycle...).
   - Restarts the crawler immediately with fresh, empty folders.

2. CONSUMER (Index Worker):
   - Runs continuously in the background.
   - Scans the `indexing_queue` folder.
   - If a cycle folder is found:
       - Consolidates its JSONs into `data/new_articles_detailed.jsonl`.
       - Triggers `build_index_pipeline()` to update the FAISS vector database.
       - Deletes ("scraps") the cycle folder to save disk space.
"""

import asyncio
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

from .crawler import NewsCrawler
from .config import load_settings


# ── Logger ────────────────────────────────────────────────────────────────────

def setup_logger():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    return logging.getLogger("scheduler")

logger = setup_logger()


# ── Producer: Move data to queue ──────────────────────────────────────────────

def move_to_index_queue(output_base: Path, cycle: int) -> Path | None:
    """
    Move all JSON files from data/web/ and data/rss/ into
    data/indexing_queue/cycle_{N}_YYYYMMDD_HHMMSS/.
    This leaves the original folders empty so the crawler restarts fresh.
    """
    web_dir = output_base / "web"
    rss_dir = output_base / "rss"

    # Check if there is anything to queue
    if not any(d.exists() and list(d.glob("*.json")) for d in [web_dir, rss_dir]):
        logger.info("No JSON data found to queue — skipping.")
        return None

    # Create the queue folder and cycle specific folder
    queue_dir = output_base / "indexing_queue"
    queue_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cycle_folder_name = f"cycle_{cycle}_{timestamp}"
    cycle_path = queue_dir / cycle_folder_name
    cycle_path.mkdir()

    moved_count = 0
    # Move web/ and rss/ subdirectories directly into the cycle folder
    for source_dir in (web_dir, rss_dir):
        if source_dir.exists():
            dest_dir = cycle_path / source_dir.name
            # shutil.move handles directory moving over safely
            shutil.move(str(source_dir), str(dest_dir))
            moved_count += len(list(dest_dir.glob("*.json")))

    logger.info("📦 Queued cycle data to '%s' (%d JSON files moved).", cycle_folder_name, moved_count)
    return cycle_path


# ── Consumer: Process the queue ───────────────────────────────────────────────

def _append_to_master_jsonl(cycle_path: Path, output_base: Path):
    """
    Read all .json files in a specific cycle folder and append them
    as JSON Lines (jsonl) to the master articles database.
    """
    # The master jsonl file the build_index_pipeline expects
    master_jsonl_path = output_base / "new_articles_detailed.jsonl"
    
    appended_count = 0
    with master_jsonl_path.open("a", encoding="utf-8") as master_file:
        # Recursively find all json files in the cycle folder
        for json_file in cycle_path.rglob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for article in data:
                        if isinstance(article, dict):
                            # Write each article as a single line
                            master_file.write(json.dumps(article, ensure_ascii=False) + "\n")
                            appended_count += 1
            except Exception as e:
                logger.error(f"Error reading {json_file.name}: {e}")

    logger.info("Consolidated %d total articles into master jsonl.", appended_count)


async def index_worker(output_base: Path):
    """
    Background daemon that continuously checks the indexing_queue.
    If a cycle folder is found, it processes it into the FAISS index
    and then deletes the folder.
    """
    queue_dir = output_base / "indexing_queue"
    queue_dir.mkdir(parents=True, exist_ok=True)

    while True:
        try:
            # 1. Grab all folders inside indexing_queue, sort by oldest first
            cycle_folders = sorted(
                [f for f in queue_dir.iterdir() if f.is_dir()]
            )

            for folder in cycle_folders:
                print(f"\n\033[1;35m{'='*70}\033[0m")
                print(f"\033[1;35m🧠 [INDEX BUILDER] Processing {folder.name}\033[0m")
                print(f"\033[1;35m{'='*70}\033[0m\n")

                # Step A: Consolidate scraped separate JSONs into the master JSONL
                _append_to_master_jsonl(folder, output_base)

                # Step B: Trigger the isolated Neural Embeddings generation for this specific cycle!
                logger.info(f"Triggering raw Vector Generating Pipeline for new cycle data...")
                from app.input.news_pipeline.queue_embedder import process_cycle_embeddings
                
                success = await process_cycle_embeddings(folder, output_base)
                if not success:
                    logger.warning("Embedding tools unavailable or failed. Retrying next tick.")
                    break
                
                # Step C: Delete ("scrap") the cycle folder after a successful independent embedding pass
                logger.info(f"Raw Embedding Vectors Built Successfully. Scrapping folder '{folder.name}' to save drive space...")
                shutil.rmtree(folder)
                
                print(f"\033[1;32m✅ Successfully scrapped generic Queue file! Waiting for next scraper drop-off.\033[0m\n")

        except Exception as e:
            logger.exception(f"Index Worker encountered an error: {e}")

        # Sleep a bit before checking the queue again
        await asyncio.sleep(60)


# ── The main orchestrator loops ───────────────────────────────────────────────

async def crawler_loop(settings):
    """
    Runs the scraping aspect natively in force-terminated loops based on settings.
    """
    cycle = 0
    cycle_duration_seconds = settings.cycle_interval_minutes * 60

    while True:
        cycle += 1
        start_time = datetime.now()

        print(f"\n\033[1;33m{'='*70}\033[0m")
        print(f"\033[1;33m⏱️  SCRAPER CYCLE {cycle} STARTING — {start_time.strftime('%Y-%m-%d %H:%M:%S')}\033[0m")
        print(f"\033[1;33m   Duration Limit: {cycle_duration_seconds // 3600}h {(cycle_duration_seconds % 3600) // 60}m\033[0m")
        print(f"\033[1;33m{'='*70}\033[0m\n")

        # ── 1. Run the crawler with a hard timeout ─────────────────────────────
        crawler = NewsCrawler(settings=settings)

        try:
            await asyncio.wait_for(
                crawler.run(),
                timeout=cycle_duration_seconds,
            )
            logger.info("Crawler finished naturally before timeout limit.")

        except asyncio.TimeoutError:
            logger.info(f"⏰ {settings.cycle_interval_minutes}-minute timeout reached — force-terminating crawler.")

        except Exception as e:
            logger.exception(f"Crawler crashed during cycle {cycle}: {e}")

        # ── 2. Move data to Index Queue ─────────────────────────────────────────
        end_time = datetime.now()
        elapsed = end_time - start_time

        print(f"\n\033[1;36m{'='*70}\033[0m")
        print(f"\033[1;36m📦 HANDING OFF CYCLE {cycle} DATA TO INDEX QUEUE\033[0m")
        print(f"\033[1;36m   Ran for: {elapsed}\033[0m")
        print(f"\033[1;36m{'='*70}\033[0m\n")

        queue_path = move_to_index_queue(settings.output_base_path, cycle)
        if queue_path:
            logger.info("Cycle data dropped in %s", queue_path.name)
        else:
            logger.warning("No data produced in this cycle.")

        # Brief pause before next cycle
        print(f"\n\033[1;33m🔄 Restarting crawler immediately...\033[0m\n")
        await asyncio.sleep(5)


async def start_scraper_only():
    """
    Spins up strictly the Scraper Loop (Producer).
    """
    settings = load_settings()
    await crawler_loop(settings)


async def start_embedder_only():
    """
    Spins up strictly the background queue monitor (Consumer).
    """
    settings = load_settings()
    await index_worker(settings.output_base_path)


if __name__ == "__main__":
    print("Use main.py to start separated pipelines.")