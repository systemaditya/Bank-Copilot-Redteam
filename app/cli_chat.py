"""Chat with the copilot in the terminal, without starting the HTTP server.

    python -m app.cli_chat --customer C1000

Tool calls are printed as they happen, which makes poking at it by hand easy to follow.
Everything is also written to the audit log, the same as through the API.
"""

from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app.audit import NULL_AUDIT, make_audit_log
from app.config import get_settings
from app.copilot import Copilot
from app.db import Customer, make_engine, make_session_factory
from app.llm import LLMError, make_llm
from app.rag import make_retriever
from app.tools import ToolContext, customer_registry


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Terminal chat with the bank copilot.")
    parser.add_argument("--customer", default="C1000", help="Customer number to sign in as.")
    args = parser.parse_args(argv)

    settings = get_settings()
    session_factory = make_session_factory(make_engine(settings.database_url))
    registry = customer_registry(make_retriever(settings), settings.rag_top_k)
    copilot = Copilot(make_llm(settings), registry, settings)
    audit_log = make_audit_log(settings.audit_enabled, settings.audit_log_path)

    with session_factory() as db:
        customer = db.scalar(select(Customer).where(Customer.customer_number == args.customer))
        if customer is None:
            parser.error(f"No customer {args.customer}. Did you run `python -m app.seed --reset`?")
        actor = f"customer:{customer.customer_number}"
        print(
            f"Signed in as {customer.full_name} ({customer.customer_number}). "
            f"Model: {settings.model}. Type 'exit' to quit."
        )

        history: list[dict] = []
        while True:
            try:
                message = input("\nyou> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if message.lower() in {"exit", "quit"}:
                break
            if not message:
                continue
            audit = audit_log.scope(channel="cli", actor=actor) if audit_log else NULL_AUDIT
            audit.event("request_received", message=message)
            ctx = ToolContext(db=db, customer_id=customer.id, actor=actor)
            try:
                result = copilot.respond(ctx, customer, history, message, audit=audit)
            except LLMError as exc:
                audit.event("model_error", error=str(exc))
                print(f"[error] {exc}")
                continue
            audit.event("response_sent", reply=result.reply, truncated=result.truncated)
            history.extend(result.new_messages)
            for step in result.trace:
                print(
                    f"  [tool] {step.name}({json.dumps(step.arguments)}) -> "
                    f"{json.dumps(step.result, default=str)[:300]}"
                )
            print(f"copilot> {result.reply}")


if __name__ == "__main__":
    main()
