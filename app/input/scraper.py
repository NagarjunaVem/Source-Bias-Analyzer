from __future__ import annotations

import argparse
import asyncio

from news_pipeline.crawler import NewsCrawler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Distributed parallel news scraper with recursive discovery and JSON output "
            "for new articles not present in main metadata."
        )
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Poll all sources once, drain queues, then exit.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    crawler = NewsCrawler()
    asyncio.run(crawler.run(run_once=args.run_once))


if __name__ == "__main__":
    main()
