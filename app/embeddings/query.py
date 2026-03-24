from app.embeddings.vector_store import load_index, search

INDEX_DIR = "app/embeddings/vector_index"


def main():
    # load FAISS index
    index, metadata = load_index(INDEX_DIR)

    print("🔎 Semantic Search Ready")

    while True:
        query = input("\nEnter query (or 'exit'): ").strip()

        if query.lower() == "exit":
            break

        results = search(query, index, metadata, top_k=3)

        if not results:
            print("No results found.")
            continue

        for i, r in enumerate(results, 1):
            print(f"\nResult {i}")
            print(f"Score: {r.get('score'):.4f}")
            print(f"Title: {r.get('title')}")
            print(f"Content: {r.get('content')[:200]}...")


if __name__ == "__main__":
    main()