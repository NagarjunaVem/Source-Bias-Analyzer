"""Manual test for reranking retrieval results."""

from __future__ import annotations

from app.retrieval.reranker import rerank_results


def main() -> None:
    """Create sample retrieval results and verify reranking order."""
    dummy_results = [
        {
            "chunk_id": 1,
            "text": "Inflation eased after the policy announcement.",
            "title": "Economic Policy Update",
            "url": "https://bbc.com/news/economy",
            "scraped_date": "2024-01-15",
            "score": 0.87,
            "website_name": "BBC",
        },
        {
            "chunk_id": 2,
            "text": "Officials said unemployment fell to 3.2 percent.",
            "title": "Economy Brief",
            "url": "https://reuters.com/world",
            "scraped_date": "2024-01-15",
            "score": 0.91,
            "website_name": "Reuters",
        },
        {
            "chunk_id": 3,
            "text": "Markets reacted cautiously to the news.",
            "title": "Market Reaction",
            "url": "https://cnbc.com/markets",
            "scraped_date": "2024-01-15",
            "score": 0.79,
            "website_name": "CNBC",
        },
    ]

    final_results = rerank_results(dummy_results, top_k_final=2)
    print("\nTop reranked results:\n")
    for rank, result in enumerate(final_results, 1):
        print(f"Rank    : {rank}")
        print(f"Site    : {result['website_name']}")
        print(f"Title   : {result['title']}")
        print(f"Score   : {result['score']:.4f}")
        print(f"Text    : {result['text'][:100]}")
        print("---")


if __name__ == "__main__":
    main()
