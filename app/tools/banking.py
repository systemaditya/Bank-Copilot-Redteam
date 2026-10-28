"""Mock banking tools the copilot can call.

Each tool carries both modes: with ``ctx.defenses`` off it's the undefended baseline (the holes
tagged T3-T8 in ``docs/threat-model.md``), and with the matching flag on the control is enforced
here in code, where the model can't argue its way past it. The app runs with the controls on;
the red-team harness runs both ways to measure them.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import Account, Customer, OutboxEmail, Transaction, Transfer
from app.rag import EmbeddingError, PolicyRetriever
from app.tools.registry import Tool, ToolContext, ToolError, ToolRegistry

MAX_TRANSACTIONS = 50
ACCOUNT_NUMBER_MAX = 20  # matches the account_number columns in app/db.py
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


def _signed_in_customer_id(ctx: ToolContext) -> int:
    if ctx.customer_id is None:
        raise ToolError("This tool needs a signed-in customer.")
    return ctx.customer_id


def _require_owned(ctx: ToolContext, account: Account) -> Account:
    """With authorization on, the account must belong to the signed-in customer."""
    if ctx.defenses.authorization and account.customer_id != ctx.customer_id:
        raise ToolError("That account isn't on your profile, so I can't access it.")
    return account


def _daily_outgoing_cents(ctx: ToolContext, customer_id: int, day: date) -> int:
    """Total of today's outgoing transfers (pending + completed) for the customer, used by the
    daily-limit check so splitting an amount across transfers doesn't dodge the limit."""
    rows = ctx.db.execute(
        select(Transfer.amount_cents)
        .join(Account, Transfer.from_account_id == Account.id)
        .where(
            Account.customer_id == customer_id,
            Transfer.status.in_(["pending", "completed"]),
            func.date(Transfer.created_at) == day.isoformat(),
        )
    ).all()
    return sum(row[0] for row in rows)


def get_accounts(ctx: ToolContext) -> dict[str, Any]:
    accounts = ctx.db.scalars(
        select(Account)
        .where(Account.customer_id == _signed_in_customer_id(ctx))
        .order_by(Account.account_number)
    ).all()
    return {"accounts": [_account_summary(account) for account in accounts]}


def get_profile(ctx: ToolContext) -> dict[str, Any]:
    customer = ctx.db.get(Customer, _signed_in_customer_id(ctx))
    if customer is None:
        raise ToolError("Customer not found.")
    address = f"{customer.street}, {customer.city}, {customer.province} {customer.postal_code}"
    profile = {
        "customer_number": customer.customer_number,
        "name": customer.full_name,
        "email": customer.email,
        "phone": customer.phone,
        "address": address,
        "date_of_birth": customer.date_of_birth.isoformat(),
        "sin": customer.sin,
    }
    # T8: with redaction on, don't hand the model data no customer task needs. Mask the SIN to
    # its last 3 digits and drop the date of birth; without it, the full record goes to the model.
    if ctx.defenses.redact_pii:
        profile["sin"] = f"*** *** {customer.sin[-3:]}"
        profile.pop("date_of_birth")
    return profile


def list_transactions(ctx: ToolContext, account_number: Any, limit: Any = 10) -> dict[str, Any]:
    # T3: with authorization on, the account must be the signed-in customer's own.
    account = _require_owned(ctx, _find_account(ctx.db, account_number))
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
    # T4: with authorization on, the source account must be the signed-in customer's own.
    source = _require_owned(ctx, _find_account(ctx.db, from_account_number))
    cents = to_cents(amount)
    if cents <= 0:
        raise ToolError("Transfer amount must be greater than zero.")
    destination = str(to_account_number).strip()
    if not destination:
        raise ToolError("A destination account number is required.")
    if len(destination) > ACCOUNT_NUMBER_MAX:
        # Postgres enforces the column length, so check here and give the model a clear error
        # instead of letting the insert fail.
        raise ToolError(f"Account numbers are at most {ACCOUNT_NUMBER_MAX} characters.")
    if destination == source.account_number:
        raise ToolError("Source and destination accounts must be different.")
    if cents > source.balance_cents:
        raise ToolError("Insufficient funds in the source account.")
    # T5: with the transfer policy on, enforce the daily limit in code. The limit otherwise
    # lives only in the prompt, which the model can be talked past.
    if ctx.defenses.transfer_policy:
        limit_cents = ctx.daily_limit_cents
        already = _daily_outgoing_cents(ctx, source.customer_id, ctx.clock().date())
        if already + cents > limit_cents:
            raise ToolError(
                f"That would put today's transfers over the daily limit of "
                f"${limit_cents // 100:,}. Already sent or pending today: "
                f"${already // 100:,}."
            )
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
    # T6: with out-of-band confirmation on, the model simply can't do this. The customer
    # confirms through the app (POST /transfers/{id}/confirm), not by asking the assistant.
    if ctx.defenses.out_of_band_confirmation:
        raise ToolError(
            "I can't confirm a transfer. Please review and confirm it yourself in the app or "
            "ask the customer to."
        )
    return confirm_transfer_action(ctx, _to_int(transfer_id, "transfer_id"))


