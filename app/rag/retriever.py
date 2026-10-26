"""Embedding search over the policy chunks.

There are only a couple of dozen chunks, so a plain list of vectors is plenty. The index is
built the first time someone searches, which keeps app startup fast and means a missing
embedding model only breaks policy lookups, not the whole app.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from app.config import Settings
from app.rag.chunks import Chunk, load_chunks
from app.rag.embeddings import Embedder, cosine, make_embedder


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float


class PolicyRetriever:
    def __init__(self, chunks: list[Chunk], embedder: Embedder, min_score: float = 0.0) -> None:
        self.chunks = chunks
        self.embedder = embedder
        self.min_score = min_score
        self._vectors: list[list[float]] | None = None
        self._lock = threading.Lock()

    def _index(self) -> list[list[float]]:
        with self._lock:
            if self._vectors is None:
                self._vectors = self.embedder.embed([chunk.embed_text for chunk in self.chunks])
            return self._vectors

    def search(self, query: str, top_k: int = 3) -> list[Hit]:
        query = query.strip()
        if not query:
            return []
        vectors = self._index()
        [query_vector] = self.embedder.embed([query])
        scored = sorted(
            ((cosine(query_vector, vector), i) for i, vector in enumerate(vectors)),
            key=lambda item: (-item[0], item[1]),
        )
        return [
            Hit(self.chunks[i], round(score, 4))
            for score, i in scored[:top_k]
            if score > 0 and score >= self.min_score
        ]


def make_retriever(settings: Settings) -> PolicyRetriever:
    return PolicyRetriever(
        load_chunks(settings.policy_docs_dir), make_embedder(settings), settings.rag_min_score
    )
