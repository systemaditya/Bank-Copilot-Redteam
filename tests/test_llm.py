import json

import httpx
import pytest

from app.llm import LLMError, OllamaClient


def client_with(handler) -> OllamaClient:
    return OllamaClient("http://ollama.test", "test-model", transport=httpx.MockTransport(handler))


def test_sends_expected_payload_and_parses_tool_calls():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "get_accounts", "arguments": {}}},
                        {"function": {"name": "lookup_policy", "arguments": '{"query": "fees"}'}},
                        {"function": {"name": "lookup_policy", "arguments": "{not json"}},
                    ],
                }
            },
        )

    tools = [{"type": "function", "function": {"name": "get_accounts"}}]
    response = client_with(handler).chat([{"role": "user", "content": "hi"}], tools)

    path, payload = seen[0]
    assert path == "/api/chat"
    assert payload["model"] == "test-model"
    assert payload["stream"] is False
    assert payload["tools"] == tools
    assert payload["options"] == {"temperature": 0.0}
    assert [call.name for call in response.tool_calls] == [
        "get_accounts",
        "lookup_policy",
        "lookup_policy",
    ]
    assert response.tool_calls[1].arguments == {"query": "fees"}
    assert response.tool_calls[2].arguments == "{not json"  # left for the registry to reject


def test_omits_tools_when_none_given():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "hello"}})

    assert client_with(handler).chat([], []).content == "hello"
    assert "tools" not in seen[0]


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(500, text="boom"),
        lambda request: httpx.Response(200, text="not json"),
    ],
)
def test_bad_responses_raise_llm_error(handler):
    with pytest.raises(LLMError):
        client_with(handler).chat([], [])


def test_connection_error_raises_llm_error():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMError):
        client_with(handler).chat([], [])
