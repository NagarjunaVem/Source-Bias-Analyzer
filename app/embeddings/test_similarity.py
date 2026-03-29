import numpy as np

from app.embeddings.embed import get_embedding


def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


if __name__ == "__main__":
    s1 = input("Sentence 1: ")
    s2 = input("Sentence 2: ")

    e1 = get_embedding(s1)
    e2 = get_embedding(s2)

    sim = cosine_similarity(e1, e2)
    print(f"\nSimilarity: {sim:.4f}")
