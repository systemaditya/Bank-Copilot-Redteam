import json

import pytest
from sqlalchemy import select

from app.db import Customer, InboundEmail
from app.llm import LLMResponse, ScriptedLLM, ToolCall
from app.tools import ToolContext
from app.triage import CATEGORIES, TriageAssistant, format_email, parse_decision

VALID = {
    "summary": "Customer asks what an international wire costs.",
    "category": "transfer_question",
    "urgency": "normal",
    "draft_reply": "Hi, an international wire costs $45.00 [fees#transfer-fees].",
}


def staff_ctx(db, email):
    return ToolContext(db=db, customer_id=email.customer_id, actor="staff:S100")


# --- parsing the model's final answer ------------------------------------------------------


def test_parses_plain_json():
    decision, error = parse_decision(json.dumps(VALID))
    assert error is None
    assert decision.category == "transfer_question"


def test_parses_json_wrapped_in_prose_and_code_fences():
    decision, error = parse_decision("Here you go:\n```json\n" + json.dumps(VALID) + "\n```")
    assert error is None
    assert decision.urgency == "normal"


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("Nothing structured here.", "No JSON"),
        ("{not json}", "Invalid JSON"),
        (json.dumps({**VALID, "category": "spam"}), "category"),
        (json.dumps({k: v for k, v in VALID.items() if k != "urgency"}), "urgency"),
    ],
)
def test_rejects_bad_output(text, fragment):
    decision, error = parse_decision(text)
    assert decision is None
    assert fragment in error


# --- the assistant -------------------------------------------------------------------------


def test_triage_looks_up_the_sender_and_returns_a_decision(settings, staff_tools, db, benign_email):
    llm = ScriptedLLM(
        [
            LLMResponse(
                "", [ToolCall("lookup_customer_by_email", {"email": benign_email.from_address})]
            ),
            LLMResponse(json.dumps(VALID)),
        ]
    )
    outcome = TriageAssistant(llm, staff_tools, settings).triage(
        staff_ctx(db, benign_email), benign_email
    )
    assert outcome.parse_error is None
    assert outcome.decision.category == "transfer_question"
    assert outcome.trace[0].result["found"] is True
    first_request = llm.requests[0]
    assert first_request[0]["role"] == "system"
    assert benign_email.subject in first_request[-1]["content"]


def test_unparseable_reply_is_flagged_for_review(settings, staff_tools, db, benign_email):
    llm = ScriptedLLM([LLMResponse("I think this is about fees.")])
    outcome = TriageAssistant(llm, staff_tools, settings).triage(
        staff_ctx(db, benign_email), benign_email
    )
    assert outcome.decision is None
    assert "No JSON" in outcome.parse_error


def test_tool_loop_limit_is_reported(settings, staff_tools, db, benign_email):
    looping = [LLMResponse("", [ToolCall("lookup_policy", {"query": "fees"})])]
    llm = ScriptedLLM(looping * settings.max_tool_rounds)
    outcome = TriageAssistant(llm, staff_tools, settings).triage(
        staff_ctx(db, benign_email), benign_email
    )
    assert outcome.truncated
    assert outcome.decision is None
    assert "tool-call limit" in outcome.parse_error


def test_system_prompt_lists_every_category(settings, staff_tools):
    prompt = TriageAssistant(ScriptedLLM([]), staff_tools, settings).system_prompt()
    for category in CATEGORIES:
        assert category in prompt


def test_staff_registry_has_the_triage_tools(staff_tools):
    assert set(staff_tools.names) == {"lookup_customer_by_email", "send_email", "lookup_policy"}


def test_lookup_customer_by_email_ignores_case_and_handles_unknown(staff_tools, db, alice):
    ctx = ToolContext(db=db, customer_id=None, actor="staff:S100")
    found = staff_tools.call(ctx, "lookup_customer_by_email", {"email": alice.email.upper()})
    assert found["customer_number"] == alice.customer_number
    missing = staff_tools.call(ctx, "lookup_customer_by_email", {"email": "who@example.com"})
    assert missing["found"] is False


# --- documented baseline weaknesses --------------------------------------------------------


def test_baseline_T10_email_text_goes_into_the_prompt_unmarked(db):
    attack = db.scalars(select(InboundEmail).where(InboundEmail.label == "injection")).first()
    prompt_text = format_email(attack)
    assert attack.body in prompt_text
    assert "untrusted" not in prompt_text.lower()


def test_baseline_T13_staff_lookup_returns_any_customers_details(staff_tools, db, benign_email):
    stranger = db.scalars(
        select(Customer).where(Customer.id != benign_email.customer_id).order_by(Customer.id)
    ).first()
    result = staff_tools.call(
        staff_ctx(db, benign_email), "lookup_customer_by_email", {"email": stranger.email}
    )
    assert result["date_of_birth"] == stranger.date_of_birth.isoformat()
    assert result["accounts"]
