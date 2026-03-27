from typing import List


def chunk_text(
    text: str,
    chunk_size: int = 300,
    overlap: int = 50
) -> List[str]:
    """
    Split text into overlapping chunks (word-based).

    Args:
        text: input article
        chunk_size: words per chunk
        overlap: overlap between chunks

    Returns:
        List of chunks
    """

    words = text.split()
    chunks = []

    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = words[start:end]

        if not chunk:
            break

        chunks.append(" ".join(chunk))

        # move with overlap
        start += chunk_size - overlap

    return chunks