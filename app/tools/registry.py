"""Tool plumbing: the schemas shown to the model and dispatch of model-requested calls."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite stores naive datetimes)."""
    return datetime.now(UTC).replace(tzinfo=None)


class ToolError(Exception):
    """A tool refused or failed in an expected way. The message is returned to the model."""


@dataclass
class ToolContext:
    """Per-request context, filled in from the login session and never from the model.

    ``customer_id`` is the signed-in customer, or for staff tools the customer the work is
    about (``None`` if unknown). ``actor`` says who is driving, e.g. ``staff:S100``.
    """

    db: Session
    customer_id: int | None
    actor: str = ""
    clock: Callable[[], datetime] = field(default=utcnow)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for the arguments object
    func: Callable[..., dict[str, Any]]


class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    def call(self, ctx: ToolContext, name: str, arguments: Any) -> dict[str, Any]:
        """Run one model-requested tool call. Never raises for bad model input."""
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"Unknown tool '{name}'."}
        if not isinstance(arguments, dict):
            return {"error": f"Arguments for '{name}' must be a JSON object."}

        properties = tool.parameters.get("properties", {})
        missing = [key for key in tool.parameters.get("required", []) if key not in arguments]
        unexpected = [key for key in arguments if key not in properties]
        if missing or unexpected:
            problems = []
            if missing:
                problems.append(f"missing {', '.join(missing)}")
            if unexpected:
                problems.append(f"unexpected {', '.join(unexpected)}")
            return {"error": f"Invalid arguments for '{name}': {'; '.join(problems)}."}

        try:
            return tool.func(ctx, **arguments)
        except ToolError as exc:
            return {"error": str(exc)}
