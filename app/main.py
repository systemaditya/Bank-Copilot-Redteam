"""HTTP API. Run with: ``uvicorn --factory app.main:create_app --reload``."""

# No ``from __future__ import annotations`` here: FastAPI must evaluate the endpoint
# annotations at definition time, because DbSession/CurrentCustomer are local to create_app.
import uuid
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app import __version__
from app.auth import SessionStore
from app.config import Settings, get_settings
from app.copilot import Copilot
from app.db import Customer, init_db, make_engine, make_session_factory
from app.llm import LLMClient, LLMError, make_llm
from app.schemas import ChatRequest, ChatResponse, LoginRequest, LoginResponse, ToolTraceOut
from app.tools import ToolContext, default_registry


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
    copilot = Copilot(
        llm or make_llm(settings), default_registry(settings.policy_docs_dir), settings
    )
    sessions = SessionStore()
    # In-memory conversation history, keyed by (customer id, conversation id) so one customer
    # can't continue another customer's conversation. Lost on restart; fine for the lab.
    conversations: dict[tuple[int, str], list[dict[str, Any]]] = {}

    app = FastAPI(title=f"{settings.bank_name} Copilot (red-team lab)", version=__version__)

    def get_db() -> Iterator[Session]:
        with session_factory() as db:
            yield db

    DbSession = Annotated[Session, Depends(get_db)]

    def current_customer(
        db: DbSession, authorization: Annotated[str | None, Header()] = None
    ) -> Customer:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="Missing bearer token.")
        customer_id = sessions.resolve(token.strip())
        customer = db.get(Customer, customer_id) if customer_id is not None else None
        if customer is None:
            raise HTTPException(status_code=401, detail="Invalid or expired session.")
        return customer

    CurrentCustomer = Annotated[Customer, Depends(current_customer)]

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "model": settings.model}

    @app.post("/auth/login", response_model=LoginResponse)
    def login(request: LoginRequest, db: DbSession) -> LoginResponse:
        customer = db.scalar(
            select(Customer).where(Customer.customer_number == request.customer_number.strip())
        )
        if customer is None:
            raise HTTPException(status_code=404, detail="Unknown customer number.")
        return LoginResponse(
            token=sessions.create(customer.id),
            customer_number=customer.customer_number,
            name=customer.full_name,
        )

    @app.post("/chat", response_model=ChatResponse)
    def chat(request: ChatRequest, customer: CurrentCustomer, db: DbSession) -> ChatResponse:
        conversation_id = request.conversation_id or uuid.uuid4().hex
        key = (customer.id, conversation_id)
        history = conversations.get(key, [])
        ctx = ToolContext(db=db, customer_id=customer.id)
        try:
            result = copilot.respond(ctx, customer, history, request.message)
        except LLMError as exc:
            raise HTTPException(status_code=503, detail=f"Model unavailable: {exc}") from exc
        conversations[key] = history + result.new_messages

        trace = None
        if settings.return_trace:
            trace = [
                ToolTraceOut(name=t.name, arguments=t.arguments, result=t.result)
                for t in result.trace
            ]
        return ChatResponse(
            conversation_id=conversation_id,
            reply=result.reply,
            truncated=result.truncated,
            trace=trace,
        )

    return app
