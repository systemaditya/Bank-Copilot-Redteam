import pytest
from sqlalchemy import select

from app.db import OutboxEmail, Transfer
from app.tools import ToolContext, ToolError
from app.tools.banking import format_cents, to_cents
from tests.conftest import chequing


def call(registry, ctx, name, **arguments):
    return registry.call(ctx, name, arguments)


# --- money parsing -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "cents"),
    [("125.50", 12550), (125.5, 12550), ("$1,200", 120000), (3, 300), ("0.01", 1)],
)
def test_to_cents_parses_common_formats(raw, cents):
    assert to_cents(raw) == cents


@pytest.mark.parametrize("raw", ["abc", "1.234", "NaN", "Infinity", True, "1e12", ""])
def test_to_cents_rejects_bad_amounts(raw):
    with pytest.raises(ToolError):
        to_cents(raw)


def test_format_cents():
    assert format_cents(12550) == "125.50"
    assert format_cents(-5) == "-0.05"


# --- read tools ----------------------------------------------------------------------------


def test_get_accounts_returns_only_own_accounts(registry, alice_ctx, alice):
    result = call(registry, alice_ctx, "get_accounts")
    numbers = {a["account_number"] for a in result["accounts"]}
    assert numbers == {a.account_number for a in alice.accounts}


def test_list_transactions_newest_first_and_limited(registry, alice_ctx, alice):
    result = call(
        registry,
        alice_ctx,
        "list_transactions",
        account_number=chequing(alice).account_number,
        limit=5,
    )
    dates = [t["date"] for t in result["transactions"]]
    assert len(dates) == 5
    assert dates == sorted(dates, reverse=True)


def test_list_transactions_clamps_limit(registry, alice_ctx, alice):
    result = call(
        registry,
        alice_ctx,
        "list_transactions",
        account_number=chequing(alice).account_number,
        limit=10_000,
    )
    assert len(result["transactions"]) <= 50


def test_unknown_account_is_an_error(registry, alice_ctx):
    result = call(registry, alice_ctx, "list_transactions", account_number="999")
    assert "No account found" in result["error"]


def test_lookup_policy_returns_citable_sections(registry, alice_ctx):
    result = call(registry, alice_ctx, "lookup_policy", query="wire transfer fees")
    top = result["results"][0]
    assert top["id"] == "fees#transfer-fees"
    assert "$45.00" in top["text"]
    assert "Cite the id" in result["note"]


def test_lookup_policy_reports_backend_outage(alice_ctx):
    from app.rag import EmbeddingError, PolicyRetriever, load_chunks
    from app.tools import customer_registry
    from tests.conftest import POLICY_DOCS

    class DownEmbedder:
        name = "down"

        def embed(self, texts):
            raise EmbeddingError("connection refused")

    registry = customer_registry(PolicyRetriever(load_chunks(POLICY_DOCS), DownEmbedder()))
    result = call(registry, alice_ctx, "lookup_policy", query="fees")
    assert "unavailable" in result["error"]


def test_customer_tools_need_a_signed_in_customer(registry, db):
    ctx = ToolContext(db=db, customer_id=None, actor="staff:S100")
    assert "signed-in customer" in call(registry, ctx, "get_accounts")["error"]
    assert "signed-in customer" in call(registry, ctx, "get_profile")["error"]


# --- transfers -----------------------------------------------------------------------------


def test_initiate_creates_pending_transfer_without_moving_money(registry, alice_ctx, alice, bob):
    source = chequing(alice)
    before = source.balance_cents
    result = call(
        registry,
        alice_ctx,
        "initiate_transfer",
        from_account_number=source.account_number,
        to_account_number=chequing(bob).account_number,
        amount="1.00",
    )
    assert result["status"] == "pending"
    assert source.balance_cents == before


def test_confirm_moves_money_between_internal_accounts(registry, alice_ctx, db, alice, bob):
    source, dest = chequing(alice), chequing(bob)
    source.balance_cents = 100_000
    db.commit()
    dest_before = dest.balance_cents

    pending = call(
        registry,
        alice_ctx,
        "initiate_transfer",
        from_account_number=source.account_number,
        to_account_number=dest.account_number,
        amount=250,
    )
    done = call(registry, alice_ctx, "confirm_transfer", transfer_id=pending["transfer_id"])

    assert done["status"] == "completed"
    assert done["destination"] == "internal"
    assert source.balance_cents == 75_000
    assert dest.balance_cents == dest_before + 25_000
    assert source.transactions[-1].amount_cents == -25_000
    assert dest.transactions[-1].amount_cents == 25_000


def test_confirm_twice_is_rejected(registry, alice_ctx, db, alice):
    source = chequing(alice)
    source.balance_cents = 10_000
    db.commit()
    pending = call(
        registry,
        alice_ctx,
        "initiate_transfer",
        from_account_number=source.account_number,
        to_account_number="7777777",
        amount=10,
    )
    call(registry, alice_ctx, "confirm_transfer", transfer_id=pending["transfer_id"])
    again = call(registry, alice_ctx, "confirm_transfer", transfer_id=pending["transfer_id"])
    assert "already completed" in again["error"]


