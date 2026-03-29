"""Manual retrieval test for pasting a user article and inspecting top-k matches."""

from __future__ import annotations

from app.embeddings.embed import get_embedding
from app.retrieval.faiss_retriever import retrieve_similar_chunks

INDEX_PATH = "app/embeddings/vector_index/articles.index"
CHUNKS_PATH = "app/embeddings/vector_index/metadata.json"


def _read_article_input() -> str:
    """Read a pasted article from stdin until the user submits a blank line."""
    print("\nPaste the user article below.")
    print("Press Enter on an empty line when you are done.\n")

    lines: list[str] = []
    while True:
        line = input()
        if not line.strip():
            break
        lines.append(line)

    return "\n".join(lines).strip()


def main() -> None:
    """Embed the pasted article and print the top-k retrieved chunks."""
    article_text = _read_article_input()
    if not article_text:
        print("No article text provided.")
        return

    print("\nGenerating embedding for the input article...\n")
    query_embedding = get_embedding(article_text).reshape(1, -1)

    print("Running retrieval...\n")
    results = retrieve_similar_chunks(
        query_embedding=query_embedding,
        index_path=INDEX_PATH,
        chunks_path=CHUNKS_PATH,
        top_k=5,
        threshold=0.5,
    )

    if not results:
        print("No similar chunks were retrieved.")
        return

    print(f"Retrieved {len(results)} chunk(s).\n")
    for rank, result in enumerate(results, 1):
        print(f"Rank: {rank}")
        print(f"Chunk ID: {result['chunk_id']}")
        print(f"Website: {result['website_name']}")
        print(f"Title: {result['title']}")
        print(f"URL: {result['url']}")
        print(f"Scraped Date: {result['scraped_date']}")
        print(f"Score: {result['score']:.4f}")
        print(f"Text Preview: {result['text'][:250]}")
        print("---")


if __name__ == "__main__":
    main()
