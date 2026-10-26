"""Text embedders for policy retrieval.

``OllamaEmbedder`` is the real one. ``HashingEmbedder`` is a lexical stand-in so tests and CI
run without a model: it matches overlapping words and word fragments, but it has no idea that
"wire" and "send money abroad" mean the same thing.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

import httpx

from app.config import Settings


class EmbeddingError(RuntimeError):
    """The embedding backend couldn't be reached or returned something unusable."""


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def normalise(vector: list[float]) -> list[float]:
    length = math.sqrt(sum(x * x for x in vector))
    return [x / length for x in vector] if length else vector


def cosine(a: list[float], b: list[float]) -> float:
    """Dot product of two vectors that are already unit length."""
    return sum(x * y for x, y in zip(a, b, strict=True))


_WORD = re.compile(r"[a-z0-9]+")
# fmt: off
_STOPWORDS = frozenset([
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "how",
    "i", "in", "is", "it", "me", "my", "of", "on", "or", "the", "to", "what", "when", "where",
    "which", "with", "you", "your",
])
# fmt: on


def _tokens(text: str) -> list[str]:
    words = (w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS)
    return [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words]


class HashingEmbedder:
    name = "hashing"

    def __init__(self, dims: int = 1024) -> None:
        self.dims = dims

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dims
        for feature, weight in self._features(text):
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dims
            vector[index] += weight if digest[4] & 1 else -weight
        return normalise(vector)

    @staticmethod
    def _features(text: str):
        for token in _tokens(text):
            yield f"w:{token}", 2.0
            padded = f"#{token}#"
            for i in range(len(padded) - 2):
                yield f"c:{padded[i : i + 3]}", 0.5


class OllamaEmbedder:
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_s: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self._http = httpx.Client(base_url=base_url, timeout=timeout_s, transport=transport)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = self._http.post("/api/embed", json={"model": self.model, "input": texts})
            response.raise_for_status()
            vectors = response.json().get("embeddings")
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"Ollama embedding request failed: {exc}") from exc
        except ValueError as exc:
            raise EmbeddingError("Ollama returned a non-JSON response.") from exc
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbeddingError("Ollama returned the wrong number of embeddings.")
        return [normalise([float(x) for x in vector]) for vector in vectors]


def make_embedder(settings: Settings) -> Embedder:
    if settings.embedding_backend == "ollama":
        return OllamaEmbedder(
            settings.ollama_url, settings.embedding_model, timeout_s=settings.request_timeout_s
        )
    if settings.embedding_backend == "hashing":
        return HashingEmbedder()
    raise ValueError(f"Unknown embedding_backend: {settings.embedding_backend!r}")
