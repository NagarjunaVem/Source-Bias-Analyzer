import sys
from pathlib import Path

# Setup the system path so Python can find the "app" module
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio
from app.input.loader import load_text
from app.analysis.bias_detector import analyze_bias


def test_bias_analyzer():
    """Your friend's Bias Analysis / RAG manual testing flow"""
    try:
        from app.retrieval.faiss_retriever import search
    except ImportError as e:
        print(f"\n[ERROR] Missing AI packages for your friend's code: {e}")
        return

    # 1. Load article input
    article = load_text()
    
    INDEX_PATH = "app/embeddings/vector_index/articles.index"
    CHUNKS_PATH = "app/embeddings/vector_index/metadata.json"

    print("\nRetrieving related sources...\n")
    results = search(article, INDEX_PATH, CHUNKS_PATH, top_k=5)

    if not results:
        print("No related sources found. Proceeding without RAG context.\n")
        context = ""
    else:
        context_chunks = []
        for r in results:
            content = r.get("text", "")[:800]
            source = r.get("url", "unknown")
            context_chunks.append(f"[Source: {source}]\n{content}")
        context = "\n\n".join(context_chunks)[:3000]

    combined_input = f"INPUT ARTICLE:\n{article}\n\nRELATED SOURCES:\n{context}"
    print("\nAnalyzing bias with multi-source comparison...\n")
    print("\n=== RESULT ===\n", analyze_bias(combined_input))


def main():
    print("=" * 60)
    print("             SOURCE-BIAS-ANALYZER Pipeline")
    print("=" * 60)
    print(" 1. Start Continuous Deep Scraper & Index Queue (Your Setup)")
    print(" 2. Run Manual Bias Analyzer Test (Your Friend's Setup)")
    print("=" * 60)
    
    choice = input("\nEnter choice (1 or 2): ").strip()
    
    if choice == "1":
        print("\nStarting Automated Crawler and Queue... (Press Ctrl+C to Stop)\n")
        from app.input.news_pipeline.scheduler import main as scheduler_main
        asyncio.run(scheduler_main())
    elif choice == "2":
        test_bias_analyzer()
    else:
        print("Invalid choice, exiting.")

if __name__ == "__main__":
    main()
