"""Model clients. ``OllamaClient`` talks to a local Ollama server; ``ScriptedLLM`` replays
canned responses so tests and offline demos run without a model."""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.config import Settings


class LLMError(RuntimeError):
    """The model could not be reached or returned something unusable."""


@dataclass
class ToolCall:
    name: str
    arguments: Any  # normally a dict; left as-is when the model sends malformed JSON


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient(Protocol):
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse: ...


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        temperature: float = 0.0,
        timeout_s: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self._http = httpx.Client(base_url=base_url, timeout=timeout_s, transport=transport)

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        if tools:
            payload["tools"] = tools
        try:
            response = self._http.post("/api/chat", json=payload)
            response.raise_for_status()
            message = response.json().get("message") or {}
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc
        except ValueError as exc:
            raise LLMError("Ollama returned a non-JSON response.") from exc

        calls = []
        for raw in message.get("tool_calls") or []:
            function = raw.get("function") or {}
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                # On malformed JSON keep the raw string; the tool registry rejects it.
                with contextlib.suppress(json.JSONDecodeError):
                    arguments = json.loads(arguments)
            calls.append(ToolCall(name=function.get("name", ""), arguments=arguments))
        return LLMResponse(content=message.get("content") or "", tool_calls=calls)


class ScriptedLLM:
    """Returns pre-written responses in order and records every request it receives."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[list[dict[str, Any]]] = []

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        self.requests.append([dict(message) for message in messages])
        if not self._responses:
            raise LLMError("ScriptedLLM has no responses left.")
        return self._responses.pop(0)


def make_llm(settings: Settings) -> LLMClient:
    if settings.llm_backend == "ollama":
        return OllamaClient(
            settings.ollama_url,
            settings.model,
            temperature=settings.temperature,
            timeout_s=settings.request_timeout_s,
        )
    raise ValueError(f"Unknown llm_backend: {settings.llm_backend!r}")
