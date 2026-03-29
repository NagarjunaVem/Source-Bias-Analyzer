"""Helpers for handling empty retrieval output."""


def handle_empty_results(results: list[dict], query_text: str) -> list[dict]:
    """Return an empty list safely with clear diagnostics when nothing was retrieved."""
    if len(results) == 0:
        print(f"WARNING: No results found for query: '{query_text}'")
        print("Possible reasons:")
        print("  1. Query too specific - try broader terms")
        print("  2. All site scores below threshold 0.3")
        print("  3. FAISS indexes may be empty or corrupted")
        print("  4. Ollama embedding failed silently")
        return []
    return results
