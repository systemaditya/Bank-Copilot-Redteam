"""The model <-> tool loop that both assistants share."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from app.audit import NULL_AUDIT, RequestAudit
from app.llm import LLMClient
from app.tools.registry import ToolContext, ToolRegistry

FALLBACK_REPLY = "Sorry, I couldn't complete that request. Please try again or rephrase it."


@dataclass
class ToolTrace:
    name: str
    arguments: Any
    result: dict[str, Any]


@dataclass
class AgentResult:
    reply: str
    new_messages: list[dict[str, Any]]
    trace: list[ToolTrace] = field(default_factory=list)
    truncated: bool = False


def run_tool_loop(
    llm: LLMClient,
    registry: ToolRegistry,
    ctx: ToolContext,
    *,
    system_prompt: str,
    history: list[dict[str, Any]],
    user_message: str,
    max_rounds: int,
    audit: RequestAudit = NULL_AUDIT,
) -> AgentResult:
    """Run one user turn. ``history`` excludes the system prompt and isn't modified.

    Model errors (``LLMError``) are left for the caller to handle and audit.
    """
    user = {"role": "user", "content": user_message}
    messages = [{"role": "system", "content": system_prompt}, *history, user]
    new_messages: list[dict[str, Any]] = [user]
    trace: list[ToolTrace] = []
    tools = registry.schemas()

    for round_number in range(1, max_rounds + 1):
        started = time.perf_counter()
        response = llm.chat(messages, tools)
        audit.event(
            "model_response",
            round=round_number,
            latency_ms=round((time.perf_counter() - started) * 1000),
            content=response.content,
            tool_calls=[{"name": c.name, "arguments": c.arguments} for c in response.tool_calls],
        )

        assistant: dict[str, Any] = {"role": "assistant", "content": response.content}
        if response.tool_calls:
            assistant["tool_calls"] = [
                {"function": {"name": call.name, "arguments": call.arguments}}
                for call in response.tool_calls
            ]
        messages.append(assistant)
        new_messages.append(assistant)

        if not response.tool_calls:
            return AgentResult(response.content, new_messages, trace)

        for call in response.tool_calls:
            result = registry.call(ctx, call.name, call.arguments)
            audit.event(
                "tool_call",
                name=call.name,
                arguments=call.arguments,
                ok="error" not in result,
                result=result,
            )
            trace.append(ToolTrace(call.name, call.arguments, result))
            tool_message = {
                "role": "tool",
                "tool_name": call.name,
                "content": json.dumps(result, default=str),
            }
            messages.append(tool_message)
            new_messages.append(tool_message)

    audit.event("tool_loop_truncated", rounds=max_rounds)
    return AgentResult(FALLBACK_REPLY, new_messages, trace, truncated=True)
