"""Summarize retrieved chunks after simple deduplication."""

from __future__ import annotations

import re

import requests

SUMMARY_TIMEOUT_SECONDS = 60
MAX_SUMMARY_ARTICLES = 2


def deduplicate_chunks(results: list[dict]) -> list[dict]:
    """Remove near-duplicate retrieved chunks using simple word overlap."""
    # Keep the function stable even if retrieval returns nothing.
    if not results:
        print("Deduplication: removed 0 duplicate chunks, kept 0 unique chunks")
        return []

    # Use a small explicit stopword list as requested for simple overlap checking.
    stopwords = {"a", "the", "is", "are", "was", "were", "in", "on", "at", "to", "of", "and", "or"}

    # Normalize each chunk into a token set using lowercase, punctuation removal,
    # and stopword filtering before pairwise comparison.
    normalized_chunks: list[set[str]] = []
    for result in results:
        text = str(result.get("text", "")).lower()
        text = re.sub(r"[^\w\s]", " ", text)
        words = {word for word in text.split() if word and word not in stopwords}
        normalized_chunks.append(words)

    # Track which chunk indices are still considered the best representative.
    keep_indices = set(range(len(results)))

    # Compare every pair of chunks and drop the weaker one when overlap is 90% or more.
    for left_index in range(len(results)):
        if left_index not in keep_indices:
            continue

        for right_index in range(left_index + 1, len(results)):
            if right_index not in keep_indices:
                continue

            words_a = normalized_chunks[left_index]
            words_b = normalized_chunks[right_index]
            union = words_a | words_b
            overlap = 0.0 if not union else len(words_a & words_b) / len(union)

            if overlap < 0.90:
                continue

            left_result = results[left_index]
            right_result = results[right_index]

            # First compare FAISS similarity scores.
            left_score = float(left_result.get("score", 0.0))
            right_score = float(right_result.get("score", 0.0))
            if left_score > right_score:
                keep_indices.discard(right_index)
                continue
            if right_score > left_score:
                keep_indices.discard(left_index)
                break

            # If scores tie, prefer the chunk with longer text.
            left_text = str(left_result.get("text", ""))
            right_text = str(right_result.get("text", ""))
            if len(left_text) > len(right_text):
                keep_indices.discard(right_index)
                continue
            if len(right_text) > len(left_text):
                keep_indices.discard(left_index)
                break

            # If both lengths tie, prefer the chunk with more named entities and numbers.
            left_entities = len(re.findall(r"\b[A-Z][a-zA-Z]+\b|\b\d+(?:\.\d+)?\b", left_text))
            right_entities = len(re.findall(r"\b[A-Z][a-zA-Z]+\b|\b\d+(?:\.\d+)?\b", right_text))
            if left_entities >= right_entities:
                keep_indices.discard(right_index)
            else:
                keep_indices.discard(left_index)
                break

    # Preserve the original retrieval order for all unique chunks that survived.
    unique_chunks = [result for index, result in enumerate(results) if index in keep_indices]
    removed_count = len(results) - len(unique_chunks)
    print(f"Deduplication: removed {removed_count} duplicate chunks, kept {len(unique_chunks)} unique chunks")
    return unique_chunks


def summarize_chunk(text: str) -> str:
    """Summarize one chunk with gemma2:9b using a strict no-outside-knowledge prompt."""
    # Build the exact prompt that forces the model to stay grounded in the provided text.
    prompt = f"""You are a strict grounded summarizer. Your job is to summarize ONLY the content provided below.

    STRICT RULES YOU MUST FOLLOW:
    1. Do NOT add any information from your own knowledge or training data
    2. Do NOT include anything that is not explicitly written in the text below
    3. ONLY remove content that is clearly website noise:
       navigation text, cookie notices, advertisements, unrelated boilerplate
    4. KEEP all claims, statements, facts, opinions, and perspectives
       that are related to the article topic, even if they seem generic
    5. Do NOT judge whether a claim is important; if it is about the topic, keep it
    6. Preserve uncertainty, attribution, disagreement, and speculation exactly as presented
    7. Do NOT rewrite predictions or opinions as established facts
    8. Do NOT soften strong wording and do NOT invent balance that is not present
    9. If the text is opinionated, speculative, or forecast-driven, make that explicit in the bullets
    10. Output exactly 3 concise bullet points
    11. Each bullet point must come directly from the text below and nothing else
    12. Do NOT add any outside knowledge; only use what is written below

    Text to summarize:
    {text}

    Summary (3 bullet points, only from the text above):"""

    # Call the local Ollama API using only requests, and fall back silently to raw text if it fails.
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "gemma2:9b",
                "prompt": prompt,
                "stream": False,
            },
            timeout=SUMMARY_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()["response"]
    except Exception:
        return text


def summarize_retrieved_chunks(results: list[dict], max_articles: int = MAX_SUMMARY_ARTICLES) -> str:
    """Deduplicate chunks, rebuild article-level context, and summarize each source article."""
    # First remove near-identical retrieved chunks so duplicate content is summarized only once.
    unique_results = deduplicate_chunks(results)

    # Group surviving chunks back into their originating article using source, title, and URL.
    grouped_articles: dict[tuple[str, str, str], dict] = {}
    article_order: list[tuple[str, str, str]] = []
    for result in unique_results:
        article_key = (
            str(result.get("website_name", "")),
            str(result.get("title", "")),
            str(result.get("url", "")),
        )
        if article_key not in grouped_articles:
            grouped_articles[article_key] = {
                "website_name": result["website_name"],
                "title": result["title"],
                "url": result["url"],
                "score": float(result.get("score", 0.0)),
                "chunks": [],
            }
            article_order.append(article_key)

        grouped_articles[article_key]["score"] = max(
            grouped_articles[article_key]["score"],
            float(result.get("score", 0.0)),
        )
        grouped_articles[article_key]["chunks"].append(result)

    # Summarize each reconstructed article instead of each individual chunk.
    summaries: list[str] = []
    for article_key in article_order[:max_articles]:
        article = grouped_articles[article_key]
        ordered_chunks = sorted(
            article["chunks"],
            key=lambda chunk: (int(chunk.get("chunk_id", 0)), -float(chunk.get("score", 0.0))),
        )
        article_text = " ".join(str(chunk.get("text", "")) for chunk in ordered_chunks).strip()
        article_text = article_text[:1400]
        summary = summarize_chunk(article_text)
        summaries.append(
            f"[{article['website_name']} | {article['title']} | Score: {article['score']:.2f}]\n{summary}"
        )

    # Join all summaries into one combined context string for the downstream analysis step.
    return "\n\n".join(summaries)


if __name__ == "__main__":
    dummy_results = [
        {
            "chunk_id": 1,
            "text": "The government announced new economic policies targeting inflation and unemployment rates dropped to 3.2 percent...",
            "title": "Economic Policy Update",
            "url": "https://bbc.com/news/economy",
            "scraped_date": "2024-01-15",
            "score": 0.87,
            "website_name": "BBC"
        },
        {
            "chunk_id": 2,
            "text": "Officials added that the policy package also targeted borrowing costs and consumer prices over the next quarter...",
            "title": "Economic Policy Update",
            "url": "https://bbc.com/news/economy",
            "scraped_date": "2024-01-15",
            "score": 0.84,
            "website_name": "BBC"
        }
    ]
    context = summarize_retrieved_chunks(dummy_results)
    print(context)
    # Both retrieved chunks belong to the same original article.
    # The summarizer rebuilds article text from the retrieved chunks first.
    # Then it summarizes the reconstructed source article as one unit.
