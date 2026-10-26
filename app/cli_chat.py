"""Chat with the copilot in the terminal, without starting the HTTP server.

    python -m app.cli_chat --customer C1000

Tool calls are printed as they happen, which makes manual red-teaming easy to follow.
"""

from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app.config import get_settings
from app.copilot import Copilot
from app.db import Customer, make_engine, make_session_factory
from app.llm import LLMError, make_llm
from app.tools import ToolContext, default_registry


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Terminal chat with the bank copilot.")
    parser.add_argument("--customer", default="C1000", help="Customer number to sign in as.")
    args = parser.parse_args(argv)

    settings = get_settings()
    session_factory = make_session_factory(make_engine(settings.database_url))
    copilot = Copilot(make_llm(settings), default_registry(settings.policy_docs_dir), settings)

    with session_factory() as db:
        customer = db.scalar(select(Customer).where(Customer.customer_number == args.customer))
        if customer is None:
            parser.error(f"No customer {args.customer}. Did you run `python -m app.seed --reset`?")
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
            ctx = ToolContext(db=db, customer_id=customer.id)
            try:
                result = copilot.respond(ctx, customer, history, message)
            except LLMError as exc:
                print(f"[error] {exc}")
                continue
            history.extend(result.new_messages)
            for step in result.trace:
                print(
                    f"  [tool] {step.name}({json.dumps(step.arguments)}) -> "
                    f"{json.dumps(step.result, default=str)[:300]}"
                )
            print(f"copilot> {result.reply}")


if __name__ == "__main__":
    main()
