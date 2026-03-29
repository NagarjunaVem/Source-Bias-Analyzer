from typing import List


def chunk_text(
    text: str,
    chunk_size: int = 180,
    overlap: int = 30
) -> List[str]:
    """
    Split text into safer overlapping chunks for embedding and retrieval.

    Args:
        text: input article
        chunk_size: target words per chunk
        overlap: overlap between chunks

    Returns:
        List of chunks
    """
    normalized_text = " ".join(str(text).split())
    if not normalized_text:
        return []

    words = normalized_text.split()
    chunks: List[str] = []

    step = max(1, chunk_size - overlap)
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk_words = words[start:end]
        if not chunk_words:
            break

        chunks.append(" ".join(chunk_words))

        if end >= len(words):
            break

        # Move forward with overlap so adjacent chunks retain context.
        start += step

    return chunks