def test_confirm_declines_when_funds_ran_out(registry, alice_ctx, db, alice):
    source = chequing(alice)
    source.balance_cents = 10_000
    db.commit()
    pending = call(
        registry,
        alice_ctx,
        "initiate_transfer",
        from_account_number=source.account_number,
        to_account_number="7777777",
        amount=80,
    )
    source.balance_cents = 1_000
    db.commit()
    result = call(registry, alice_ctx, "confirm_transfer", transfer_id=pending["transfer_id"])
    assert "declined" in result["error"]
    assert db.get(Transfer, pending["transfer_id"]).status == "declined"


@pytest.mark.parametrize(
    ("amount", "message"),
    [(0, "greater than zero"), (-5, "greater than zero"), ("10.001", "two decimal places")],
)
def test_initiate_rejects_bad_amounts(registry, alice_ctx, alice, amount, message):
    result = call(
        registry,
        alice_ctx,
        "initiate_transfer",
        from_account_number=chequing(alice).account_number,
        to_account_number="7777777",
        amount=amount,
    )
    assert message in result["error"]


def test_initiate_rejects_insufficient_funds(registry, alice_ctx, db, alice):
    source = chequing(alice)
    source.balance_cents = 500
    db.commit()
    result = call(
        registry,
        alice_ctx,
        "initiate_transfer",
        from_account_number=source.account_number,
        to_account_number="7777777",
        amount=6,
    )
    assert "Insufficient funds" in result["error"]


def test_initiate_rejects_same_account(registry, alice_ctx, alice):
    number = chequing(alice).account_number
    result = call(
        registry,
        alice_ctx,
        "initiate_transfer",
        from_account_number=number,
        to_account_number=number,
        amount=1,
    )
    assert "must be different" in result["error"]


# --- email sandbox -------------------------------------------------------------------------


def test_send_email_only_writes_to_sandbox_outbox(registry, alice_ctx, db, alice):
    result = call(
        registry, alice_ctx, "send_email", to="someone@example.com", subject="Hi", body="Test"
    )
    assert result["status"] == "queued_in_sandbox"
    stored = db.scalars(select(OutboxEmail)).one()
    assert stored.to_address == "someone@example.com"
    assert stored.customer_id == alice.id


def test_send_email_rejects_invalid_address(registry, alice_ctx):
    result = call(registry, alice_ctx, "send_email", to="not an email", subject="x", body="y")
    assert "Invalid email" in result["error"]


# --- registry dispatch ---------------------------------------------------------------------


def test_registry_rejects_unknown_tool(registry, alice_ctx):
    assert "Unknown tool" in registry.call(alice_ctx, "drop_tables", {})["error"]


def test_registry_rejects_missing_and_unexpected_arguments(registry, alice_ctx):
    result = registry.call(alice_ctx, "list_transactions", {"acct": "1"})
    assert "missing account_number" in result["error"]
    assert "unexpected acct" in result["error"]


def test_registry_rejects_non_object_arguments(registry, alice_ctx):
    assert "JSON object" in registry.call(alice_ctx, "get_accounts", "{bad json")["error"]


def test_schemas_cover_every_tool(registry):
    names = {schema["function"]["name"] for schema in registry.schemas()}
    assert (
        names
        == set(registry.names)
        == {
            "get_accounts",
            "get_profile",
            "list_transactions",
            "initiate_transfer",
            "confirm_transfer",
            "send_email",
            "lookup_policy",
        }
    )


# --- documented baseline weaknesses --------------------------------------------------------
# These tests pin down the gaps the red team will attack (see docs/threat-model.md). When a
# later week adds the matching control, flip the assertion so the test proves the fix.


def test_baseline_T3_any_customer_can_read_another_customers_transactions(registry, alice_ctx, bob):
    result = call(
        registry, alice_ctx, "list_transactions", account_number=chequing(bob).account_number
    )
    assert "error" not in result and result["transactions"]


def test_baseline_T4_transfer_from_another_customers_account(registry, alice_ctx, db, bob):
    victim = chequing(bob)
    victim.balance_cents = 10_000
    db.commit()
    result = call(
        registry,
        alice_ctx,
        "initiate_transfer",
        from_account_number=victim.account_number,
        to_account_number="7777777",
        amount=50,
    )
    assert result["status"] == "pending"


def test_baseline_T5_daily_limit_is_not_enforced_in_code(registry, alice_ctx, db, alice):
    source = chequing(alice)
    source.balance_cents = 1_000_000
    db.commit()
    result = call(
        registry,
        alice_ctx,
        "initiate_transfer",
        from_account_number=source.account_number,
        to_account_number="7777777",
        amount=5000,
    )
    assert result["status"] == "pending"


def test_baseline_T8_profile_exposes_full_sin_to_the_model(registry, alice_ctx, alice):
    assert call(registry, alice_ctx, "get_profile")["sin"] == alice.sin


def test_tool_context_clock_is_injectable(registry, db, alice):
    from datetime import datetime

    fixed = datetime(2026, 1, 2, 3, 4)
    ctx = ToolContext(db=db, customer_id=alice.id, clock=lambda: fixed)
    call(registry, ctx, "send_email", to="a@example.com", subject="s", body="b")
    assert db.scalars(select(OutboxEmail)).one().created_at == fixed
