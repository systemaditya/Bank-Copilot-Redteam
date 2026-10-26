"""HTTP API. Run with: ``uvicorn --factory app.main:create_app --reload``."""

# No ``from __future__ import annotations`` here: FastAPI must evaluate the endpoint
# annotations at definition time, because the dependency aliases are local to create_app.
import uuid
from collections.abc import Iterator
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app import __version__
from app.agent import ToolTrace
from app.audit import NULL_AUDIT, RequestAudit, make_audit_log
from app.auth import Principal, SessionStore
from app.config import Settings, get_settings
from app.copilot import Copilot
from app.db import Customer, InboundEmail, Staff, init_db, make_engine, make_session_factory
from app.llm import LLMClient, LLMError, make_llm
from app.rag import make_retriever
from app.schemas import (
    ChatRequest,
    ChatResponse,
    EmailDetail,
    EmailSummary,
    LoginRequest,
    LoginResponse,
    StaffLoginRequest,
    StaffLoginResponse,
    ToolTraceOut,
    TriageResponse,
)
from app.tools import ToolContext, customer_registry, staff_registry
from app.tools.registry import utcnow
from app.triage import TriageAssistant


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLMClient | None = None,
    engine: Engine | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    engine = engine or make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    llm = llm or make_llm(settings)
    retriever = make_retriever(settings)
    copilot = Copilot(llm, customer_registry(retriever, settings.rag_top_k), settings)
    triage_assistant = TriageAssistant(llm, staff_registry(retriever, settings.rag_top_k), settings)
    audit_log = make_audit_log(settings.audit_enabled, settings.audit_log_path)
    sessions = SessionStore()
    # In-memory chat history, keyed by (customer id, conversation id) so one customer can't
    # continue another customer's conversation. Lost on restart, which is fine for the lab.
    conversations: dict[tuple[int, str], list[dict[str, Any]]] = {}

    app = FastAPI(title=f"{settings.bank_name} Copilot (red-team lab)", version=__version__)

    def audit_for(channel: str, actor: str) -> RequestAudit:
        return audit_log.scope(channel=channel, actor=actor) if audit_log else NULL_AUDIT

    def trace_out(trace: list[ToolTrace]) -> list[ToolTraceOut] | None:
        if not settings.return_trace:
            return None
        return [ToolTraceOut(name=t.name, arguments=t.arguments, result=t.result) for t in trace]

    def get_db() -> Iterator[Session]:
        with session_factory() as db:
            yield db

    DbSession = Annotated[Session, Depends(get_db)]

    def principal_from(authorization: str | None, wanted: Literal["customer", "staff"]):
        scheme, _, token = (authorization or "").partition(" ")
        principal: Principal | None = None
        if scheme.lower() == "bearer" and token:
            principal = sessions.resolve(token.strip())
        if principal is None:
            audit_for("auth", "anonymous").event("auth_failed", reason="missing or bad token")
            raise HTTPException(status_code=401, detail="Missing or invalid bearer token.")
        if principal.kind != wanted:
            audit_for("auth", principal.actor).event(
                "auth_failed", reason=f"{principal.kind} token used on a {wanted} endpoint"
            )
            raise HTTPException(status_code=403, detail=f"This endpoint is for {wanted} only.")
        return principal

    def current_customer(
        db: DbSession, authorization: Annotated[str | None, Header()] = None
    ) -> Customer:
        customer = db.get(Customer, principal_from(authorization, "customer").id)
        if customer is None:
            raise HTTPException(status_code=401, detail="Invalid or expired session.")
        return customer

    def current_staff(
        db: DbSession, authorization: Annotated[str | None, Header()] = None
    ) -> Staff:
        staff = db.get(Staff, principal_from(authorization, "staff").id)
        if staff is None:
            raise HTTPException(status_code=401, detail="Invalid or expired session.")
        return staff

    CurrentCustomer = Annotated[Customer, Depends(current_customer)]
    CurrentStaff = Annotated[Staff, Depends(current_staff)]

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "model": settings.model, "audit": audit_log is not None}

    @app.post("/auth/login", response_model=LoginResponse)
    def login(request: LoginRequest, db: DbSession) -> LoginResponse:
        number = request.customer_number.strip()
        customer = db.scalar(select(Customer).where(Customer.customer_number == number))
        if customer is None:
            raise HTTPException(status_code=404, detail="Unknown customer number.")
        audit_for("auth", f"customer:{number}").event("login")
        return LoginResponse(
            token=sessions.create(Principal("customer", customer.id, customer.customer_number)),
            customer_number=customer.customer_number,
            name=customer.full_name,
        )

    @app.post("/auth/staff-login", response_model=StaffLoginResponse)
    def staff_login(request: StaffLoginRequest, db: DbSession) -> StaffLoginResponse:
        number = request.staff_number.strip()
        staff = db.scalar(select(Staff).where(Staff.staff_number == number))
        if staff is None:
            raise HTTPException(status_code=404, detail="Unknown staff number.")
        audit_for("auth", f"staff:{number}").event("login")
        return StaffLoginResponse(
            token=sessions.create(Principal("staff", staff.id, staff.staff_number)),
            staff_number=staff.staff_number,
            name=staff.full_name,
        )

    @app.post("/chat", response_model=ChatResponse)
    def chat(request: ChatRequest, customer: CurrentCustomer, db: DbSession) -> ChatResponse:
        conversation_id = request.conversation_id or uuid.uuid4().hex
        key = (customer.id, conversation_id)
        history = conversations.get(key, [])
        actor = f"customer:{customer.customer_number}"
        audit = audit_for("chat", actor)
        audit.event("request_received", conversation_id=conversation_id, message=request.message)

        ctx = ToolContext(db=db, customer_id=customer.id, actor=actor)
        try:
            result = copilot.respond(ctx, customer, history, request.message, audit=audit)
        except LLMError as exc:
            audit.event("model_error", error=str(exc))
            raise HTTPException(status_code=503, detail=f"Model unavailable: {exc}") from exc
        conversations[key] = history + result.new_messages
        audit.event("response_sent", reply=result.reply, truncated=result.truncated)

        return ChatResponse(
            conversation_id=conversation_id,
            reply=result.reply,
            truncated=result.truncated,
            trace=trace_out(result.trace),
        )

    @app.get("/triage/emails", response_model=list[EmailSummary])
    def list_emails(staff: CurrentStaff, db: DbSession, status: str | None = None):
        query = select(InboundEmail).order_by(InboundEmail.received_at)
        if status:
            query = query.where(InboundEmail.status == status)
        return [EmailSummary.model_validate(email) for email in db.scalars(query)]

    @app.get("/triage/emails/{email_id}", response_model=EmailDetail)
    def get_email(email_id: int, staff: CurrentStaff, db: DbSession) -> EmailDetail:
        email = db.get(InboundEmail, email_id)
        if email is None:
            raise HTTPException(status_code=404, detail="No such email.")
        return EmailDetail.model_validate(email)

    @app.post("/triage/emails/{email_id}/run", response_model=TriageResponse)
    def run_triage(email_id: int, staff: CurrentStaff, db: DbSession) -> TriageResponse:
        email = db.get(InboundEmail, email_id)
        if email is None:
            raise HTTPException(status_code=404, detail="No such email.")
        actor = f"staff:{staff.staff_number}"
        audit = audit_for("triage", actor)
        audit.event("triage_started", email_id=email.id)

        ctx = ToolContext(db=db, customer_id=email.customer_id, actor=actor)
        try:
            outcome = triage_assistant.triage(ctx, email, audit=audit)
        except LLMError as exc:
            audit.event("model_error", error=str(exc))
            raise HTTPException(status_code=503, detail=f"Model unavailable: {exc}") from exc

        decision = outcome.decision
        email.status = "triaged" if decision else "needs_review"
        email.triage_category = decision.category if decision else None
        email.triage_urgency = decision.urgency if decision else None
        email.triage_summary = decision.summary if decision else None
        email.draft_reply = decision.draft_reply if decision else None
        email.triage_error = outcome.parse_error
        email.triaged_by = staff.staff_number
        email.triaged_at = utcnow()
        db.commit()
        audit.event(
            "triage_finished",
            email_id=email.id,
            status=email.status,
            category=email.triage_category,
            urgency=email.triage_urgency,
            parse_error=outcome.parse_error,
        )

        return TriageResponse(
            email_id=email.id,
            status=email.status,
            decision=decision,
            parse_error=outcome.parse_error,
            reply=outcome.reply,
            truncated=outcome.truncated,
            trace=trace_out(outcome.trace),
        )

    return app
