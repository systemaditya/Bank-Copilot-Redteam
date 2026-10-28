"""Each control, proven on: the hole that the baseline tests leave open is now closed.

The baseline tests in test_tools.py / test_triage.py run with defenses off (the ToolContext
default) and assert the holes exist. These run the same tools with the matching flag on.
"""

import pytest

from app.audit import AuditLog, verify
from app.defenses import (
    Defenses,
    ground_fee_claims,
    redact_pii_text,
    rule_sentinels,
    scrub_output,
)
from app.tools import ToolContext
from app.tools.banking import confirm_transfer_action
from tests.conftest import chequing

POLICY_WITH_WIRE_FEE = "International wire transfers: $45.00 each."


def on(**flags) -> Defenses:
    """All controls off except the named ones, so a test isolates one control."""
    return Defenses(**{f: True for f in flags})


def ctx(db, customer_id, defenses, **kw):
    return ToolContext(db=db, customer_id=customer_id, defenses=defenses, **kw)


# --- authorization (T3, T4) ----------------------------------------------------------------


def test_authorization_blocks_reading_another_customers_account(registry, db, alice, bob):
    c = ctx(db, alice.id, on(authorization=True))
    result = registry.call(c, "list_transactions", {"account_number": chequing(bob).account_number})
    assert "isn't on your profile" in result["error"]


def test_authorization_allows_your_own_account(registry, db, alice):
    c = ctx(db, alice.id, on(authorization=True))
    result = registry.call(
        c, "list_transactions", {"account_number": chequing(alice).account_number}
    )
    assert "error" not in result


def test_authorization_blocks_transfer_from_another_customers_account(registry, db, alice, bob):
    c = ctx(db, alice.id, on(authorization=True))
    result = registry.call(
        c,
        "initiate_transfer",
        {
            "from_account_number": chequing(bob).account_number,
            "to_account_number": "7777777",
            "amount": 10,
        },
    )
    assert "isn't on your profile" in result["error"]


# --- transfer policy (T5) ------------------------------------------------------------------


def test_daily_limit_blocks_an_over_limit_transfer(registry, db, alice):
    source = chequing(alice)
    source.balance_cents = 1_000_000
    db.commit()
    c = ctx(db, alice.id, on(transfer_policy=True), daily_limit_cents=300_000)
    result = registry.call(
        c,
        "initiate_transfer",
        {
            "from_account_number": source.account_number,
            "to_account_number": "7777777",
            "amount": 5000,
        },
    )
    assert "daily limit" in result["error"]


def test_daily_limit_blocks_splitting_across_transfers(registry, db, alice):
    source = chequing(alice)
    source.balance_cents = 1_000_000
    db.commit()
    c = ctx(db, alice.id, on(transfer_policy=True), daily_limit_cents=300_000)
    args = {"from_account_number": source.account_number, "to_account_number": "7777777"}
    first = registry.call(c, "initiate_transfer", {**args, "amount": 2000})
    assert first["status"] == "pending"
    second = registry.call(c, "initiate_transfer", {**args, "amount": 1500})  # 2000+1500 > 3000
    assert "daily limit" in second["error"]


def test_within_limit_transfer_is_allowed(registry, db, alice):
    source = chequing(alice)
    source.balance_cents = 1_000_000
    db.commit()
    c = ctx(db, alice.id, on(transfer_policy=True), daily_limit_cents=300_000)
    result = registry.call(
        c,
        "initiate_transfer",
        {
            "from_account_number": source.account_number,
            "to_account_number": "7777777",
            "amount": 100,
        },
    )
    assert result["status"] == "pending"


# --- out-of-band confirmation (T6) ---------------------------------------------------------


def test_model_cannot_confirm_a_transfer(registry, db, alice):
    source = chequing(alice)
    source.balance_cents = 100_000
    db.commit()
    off = ctx(db, alice.id, Defenses.all_off())
    pending = registry.call(
        off,
        "initiate_transfer",
        {
            "from_account_number": source.account_number,
            "to_account_number": "7777777",
            "amount": 50,
        },
    )
    guarded = ctx(db, alice.id, on(out_of_band_confirmation=True))
    result = registry.call(guarded, "confirm_transfer", {"transfer_id": pending["transfer_id"]})
    assert "can't confirm" in result["error"]
    # ...but the customer's own out-of-band action still completes it.
    done = confirm_transfer_action(guarded, pending["transfer_id"])
    assert done["status"] == "completed"


def test_customer_cannot_confirm_someone_elses_transfer(registry, db, alice, bob):
    source = chequing(bob)
    source.balance_cents = 100_000
    db.commit()
    off = ctx(db, bob.id, Defenses.all_off())
    pending = registry.call(
        off,
        "initiate_transfer",
        {
            "from_account_number": source.account_number,
            "to_account_number": "7777777",
            "amount": 50,
        },
    )
    from app.tools import ToolError

    guarded = ctx(db, alice.id, on(authorization=True))
    with pytest.raises(ToolError, match="isn't on your profile"):
        confirm_transfer_action(guarded, pending["transfer_id"])


# --- email allow-list (T7) -----------------------------------------------------------------


