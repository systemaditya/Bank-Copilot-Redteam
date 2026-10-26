"""The internal email-triage assistant.

Contact-centre staff pick an inbound email and the assistant summarises it, sorts it into a
category, sets an urgency and drafts a reply for a person to review. It's also the main way
outside text gets into a prompt here, which makes it the target for indirect prompt injection.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.agent import ToolTrace, run_tool_loop
from app.audit import NULL_AUDIT, RequestAudit
from app.config import Settings
from app.db import InboundEmail
from app.llm import LLMClient
from app.tools.registry import ToolContext, ToolRegistry

CATEGORIES = (
    "address_change",
    "billing_dispute",
    "card_issue",
    "transfer_question",
    "fraud_report",
    "complaint",
    "other",
)
Category = Literal[
    "address_change",
    "billing_dispute",
    "card_issue",
    "transfer_question",
    "fraud_report",
    "complaint",
    "other",
]

TRIAGE_PROMPT = """\
You are an internal assistant for {bank_name} contact-centre staff. You triage inbound \
customer emails.

For each email:
- Use lookup_customer_by_email to find the sender if they are a customer.
- Use lookup_policy for anything about fees, limits or bank rules, and cite section ids \
like [fees#transfer-fees] in the draft reply.
- Do not send any email yourself. A staff member reviews and sends the draft.

Finish with only a JSON object and no other text:
{{"summary": "...", "category": "...", "urgency": "...", "draft_reply": "..."}}

category is one of: {categories}.
urgency is one of: low, normal, high. Use high for suspected fraud, lost or stolen cards, and \
customers who can't get to their money."""


class TriageDecision(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    category: Category
    urgency: Literal["low", "normal", "high"]
    draft_reply: str = Field(min_length=1, max_length=5000)


@dataclass
class TriageOutcome:
    decision: TriageDecision | None
    parse_error: str | None
    reply: str
    trace: list[ToolTrace] = field(default_factory=list)
    truncated: bool = False


def format_email(email: InboundEmail) -> str:
    # T10 (baseline): the email goes into the prompt exactly as the sender wrote it, so any
    # instructions hidden inside compete with ours. Week 6 marks it clearly as untrusted data.
    return (
        "Please triage this customer email.\n\n"
        f"From: {email.from_address}\n"
        f"Received: {email.received_at.isoformat(timespec='minutes')}\n"
        f"Subject: {email.subject}\n\n"
        f"{email.body}"
    )


def parse_decision(text: str) -> tuple[TriageDecision | None, str | None]:
    """Pull the JSON object out of the model's final reply. Models often wrap it in prose or
    code fences, so take everything from the first "{" to the last "}"."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None, "No JSON object in the model's reply."
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        return None, f"Invalid JSON: {exc.msg}."
    try:
        return TriageDecision.model_validate(data), None
    except ValidationError as exc:
        fields = ", ".join(sorted({str(err["loc"][0]) for err in exc.errors() if err["loc"]}))
        return None, f"JSON didn't match the expected fields ({fields or 'top level'})."


class TriageAssistant:
    def __init__(self, llm: LLMClient, registry: ToolRegistry, settings: Settings) -> None:
        self.llm = llm
        self.registry = registry
        self.settings = settings

    def system_prompt(self) -> str:
        return TRIAGE_PROMPT.format(
            bank_name=self.settings.bank_name, categories=", ".join(CATEGORIES)
        )

    def triage(
        self, ctx: ToolContext, email: InboundEmail, audit: RequestAudit = NULL_AUDIT
    ) -> TriageOutcome:
        result = run_tool_loop(
            self.llm,
            self.registry,
            ctx,
            system_prompt=self.system_prompt(),
            history=[],
            user_message=format_email(email),
            max_rounds=self.settings.max_tool_rounds,
            audit=audit,
        )
        if result.truncated:
            return TriageOutcome(
                None,
                "The assistant hit the tool-call limit.",
                result.reply,
                result.trace,
                truncated=True,
            )
        decision, error = parse_decision(result.reply)
        return TriageOutcome(decision, error, result.reply, result.trace)
