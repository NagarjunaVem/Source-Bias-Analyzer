from app.input.loader import load_text
from app.analysis.bias_detector import analyze_bias
from app.retrieval.faiss_retriever import search

INDEX_PATH = "app/embeddings/vector_index/articles.index"
CHUNKS_PATH = "app/embeddings/vector_index/metadata.json"


def build_context(results, max_chars=3000):
    """
    Combine retrieved articles into a context string.
    Limit size to avoid token overflow.
    """
    context_chunks = []

    for r in results:
        content = r.get("text", "")[:800]  # trim each doc
        source = r.get("url", "unknown")

        chunk = f"[Source: {source}]\n{content}"
        context_chunks.append(chunk)

    context = "\n\n".join(context_chunks)

    return context[:max_chars]


def main():
    # 1. Load article input
    article = load_text()

    print("\nLoading retrieval index...\n")

    # 2. Retrieve similar articles (RAG)
    print("\nRetrieving related sources...\n")
    results = search(article, INDEX_PATH, CHUNKS_PATH, top_k=5)

    if not results:
        print("No related sources found. Proceeding without RAG context.\n")
        context = ""
    else:
        context = build_context(results)

    # 4. Combine article + retrieved context
    combined_input = f"""
    INPUT ARTICLE:
    {article}

    RELATED SOURCES:
    {context}
    """

    print("\nAnalyzing bias with multi-source comparison...\n")

    # 5. Run LLM analysis
    result = analyze_bias(combined_input)

    # 6. Output
    print("\n=== RESULT ===\n")
    print(result)


if __name__ == "__main__":
    main()
