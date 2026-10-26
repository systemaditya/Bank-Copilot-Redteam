import json
import math

import httpx
import pytest

from app.rag import EmbeddingError, HashingEmbedder, OllamaEmbedder, PolicyRetriever, load_chunks
from app.rag.chunks import slugify
from tests.conftest import POLICY_DOCS


def test_chunks_have_unique_citation_ids():
    chunks = load_chunks(POLICY_DOCS)
    ids = [chunk.id for chunk in chunks]
    assert len(ids) == len(set(ids))
    assert {"fees#transfer-fees", "transfers#daily-transfer-limits"} <= set(ids)
    assert {chunk.source for chunk in chunks} == {
        "fees.md",
        "transfers.md",
        "accounts-faq.md",
        "privacy-security.md",
    }


def test_slugify():
    assert slugify("ATM and card fees") == "atm-and-card-fees"
    assert slugify("  What we will never ask for! ") == "what-we-will-never-ask-for"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("daily transfer limit", "transfers#daily-transfer-limits"),
        ("monthly account fees", "fees#monthly-account-fees"),
        ("wire transfer fees", "fees#transfer-fees"),
        ("lost or stolen card", "accounts-faq#lost-or-stolen-card"),
        ("savings interest rate", "accounts-faq#savings-interest-rate"),
    ],
)
def test_finds_the_right_section(retriever, query, expected):
    assert retriever.search(query)[0].chunk.id == expected


def test_known_limit_lexical_fallback_ranks_by_word_overlap(retriever):
    # "International wires" appears in the processing-times section too, so the hashing
    # fallback ranks it first. The right section is still in the top 3 the model sees. Week 4
    # compares this against real embeddings on a labelled query set.
    ids = [hit.chunk.id for hit in retriever.search("international wire fee")]
    assert ids[0] == "transfers#processing-times"
    assert "fees#transfer-fees" in ids


def test_hits_are_sorted_and_capped(retriever):
    hits = retriever.search("transfer fees and limits", top_k=4)
    assert 0 < len(hits) <= 4
    scores = [hit.score for hit in hits]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.parametrize("query", ["", "   ", "what is the"])
def test_empty_or_stopword_queries_return_nothing(retriever, query):
    assert retriever.search(query) == []


def test_min_score_filters_weak_matches():
    strict = PolicyRetriever(load_chunks(POLICY_DOCS), HashingEmbedder(), min_score=0.99)
    assert strict.search("fees") == []


def test_index_is_built_once():
    class CountingEmbedder(HashingEmbedder):
        texts_seen = 0

        def embed(self, texts):
            CountingEmbedder.texts_seen += len(texts)
            return super().embed(texts)

    chunks = load_chunks(POLICY_DOCS)
    retriever = PolicyRetriever(chunks, CountingEmbedder())
    retriever.search("fees")
    retriever.search("limits")
    assert CountingEmbedder.texts_seen == len(chunks) + 2


def test_hashing_embedder_is_deterministic_and_unit_length():
    embedder = HashingEmbedder()
    first, second = embedder.embed(["wire transfer fee"]), embedder.embed(["wire transfer fee"])
    assert first == second
    assert math.isclose(sum(x * x for x in first[0]), 1.0)


def test_ollama_embedder_sends_batch_and_normalises():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"embeddings": [[3.0, 4.0], [0.0, 2.0]]})

    embedder = OllamaEmbedder(
        "http://ollama.test", "embed-model", transport=httpx.MockTransport(handler)
    )
    vectors = embedder.embed(["a", "b"])
    assert seen == [("/api/embed", {"model": "embed-model", "input": ["a", "b"]})]
    assert vectors == [[0.6, 0.8], [0.0, 1.0]]


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(500, text="boom"),
        lambda request: httpx.Response(200, text="not json"),
        lambda request: httpx.Response(200, json={"embeddings": [[1.0]]}),  # wrong count
    ],
)
def test_ollama_embedder_errors(handler):
    embedder = OllamaEmbedder("http://ollama.test", "m", transport=httpx.MockTransport(handler))
    with pytest.raises(EmbeddingError):
        embedder.embed(["a", "b"])
