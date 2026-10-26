"""API tests for staff login, email triage and the audit trail."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.audit import verify
from app.db import InboundEmail
from app.llm import LLMResponse, ScriptedLLM, ToolCall
from app.main import create_app

VALID = {
    "summary": "Customer asks about the daily limit.",
    "category": "transfer_question",
    "urgency": "normal",
    "draft_reply": "Hi, the daily limit is $3,000.00 [transfers#daily-transfer-limits].",
}


@pytest.fixture
def make_client(settings, engine):
    def _make(llm, **overrides):
        return TestClient(create_app(settings.model_copy(update=overrides), llm=llm, engine=engine))

    return _make


def bearer(response):
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def staff_login(client, number="S100"):
    return bearer(client.post("/auth/staff-login", json={"staff_number": number}))


def customer_login(client, number):
    return bearer(client.post("/auth/login", json={"customer_number": number}))


def test_staff_login(make_client):
    client = make_client(ScriptedLLM([]))
    response = client.post("/auth/staff-login", json={"staff_number": "S100"})
    assert response.status_code == 200
    assert response.json()["staff_number"] == "S100"
    assert client.post("/auth/staff-login", json={"staff_number": "S999"}).status_code == 404


def test_tokens_only_work_on_their_own_side(make_client, alice):
    client = make_client(ScriptedLLM([]))
    as_customer = customer_login(client, alice.customer_number)
    as_staff = staff_login(client)
    assert client.get("/triage/emails", headers=as_customer).status_code == 403
    assert client.post("/chat", json={"message": "hi"}, headers=as_staff).status_code == 403


def test_list_and_filter_emails(make_client, db):
    client = make_client(ScriptedLLM([]))
    headers = staff_login(client)
    everything = client.get("/triage/emails", headers=headers).json()
    assert len(everything) == db.scalar(select(func.count()).select_from(InboundEmail))
    new_only = client.get("/triage/emails", params={"status": "new"}, headers=headers).json()
    assert {email["status"] for email in new_only} == {"new"}


def test_email_detail_hides_ground_truth_labels(make_client, benign_email):
    client = make_client(ScriptedLLM([]))
    headers = staff_login(client)
    detail = client.get(f"/triage/emails/{benign_email.id}", headers=headers).json()
    assert detail["body"] == benign_email.body
    assert "label" not in detail
    assert "expected_category" not in detail
    assert client.get("/triage/emails/99999", headers=headers).status_code == 404


def test_triage_run_saves_the_decision(make_client, benign_email):
    llm = ScriptedLLM(
        [
            LLMResponse("", [ToolCall("lookup_policy", {"query": "daily transfer limit"})]),
            LLMResponse(json.dumps(VALID)),
        ]
    )
    client = make_client(llm)
    headers = staff_login(client)
    result = client.post(f"/triage/emails/{benign_email.id}/run", headers=headers).json()
    assert result["status"] == "triaged"
    assert result["decision"]["category"] == "transfer_question"
    assert result["trace"][0]["name"] == "lookup_policy"

    detail = client.get(f"/triage/emails/{benign_email.id}", headers=headers).json()
    assert detail["status"] == "triaged"
    assert detail["triage_urgency"] == "normal"
    assert detail["triaged_by"] == "S100"


def test_unusable_triage_output_goes_to_review(make_client, benign_email):
    client = make_client(ScriptedLLM([LLMResponse("Looks like a transfer question to me.")]))
    headers = staff_login(client)
    result = client.post(f"/triage/emails/{benign_email.id}/run", headers=headers).json()
    assert result["status"] == "needs_review"
    assert result["decision"] is None
    assert "No JSON" in result["parse_error"]


def test_chat_writes_a_verifiable_audit_trail(make_client, alice, tmp_path):
    path = tmp_path / "audit.jsonl"
    llm = ScriptedLLM([LLMResponse("", [ToolCall("get_accounts", {})]), LLMResponse("Done.")])
    client = make_client(llm, audit_enabled=True, audit_log_path=path)
    headers = customer_login(client, alice.customer_number)
    client.post("/chat", json={"message": "my balances?"}, headers=headers)

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    chat_events = [r["event"] for r in records if r["channel"] == "chat"]
    assert chat_events == [
        "request_received",
        "model_response",
        "tool_call",
        "model_response",
        "response_sent",
    ]
    assert {r["actor"] for r in records if r["channel"] == "chat"} == {
        f"customer:{alice.customer_number}"
    }
    assert len({r["request_id"] for r in records if r["channel"] == "chat"}) == 1
    assert verify(path).ok


def test_failed_logins_are_audited(make_client, tmp_path):
    path = tmp_path / "audit.jsonl"
    client = make_client(ScriptedLLM([]), audit_enabled=True, audit_log_path=path)
    client.post("/chat", json={"message": "hi"}, headers={"Authorization": "Bearer nope"})
    record = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["event"] == "auth_failed"
    assert record["actor"] == "anonymous"


def test_wrong_side_token_is_audited_with_the_staff_number(make_client, tmp_path):
    path = tmp_path / "audit.jsonl"
    client = make_client(ScriptedLLM([]), audit_enabled=True, audit_log_path=path)
    client.post("/chat", json={"message": "hi"}, headers=staff_login(client))
    record = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["event"] == "auth_failed"
    assert record["actor"] == "staff:S100"
