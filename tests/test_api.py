import pytest
from fastapi.testclient import TestClient

from app.llm import LLMError, LLMResponse, ScriptedLLM, ToolCall
from app.main import create_app


class FailingLLM:
    def chat(self, messages, tools):
        raise LLMError("connection refused")


@pytest.fixture
def make_client(settings, engine):
    def _make(llm):
        return TestClient(create_app(settings, llm=llm, engine=engine))

    return _make


def login(client, customer_number):
    response = client.post("/auth/login", json={"customer_number": customer_number})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_health(make_client):
    assert make_client(ScriptedLLM([])).get("/health").json()["status"] == "ok"


def test_login_unknown_customer(make_client):
    response = make_client(ScriptedLLM([])).post("/auth/login", json={"customer_number": "C9"})
    assert response.status_code == 404


@pytest.mark.parametrize("header", [None, "Bearer", "Bearer nope", "Basic abc"])
def test_chat_requires_valid_session(make_client, header):
    headers = {"Authorization": header} if header else {}
    response = make_client(ScriptedLLM([])).post("/chat", json={"message": "hi"}, headers=headers)
    assert response.status_code == 401


def test_chat_runs_tools_and_returns_trace(make_client, alice):
    llm = ScriptedLLM([LLMResponse("", [ToolCall("get_accounts", {})]), LLMResponse("Done.")])
    client = make_client(llm)
    response = client.post(
        "/chat", json={"message": "my accounts?"}, headers=login(client, alice.customer_number)
    )
    body = response.json()
    assert response.status_code == 200
    assert body["reply"] == "Done."
    assert body["truncated"] is False
    assert body["trace"][0]["name"] == "get_accounts"


def test_conversation_history_carries_over(make_client, alice):
    llm = ScriptedLLM([LLMResponse("First."), LLMResponse("Second.")])
    client = make_client(llm)
    headers = login(client, alice.customer_number)
    first = client.post("/chat", json={"message": "one"}, headers=headers).json()
    client.post(
        "/chat",
        json={"message": "two", "conversation_id": first["conversation_id"]},
        headers=headers,
    )
    contents = [m["content"] for m in llm.requests[1][1:]]
    assert contents == ["one", "First.", "two"]


def test_conversations_are_isolated_between_customers(make_client, alice, bob):
    llm = ScriptedLLM([LLMResponse("For Alice."), LLMResponse("For Bob.")])
    client = make_client(llm)
    first = client.post(
        "/chat", json={"message": "secret"}, headers=login(client, alice.customer_number)
    ).json()
    client.post(
        "/chat",
        json={"message": "hi", "conversation_id": first["conversation_id"]},
        headers=login(client, bob.customer_number),
    )
    bob_request = llm.requests[1]
    assert [m["content"] for m in bob_request[1:]] == ["hi"]
    assert bob.customer_number in bob_request[0]["content"]


def test_model_outage_returns_503(make_client, alice):
    client = make_client(FailingLLM())
    response = client.post(
        "/chat", json={"message": "hi"}, headers=login(client, alice.customer_number)
    )
    assert response.status_code == 503


def test_empty_message_rejected(make_client, alice):
    client = make_client(ScriptedLLM([]))
    response = client.post(
        "/chat", json={"message": ""}, headers=login(client, alice.customer_number)
    )
    assert response.status_code == 422
