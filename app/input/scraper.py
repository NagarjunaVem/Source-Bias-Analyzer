"""
scraper.py
----------
Entry point to run the news scraping pipeline.
Run from project root:  python -m app.input.scraper
"""

import sys
from pathlib import Path

# Setup the system path so Python can find the "app" module, no matter where this script is executed from
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.input.news_pipeline.scheduler import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())