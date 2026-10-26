"""Request and response models for the HTTP API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.triage import TriageDecision


class LoginRequest(BaseModel):
    customer_number: str = Field(min_length=1, max_length=16)


class LoginResponse(BaseModel):
    token: str
    customer_number: str
    name: str


class StaffLoginRequest(BaseModel):
    staff_number: str = Field(min_length=1, max_length=16)


class StaffLoginResponse(BaseModel):
    token: str
    staff_number: str
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


class EmailSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_address: str
    subject: str
    received_at: datetime
    status: str


class EmailDetail(EmailSummary):
    body: str
    triage_category: str | None
    triage_urgency: str | None
    triage_summary: str | None
    draft_reply: str | None
    triage_error: str | None
    triaged_by: str | None
    triaged_at: datetime | None


class TriageResponse(BaseModel):
    email_id: int
    status: str
    decision: TriageDecision | None
    parse_error: str | None
    reply: str
    truncated: bool
    trace: list[ToolTraceOut] | None = None
