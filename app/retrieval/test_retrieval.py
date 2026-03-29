"""Manual test for multi-site retrieval."""

from __future__ import annotations

from app.retrieval.faiss_retriever import retrieve_similar_chunks

BASE_DIR = "app/embeddings/vector_index"


def _read_query() -> str:
    """Read a query article or sentence from stdin until a blank line is entered."""
    print("\nPaste the article or query text below.")
    print("Press Enter on an empty line when you are done.\n")

    lines: list[str] = []
    while True:
        line = input()
        if not line.strip():
            break
        lines.append(line)

    return "\n".join(lines).strip()


def main() -> None:
    """Run multi-site retrieval and print the final reranked results."""
    query_text = _read_query()
    if not query_text:
        print("No query text provided.")
        return

    print("\nRunning retrieval across all site indexes...\n")
    results = retrieve_similar_chunks(
        query_text=query_text,
        base_dir=BASE_DIR,
        top_k_per_site=5,
        top_k_final=10,
        threshold=0.3,
    )

    if not results:
        print("No similar chunks were retrieved.")
        return

    print(f"Retrieved {len(results)} final result(s).\n")
    for rank, result in enumerate(results, 1):
        print(f"Rank    : {rank}")
        print(f"Site    : {result['website_name']}")
        print(f"Title   : {result['title']}")
        print(f"Score   : {result['score']:.4f}")
        print(f"URL     : {result['url']}")
        print(f"Scraped : {result['scraped_date']}")
        print(f"Text    : {result['text'][:250]}")
        print("---")


if __name__ == "__main__":
    main()
