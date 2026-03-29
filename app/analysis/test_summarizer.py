"""Manual test for summarizer and chunk deduplication."""

from __future__ import annotations

from app.analysis.summarizer import deduplicate_chunks, summarize_retrieved_chunks


def main() -> None:
    """Run the summarizer pipeline on sample retrieved chunks."""
    dummy_results = [
        {
            "chunk_id": 1,
            "text": "The government announced new economic policies targeting inflation. "
                    "Officials said unemployment dropped to 3.2 percent. "
                    "Read more articles and subscribe for updates.",
            "title": "Economic Policy Update",
            "url": "https://bbc.com/news/economy",
            "scraped_date": "2024-01-15",
            "score": 0.87,
            "website_name": "BBC",
        },
        {
            "chunk_id": 2,
            "text": "The government announced new economic policies targeting inflation. "
                    "Officials said unemployment dropped to 3.2 percent. "
                    "Read more articles and subscribe for updates.",
            "title": "Economy News",
            "url": "https://reuters.com/economy",
            "scraped_date": "2024-01-15",
            "score": 0.81,
            "website_name": "Reuters",
        },
        {
            "chunk_id": 3,
            "text": "Analysts said the policy may affect borrowing costs in the coming months.",
            "title": "Policy Analysis",
            "url": "https://thehindu.com/business",
            "scraped_date": "2024-01-15",
            "score": 0.76,
            "website_name": "The Hindu",
        },
    ]

    unique_results = deduplicate_chunks(dummy_results)
    print(f"\nUnique chunk count: {len(unique_results)}\n")

    context = summarize_retrieved_chunks(dummy_results)
    print("Combined summary context:\n")
    print(context)


if __name__ == "__main__":
    main()
