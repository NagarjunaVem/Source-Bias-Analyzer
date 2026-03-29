from app.retrieval.faiss_retriever import search

INDEX_PATH = "app/embeddings/vector_index/articles.index"
CHUNKS_PATH = "app/embeddings/vector_index/metadata.json"


def main():
    print("Semantic Search Ready")

    while True:
        query = input("\nEnter query (or 'exit'): ").strip()

        if query.lower() == "exit":
            break

        results = search(query, INDEX_PATH, CHUNKS_PATH, top_k=3)

        if not results:
            print("No results found.")
            continue

        for i, result in enumerate(results, 1):
            print(f"\nResult {i}")
            print(f"Score: {result.get('score'):.4f}")
            print(f"Title: {result.get('title')}")
            print(f"Content: {result.get('text')[:200]}...")


if __name__ == "__main__":
    main()
