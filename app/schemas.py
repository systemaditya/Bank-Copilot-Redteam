"""Request and response models for the HTTP API."""

from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    customer_number: str = Field(min_length=1, max_length=16)


class LoginResponse(BaseModel):
    token: str
    customer_number: str
    name: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    conversation_id: str | None = Field(default=None, max_length=64)


class ToolTraceOut(BaseModel):
    name: str
    arguments: Any
    result: dict[str, Any]


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    truncated: bool
    trace: list[ToolTraceOut] | None = None