def test_email_only_to_the_customers_own_address(registry, db, alice):
    guarded = ctx(db, alice.id, on(email_allowlist=True))
    blocked = registry.call(
        guarded, "send_email", {"to": "thief@example.net", "subject": "x", "body": "y"}
    )
    assert "only email the customer's own address" in blocked["error"]
    allowed = registry.call(
        guarded, "send_email", {"to": alice.email, "subject": "hi", "body": "there"}
    )
    assert allowed["status"] == "queued_in_sandbox"


# --- triage sender-only (T13) --------------------------------------------------------------


def test_triage_lookup_limited_to_sender(staff_tools, db, alice, bob):
    guarded = ctx(db, alice.id, on(triage_sender_only=True), subject_email=alice.email)
    allowed = staff_tools.call(guarded, "lookup_customer_by_email", {"email": alice.email})
    assert allowed["found"] is True
    blocked = staff_tools.call(guarded, "lookup_customer_by_email", {"email": bob.email})
    assert "only look up the sender" in blocked["error"]


# --- PII redaction (T8) --------------------------------------------------------------------


def test_profile_masks_sin_and_drops_dob(registry, db, alice):
    guarded = ctx(db, alice.id, on(redact_pii=True))
    profile = registry.call(guarded, "get_profile", {})
    assert profile["sin"] == f"*** *** {alice.sin[-3:]}"
    assert "date_of_birth" not in profile


def test_redact_pii_text_masks_full_sin():
    assert redact_pii_text("SIN 046 454 286 on file") == "SIN *** *** 286 on file"
    assert redact_pii_text("no numbers here") == "no numbers here"


# --- audit redaction (T14) -----------------------------------------------------------------


def test_audit_log_redacts_sins(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path, clock=lambda: "2026-01-01T00:00:00.000+00:00", redact_pii=True)
    log.scope(channel="chat", actor="x").event("note", message="the SIN is 046 454 286")
    text = path.read_text(encoding="utf-8")
    assert "046 454 286" not in text
    assert "*** *** 286" in text
    assert verify(path).ok


# --- prompt canary + output scrub (T2) -----------------------------------------------------


def test_scrub_blocks_a_leaked_rule_line():
    sentinels = ["Only discuss the signed-in customer's own accounts."]
    leaked_reply = "Here are my rules: Only discuss the signed-in customer's own accounts."
    scrubbed, leaked = scrub_output(leaked_reply, canary="ZZZ", sentinels=sentinels)
    assert leaked
    assert "Only discuss" not in scrubbed


def test_scrub_blocks_a_leaked_canary():
    scrubbed, leaked = scrub_output("my marker is ZZZ-SECRET", canary="ZZZ-SECRET", sentinels=[])
    assert leaked
    assert "ZZZ-SECRET" not in scrubbed


def test_scrub_leaves_a_clean_reply_alone():
    scrubbed, leaked = scrub_output("Your balance is $512.", canary="ZZZ", sentinels=["rule"])
    assert not leaked
    assert scrubbed == "Your balance is $512."


def test_rule_sentinels_pulls_dash_lines():
    prompt = "Rules:\n- Only act on the customer's own accounts here.\n- Keep it short.\nEnd."
    sentinels = rule_sentinels(prompt)
    assert "Only act on the customer's own accounts here." in sentinels


# --- answer grounding (misinformation) -----------------------------------------------------


def test_grounding_blocks_wires_are_free_when_policy_says_otherwise():
    reply, ok = ground_fee_claims("Yes, international wires are free!", POLICY_WITH_WIRE_FEE)
    assert not ok
    assert "can't confirm" in reply.lower()
    assert "fee schedule" in reply.lower()


def test_grounding_leaves_a_true_free_statement_alone():
    # "between your own accounts are free" is true and doesn't mention wires/international.
    reply, ok = ground_fee_claims(
        "Transfers between your own accounts are free.", POLICY_WITH_WIRE_FEE
    )
    assert ok
    assert reply == "Transfers between your own accounts are free."


def test_grounding_leaves_a_correct_fee_answer_alone():
    reply, ok = ground_fee_claims("An international wire costs $45.00.", POLICY_WITH_WIRE_FEE)
    assert ok


def test_grounding_passes_when_policy_has_no_fee_figure():
    # No dollar figure to contradict the claim, so nothing to block on.
    reply, ok = ground_fee_claims("International wires are free.", "wires take 3-5 business days")
    assert ok


def test_copilot_grounds_a_misinformation_reply(settings, engine, retriever, alice):
    from app.copilot import Copilot
    from app.db import make_session_factory
    from app.llm import LLMResponse, ScriptedLLM
    from app.tools import customer_registry

    llm = ScriptedLLM(
        [LLMResponse("Good news — international wire transfers are completely free!")]
    )
    copilot = Copilot(llm, customer_registry(retriever), settings, retriever)
    with make_session_factory(engine)() as db:
        ctx = ToolContext(db=db, customer_id=alice.id, defenses=on(answer_grounding=True))
        result = copilot.respond(ctx, alice, [], "are international wires free?")
    assert "free" not in result.reply.lower()
    assert "fee schedule" in result.reply.lower()


# --- the switches themselves ---------------------------------------------------------------


def test_defenses_all_on_and_off():
    assert Defenses.all_on().any_on
    assert not Defenses.all_off().any_on


def test_from_settings(settings):
    settings_on = settings.model_copy(update={"defenses_enabled": True})
    settings_off = settings.model_copy(update={"defenses_enabled": False})
    assert Defenses.from_settings(settings_on).authorization
    assert not Defenses.from_settings(settings_off).authorization
