"""Embedding generation.

There is NO real Embedding model in this phase, so `generate_embedding` is a
deterministic MOCK. It hashes tokens into a normalized 1536-dim vector, so texts
that share tokens produce similar vectors — enough to exercise the pgvector
INSERT and cosine-similarity query end-to-end.

TODO(Future Agent backend): replace the body with a real Embedding API call
(e.g. OpenAI text-embedding-3-small) without changing the signature:

    def generate_embedding(text: str) -> list[float]: ...
"""
import hashlib
import math
import random

EMBEDDING_DIM = 1536  # must match VECTOR(1536) in backend/schema.sql


def generate_embedding(text: str) -> list:
    """Return a deterministic mock 1536-dim embedding for `text`."""
    vector = [0.0] * EMBEDDING_DIM
    for token in text.lower().split():
        seed = int.from_bytes(
            hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big"
        )
        rng = random.Random(seed)
        for _ in range(4):  # each token votes on 4 dimensions
            dim = rng.randrange(EMBEDDING_DIM)
            vector[dim] += 1.0 if rng.getrandbits(1) else -1.0
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0.0:  # empty / punctuation-only input
        vector[0] = 1.0
        return vector
    return [x / norm for x in vector]
