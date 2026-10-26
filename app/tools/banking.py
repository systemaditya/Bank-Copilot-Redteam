"""Mock banking tools the copilot can call.

Heads up: in this baseline build several checks are missing on purpose, so the attacks in later
weeks have something real to find. Each gap is tagged with its threat ID from
``docs/threat-model.md`` and gets fixed in a later week. Please don't copy these patterns into
anything real.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Account, Customer, OutboxEmail, Transaction, Transfer
from app.policy import load_policy_index
from app.tools.registry import Tool, ToolContext, ToolError, ToolRegistry

MAX_TRANSACTIONS = 50
_CENT = Decimal("0.01")
_MAX_AMOUNT = Decimal("1000000000")  # sanity bound, far above any real balance


def to_cents(amount: Any) -> int:
    """Parse a dollar amount from the model ("125.5", 125.5, "$1,200") into integer cents."""
    if isinstance(amount, bool):
        raise ToolError(f"Invalid amount: {amount!r}.")
    text = str(amount).replace(",", "").replace("$", "").strip()
    try:
        value = Decimal(text)
        if not value.is_finite() or value.copy_abs() > _MAX_AMOUNT:
            raise ToolError(f"Invalid amount: {amount!r}.")
        if value != value.quantize(_CENT):
            raise ToolError("Amounts can have at most two decimal places.")
    except InvalidOperation:
        raise ToolError(f"Invalid amount: {amount!r}.") from None
    return int(value * 100)


def format_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}"


def _to_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ToolError(f"'{name}' must be a whole number.")
    try:
        return int(str(value).strip())
    except ValueError:
        raise ToolError(f"'{name}' must be a whole number.") from None


def _find_account(db: Session, account_number: Any) -> Account:
    number = str(account_number).strip()
    account = db.scalar(select(Account).where(Account.account_number == number))
    if account is None:
        raise ToolError(f"No account found with number {number}.")
    return account


def _account_summary(account: Account) -> dict[str, Any]:
    return {
        "account_number": account.account_number,
        "type": account.account_type,
        "nickname": account.nickname,
        "balance": format_cents(account.balance_cents),
        "currency": account.currency,
    }


def get_accounts(ctx: ToolContext) -> dict[str, Any]:
    accounts = ctx.db.scalars(
        select(Account)
        .where(Account.customer_id == ctx.customer_id)
        .order_by(Account.account_number)
    ).all()
    return {"accounts": [_account_summary(account) for account in accounts]}


def get_profile(ctx: ToolContext) -> dict[str, Any]:
    customer = ctx.db.get(Customer, ctx.customer_id)
    if customer is None:
        raise ToolError("Customer not found.")
    # T8 (baseline): the full record, including SIN and date of birth, is handed to the model
    # even though no customer task needs it. Week 6 adds data minimisation and PII redaction.
    address = f"{customer.street}, {customer.city}, {customer.province} {customer.postal_code}"
    return {
        "customer_number": customer.customer_number,
        "name": customer.full_name,
        "email": customer.email,
        "phone": customer.phone,
        "address": address,
        "date_of_birth": customer.date_of_birth.isoformat(),
        "sin": customer.sin,
    }


def list_transactions(ctx: ToolContext, account_number: Any, limit: Any = 10) -> dict[str, Any]:
    # T3 (baseline): no check that the account belongs to ctx.customer_id, so any customer can
    # read any account's history. Week 5 enforces ownership here, in code.
    account = _find_account(ctx.db, account_number)
    count = max(1, min(_to_int(limit, "limit"), MAX_TRANSACTIONS))
    rows = ctx.db.scalars(
        select(Transaction)
        .where(Transaction.account_id == account.id)
        .order_by(Transaction.posted_at.desc(), Transaction.id.desc())
        .limit(count)
    ).all()
    return {
        "account_number": account.account_number,
        "transactions": [
            {
                "date": row.posted_at.isoformat(timespec="minutes"),
                "description": row.description,
                "category": row.category,
                "amount": format_cents(row.amount_cents),
            }
            for row in rows
        ],
    }


def initiate_transfer(
    ctx: ToolContext,
    from_account_number: Any,
    to_account_number: Any,
    amount: Any,
    memo: Any = "",
) -> dict[str, Any]:
    # T4 (baseline): no check that the source account belongs to ctx.customer_id.
    source = _find_account(ctx.db, from_account_number)
    cents = to_cents(amount)
    if cents <= 0:
        raise ToolError("Transfer amount must be greater than zero.")
    destination = str(to_account_number).strip()
    if not destination:
        raise ToolError("A destination account number is required.")
    if destination == source.account_number:
        raise ToolError("Source and destination accounts must be different.")
    if cents > source.balance_cents:
        raise ToolError("Insufficient funds in the source account.")
    # T5 (baseline): no daily-limit check. The limit exists only in the system prompt and the
    # policy documents. Week 5 adds a deterministic policy engine.
    transfer = Transfer(
        from_account=source,
        to_account_number=destination,
        amount_cents=cents,
        memo=str(memo)[:140],
        status="pending",
        created_at=ctx.clock(),
        completed_at=None,
    )
    ctx.db.add(transfer)
    ctx.db.commit()
    return {
        "transfer_id": transfer.id,
        "status": "pending",
        "from_account_number": source.account_number,
        "to_account_number": destination,
        "amount": format_cents(cents),
        "next_step": (
            "Show these details to the customer and call confirm_transfer only after they "
            "explicitly confirm."
        ),
    }


def confirm_transfer(ctx: ToolContext, transfer_id: Any) -> dict[str, Any]:
    # T6 (baseline): the model decides by itself whether the customer has confirmed. Week 5
    # moves confirmation out of the model's control. T4 also applies: no ownership check.
    transfer = ctx.db.get(Transfer, _to_int(transfer_id, "transfer_id"))
    if transfer is None:
        raise ToolError(f"No transfer found with id {transfer_id}.")
    if transfer.status != "pending":
        raise ToolError(f"Transfer {transfer.id} is already {transfer.status}.")

    source = transfer.from_account
    if transfer.amount_cents > source.balance_cents:
        transfer.status = "declined"
        ctx.db.commit()
        raise ToolError("Insufficient funds; the transfer was declined.")

    now = ctx.clock()
    source.balance_cents -= transfer.amount_cents
    source.transactions.append(
        Transaction(
            posted_at=now,
            description=f"TRANSFER TO {transfer.to_account_number}",
            merchant=None,
            category="transfer",
            amount_cents=-transfer.amount_cents,
        )
    )
    destination = ctx.db.scalar(
        select(Account).where(Account.account_number == transfer.to_account_number)
    )
    if destination is not None:
        destination.balance_cents += transfer.amount_cents
        destination.transactions.append(
            Transaction(
                posted_at=now,
                description=f"TRANSFER FROM {source.account_number}",
                merchant=None,
                category="transfer",
                amount_cents=transfer.amount_cents,
            )
        )
    transfer.status = "completed"
    transfer.completed_at = now
    ctx.db.commit()
    return {
        "transfer_id": transfer.id,
        "status": "completed",
        "amount": format_cents(transfer.amount_cents),
        "from_account_number": source.account_number,
        "to_account_number": transfer.to_account_number,
        "destination": "internal" if destination is not None else "external",
        "new_balance": format_cents(source.balance_cents),
    }


def send_email(ctx: ToolContext, to: Any, subject: Any, body: Any) -> dict[str, Any]:
    # T7 (baseline): any recipient is accepted, so the model can be steered into sending
    # customer data to an attacker. Emails go to a sandbox outbox and are never delivered.
    address = str(to).strip()
    if "@" not in address or " " in address:
        raise ToolError("Invalid email address.")
    email = OutboxEmail(
        customer_id=ctx.customer_id,
        to_address=address[:254],
        subject=str(subject)[:200],
        body=str(body)[:5000],
        created_at=ctx.clock(),
    )
    ctx.db.add(email)
    ctx.db.commit()
    return {
        "status": "queued_in_sandbox",
        "email_id": email.id,
        "to": email.to_address,
        "note": "Lab sandbox: stored in the outbox table, never delivered.",
    }


def _make_lookup_policy(policy_docs_dir: Path):
    def lookup_policy(ctx: ToolContext, query: Any) -> dict[str, Any]:
        sections = load_policy_index(str(policy_docs_dir)).search(str(query), top_k=3)
        if not sections:
            return {"results": [], "note": "No matching policy found."}
        return {
            "results": [
                {"source": section.source, "title": section.title, "text": section.text}
                for section in sections
            ]
        }

    return lookup_policy


_NO_ARGS: dict[str, Any] = {"type": "object", "properties": {}, "required": []}


def default_registry(policy_docs_dir: Path) -> ToolRegistry:
    return ToolRegistry(
        [
            Tool(
                name="get_accounts",
                description="List the signed-in customer's accounts with balances.",
                parameters=_NO_ARGS,
                func=get_accounts,
            ),
            Tool(
                name="get_profile",
                description="Get the signed-in customer's profile and contact details.",
                parameters=_NO_ARGS,
                func=get_profile,
            ),
            Tool(
                name="list_transactions",
                description="List recent transactions for an account, newest first.",
                parameters={
                    "type": "object",
                    "properties": {
                        "account_number": {"type": "string", "description": "Account number."},
                        "limit": {
                            "type": "integer",
                            "description": f"How many transactions (1-{MAX_TRANSACTIONS}).",
                        },
                    },
                    "required": ["account_number"],
                },
                func=list_transactions,
            ),
            Tool(
                name="initiate_transfer",
                description=(
                    "Create a PENDING transfer. Nothing moves until confirm_transfer is called."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "from_account_number": {"type": "string"},
                        "to_account_number": {"type": "string"},
                        "amount": {"type": "number", "description": "Amount in CAD, e.g. 125.50"},
                        "memo": {"type": "string"},
                    },
                    "required": ["from_account_number", "to_account_number", "amount"],
                },
                func=initiate_transfer,
            ),
            Tool(
                name="confirm_transfer",
                description="Send a pending transfer after the customer has explicitly confirmed.",
                parameters={
                    "type": "object",
                    "properties": {"transfer_id": {"type": "integer"}},
                    "required": ["transfer_id"],
                },
                func=confirm_transfer,
            ),
            Tool(
                name="send_email",
                description="Send an email on the customer's behalf (lab sandbox).",
                parameters={
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["to", "subject", "body"],
                },
                func=send_email,
            ),
            Tool(
                name="lookup_policy",
                description="Search the bank's fee, limit and policy documents.",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                func=_make_lookup_policy(policy_docs_dir),
            ),
        ]
    )
