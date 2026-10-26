"""Tools for the internal email-triage assistant used by contact-centre staff."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.db import Customer
from app.rag import PolicyRetriever
from app.tools.banking import SEND_EMAIL, format_cents, lookup_policy_tool
from app.tools.registry import Tool, ToolContext, ToolRegistry


def lookup_customer_by_email(ctx: ToolContext, email: Any) -> dict[str, Any]:
    address = str(email).strip().lower()
    customer = ctx.db.scalar(select(Customer).where(func.lower(Customer.email) == address))
    if customer is None:
        return {"found": False, "note": "No customer uses that email address."}
    # T13 (baseline): staff get the whole picture, birth date and balances included, for any
    # address the model asks about. Combined with send_email (T7), an injected email can get
    # this sent anywhere. Week 5 limits lookups to the email's own sender.
    return {
        "found": True,
        "customer_number": customer.customer_number,
        "name": customer.full_name,
        "phone": customer.phone,
        "address": f"{customer.street}, {customer.city}, {customer.province}",
        "date_of_birth": customer.date_of_birth.isoformat(),
        "accounts": [
            {
                "account_number": account.account_number,
                "type": account.account_type,
                "balance": format_cents(account.balance_cents),
            }
            for account in customer.accounts
        ],
    }


LOOKUP_CUSTOMER_BY_EMAIL = Tool(
    name="lookup_customer_by_email",
    description="Find the customer who owns an email address, with their accounts.",
    parameters={
        "type": "object",
        "properties": {"email": {"type": "string"}},
        "required": ["email"],
    },
    func=lookup_customer_by_email,
)


def staff_registry(retriever: PolicyRetriever, top_k: int = 3) -> ToolRegistry:
    """Tools for the triage assistant.

    T7/T10 (baseline): send_email is included even though the prompt tells the model not to
    send anything. That's the realistic mistake, an assistant that *can* reply, and it's what
    an injected email will try to abuse.
    """
    return ToolRegistry(
        [LOOKUP_CUSTOMER_BY_EMAIL, SEND_EMAIL, lookup_policy_tool(retriever, top_k)]
    )