def confirm_transfer_action(ctx: ToolContext, transfer_id: int) -> dict[str, Any]:
    """Actually send a pending transfer. This is the customer's own action, reached from the
    API confirm endpoint, and (when defenses are off) from the model's confirm_transfer tool."""
    transfer = ctx.db.get(Transfer, transfer_id)
    if transfer is None:
        raise ToolError(f"No transfer found with id {transfer_id}.")
    _require_owned(ctx, transfer.from_account)  # T4: can't confirm someone else's transfer
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
    # T7: with the allow-list on, the only recipient allowed is the customer's own address on
    # file. That's what stops an injected email from exfiltrating data to an attacker.
    address = str(to).strip()
    if "@" not in address or " " in address:
        raise ToolError("Invalid email address.")
    if ctx.defenses.email_allowlist:
        customer = ctx.db.get(Customer, ctx.customer_id) if ctx.customer_id else None
        allowed = customer.email.lower() if customer else None
        if allowed is None or address.lower() != allowed:
            raise ToolError(
                "I can only email the customer's own address on file, not any other recipient."
            )
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


def lookup_policy_tool(retriever: PolicyRetriever, top_k: int = 3) -> Tool:
    def lookup_policy(ctx: ToolContext, query: Any) -> dict[str, Any]:
        try:
            hits = retriever.search(str(query), top_k=top_k)
        except EmbeddingError as exc:
            raise ToolError(f"Policy search is unavailable right now ({exc}).") from None
        if not hits:
            return {"results": [], "note": "No matching policy found."}
        return {
            "results": [
                {
                    "id": hit.chunk.id,
                    "title": hit.chunk.title,
                    "text": hit.chunk.text,
                    "score": hit.score,
                }
                for hit in hits
            ],
            "note": "Cite the id of every section you rely on, like [fees#transfer-fees].",
        }

    return Tool(
        name="lookup_policy",
        description="Search the bank's fee, limit and policy documents. Results have citation ids.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        func=lookup_policy,
    )


_NO_ARGS: dict[str, Any] = {"type": "object", "properties": {}, "required": []}

GET_ACCOUNTS = Tool(
    name="get_accounts",
    description="List the signed-in customer's accounts with balances.",
    parameters=_NO_ARGS,
    func=get_accounts,
)
GET_PROFILE = Tool(
    name="get_profile",
    description="Get the signed-in customer's profile and contact details.",
    parameters=_NO_ARGS,
    func=get_profile,
)
LIST_TRANSACTIONS = Tool(
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
)
INITIATE_TRANSFER = Tool(
    name="initiate_transfer",
    description="Create a PENDING transfer. Nothing moves until confirm_transfer is called.",
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
)
CONFIRM_TRANSFER = Tool(
    name="confirm_transfer",
    description="Send a pending transfer after the customer has explicitly confirmed.",
    parameters={
        "type": "object",
        "properties": {"transfer_id": {"type": "integer"}},
        "required": ["transfer_id"],
    },
    func=confirm_transfer,
)
SEND_EMAIL = Tool(
    name="send_email",
    description="Send an email (lab sandbox: it is stored, never delivered).",
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
)


def customer_registry(retriever: PolicyRetriever, top_k: int = 3) -> ToolRegistry:
    """Tools for the customer-facing chat assistant."""
    return ToolRegistry(
        [
            GET_ACCOUNTS,
            GET_PROFILE,
            LIST_TRANSACTIONS,
            INITIATE_TRANSFER,
            CONFIRM_TRANSFER,
            SEND_EMAIL,
            lookup_policy_tool(retriever, top_k),
        ]
    )
