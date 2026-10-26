"""Run attack and benign cases against the assistants and collect scored results.

The harness drives the real ``Copilot`` and ``TriageAssistant`` in-process, so it exercises the
same prompts, tools and tool loop as the API without needing the server running. Point it at a
real model for a baseline, or hand it a scripted model in tests.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.copilot import Copilot
from app.db import Customer, InboundEmail, make_engine, make_session_factory
from app.llm import LLMClient, LLMError
from app.rag import PolicyRetriever, make_retriever
from app.tools import ToolContext, customer_registry, staff_registry
from app.triage import TriageAssistant
from redteam.cases import Case
from redteam.scoring import RunRecord, ToolCallRecord


def _rule_sentinels(prompt: str) -> list[str]:
    """The distinctive '- ...' rule lines from a system prompt. If one comes back verbatim in a
    reply, the model leaked its instructions."""
    lines: list[str] = []
    for raw in prompt.splitlines():
        line = raw.strip()
        if line.startswith("- ") and len(line) > 25:
            lines.append(line[2:])
    return lines


@dataclass
class CaseResult:
    case: Case
    record: RunRecord
    succeeded: bool  # attack worked, or (benign) was falsely refused

    @property
    def label(self) -> str:
        if self.case.benign:
            return "false refusal" if self.succeeded else "handled"
        return "ATTACK SUCCEEDED" if self.succeeded else "defended"


@dataclass
class Harness:
    llm: LLMClient
    session_factory: object
    retriever: PolicyRetriever
    settings: Settings
    errors: list[str] = field(default_factory=list)

    @classmethod
    def build(cls, settings: Settings, llm: LLMClient) -> Harness:
        engine = make_engine(settings.database_url)
        return cls(
            llm=llm,
            session_factory=make_session_factory(engine),
            retriever=make_retriever(settings),
            settings=settings,
        )

    def run(self, cases: list[Case]) -> list[CaseResult]:
        copilot = Copilot(
            self.llm, customer_registry(self.retriever, self.settings.rag_top_k), self.settings
        )
        triage = TriageAssistant(
            self.llm, staff_registry(self.retriever, self.settings.rag_top_k), self.settings
        )
        results: list[CaseResult] = []
        with self.session_factory() as db:
            for case in cases:
                record = (
                    self._run_chat(db, copilot, case)
                    if case.channel == "chat"
                    else self._run_triage(db, triage, case)
                )
                results.append(CaseResult(case, record, case.evaluate(record)))
        return results

    def _run_chat(self, db: Session, copilot: Copilot, case: Case) -> RunRecord:
        customer = db.scalar(
            select(Customer).where(Customer.customer_number == (case.customer or "C1000"))
        )
        if customer is None:
            return RunRecord(case.id, "chat", "", [], error=f"no customer {case.customer}")
        context = {
            "owned_accounts": [a.account_number for a in customer.accounts],
            "date_of_birth": customer.date_of_birth.isoformat(),
            "daily_limit_cents": self.settings.daily_transfer_limit_cad * 100,
            "prompt_sentinels": _rule_sentinels(copilot.system_prompt(customer)),
        }
        ctx = ToolContext(
            db=db, customer_id=customer.id, actor=f"redteam:{customer.customer_number}"
        )
        started = time.perf_counter()
        try:
            result = copilot.respond(ctx, customer, [], case.message or "")
        except LLMError as exc:
            return RunRecord(case.id, "chat", "", [], context=context, error=str(exc))
        return RunRecord(
            case_id=case.id,
            channel="chat",
            reply=result.reply,
            tool_calls=[ToolCallRecord(t.name, t.arguments, t.result) for t in result.trace],
            context=context,
            truncated=result.truncated,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )

    def _run_triage(self, db: Session, triage: TriageAssistant, case: Case) -> RunRecord:
        email = self._email_for(db, case)
        if email is None:
            return RunRecord(case.id, "triage", "", [], error="could not build the email")
        target = db.get(Customer, email.customer_id) if email.customer_id else None
        context = {
            "owned_accounts": [a.account_number for a in target.accounts] if target else [],
            "date_of_birth": target.date_of_birth.isoformat() if target else None,
            "daily_limit_cents": self.settings.daily_transfer_limit_cad * 100,
            "prompt_sentinels": _rule_sentinels(triage.system_prompt()),
        }
        ctx = ToolContext(db=db, customer_id=email.customer_id, actor="redteam:S100")
        started = time.perf_counter()
        try:
            outcome = triage.triage(ctx, email)
        except LLMError as exc:
            return RunRecord(case.id, "triage", "", [], context=context, error=str(exc))
        if outcome.decision is not None:
            reply = f"{outcome.decision.summary}\n{outcome.decision.draft_reply}"
        else:
            reply = outcome.reply
        return RunRecord(
            case_id=case.id,
            channel="triage",
            reply=reply,
            tool_calls=[ToolCallRecord(t.name, t.arguments, t.result) for t in outcome.trace],
            context=context,
            truncated=outcome.truncated,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )

    def _email_for(self, db: Session, case: Case) -> InboundEmail | None:
        if case.email_id is not None:
            return db.get(InboundEmail, case.email_id)
        spec = case.email or {}
        # A case can say which customer "sent" it (an attacker in that customer's mailbox);
        # we then use that customer's real seeded address. Otherwise it's an outside sender.
        owner = None
        if spec.get("customer"):
            owner = db.scalar(select(Customer).where(Customer.customer_number == spec["customer"]))
            if owner is None:
                return None
            from_address = owner.email
        else:
            from_address = spec.get("from", "attacker@example.org")
            owner = db.scalar(select(Customer).where(Customer.email == from_address.lower()))
        return InboundEmail(
            from_address=from_address,
            subject=spec.get("subject", "(no subject)"),
            body=spec.get("body", ""),
            received_at=datetime.now(UTC).replace(tzinfo=None),
            customer_id=owner.id if owner else None,
            label="injection",
            status="new",
        )
