import sys
from pathlib import Path

# Setup the system path so Python can find the "app" module
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio
from app.input.loader import load_text
from app.analysis.bias_detector import analyze_bias
from app.retrieval.faiss_retriever import search

INDEX_BASE_DIR = "app/embeddings/vector_index"


def test_bias_analyzer():
    """Run the upgraded evidence-based analysis pipeline in manual mode."""

    article = load_text()
    print("\nRetrieving related sources...\n")
    results = search(article, INDEX_BASE_DIR, top_k=5)

    if not results:
        print("No related sources found. Proceeding with fallback-safe analysis.\n")
    else:
        for result in results[:5]:
            print(f"- {result.get('title', 'Untitled')} | {result.get('website_name', 'Unknown')}")

    print("\nAnalyzing bias with multi-source comparison...\n")
    print("\n=== RESULT ===\n", analyze_bias(article, retrieval_base_dir=INDEX_BASE_DIR))


def main():
    print("=" * 60)
    print("             SOURCE-BIAS-ANALYZER Pipeline")
    print("=" * 60)
    print(" 1. Start Continuous Scraper Loop           (Terminal A)")
    print(" 2. Start Background Embedder Queue Worker  (Terminal B)")
    print(" 3. Run Manual Bias Analyzer Test           (Your Friend's Setup)")
    print("=" * 60)
    
    choice = input("\nEnter choice (1, 2, or 3): ").strip()
    
    if choice == "1":
        print("\nStarting Automated Crawler... (Press Ctrl+C to Stop)\n")
        from app.input.news_pipeline.scheduler import start_scraper_only
        asyncio.run(start_scraper_only())
    elif choice == "2":
        print("\nStarting Background Embedder Queue... (Press Ctrl+C to Stop)\n")
        from app.input.news_pipeline.scheduler import start_embedder_only
        asyncio.run(start_embedder_only())
    elif choice == "3":
        test_bias_analyzer()
    else:
        print("Invalid choice, exiting.")

if __name__ == "__main__":
    main()
