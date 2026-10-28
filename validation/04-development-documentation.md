# 04 — Development documentation

E-23 (Principle 3.3) wants the build written down: architecture, assumptions, limitations, and
an explainability approach suited to the model's impact. The engineering detail lives in
[../docs/architecture.md](../docs/architecture.md); this is the governance-facing summary.

## Architecture

Two assistants share one model-and-tools loop (`app/agent.py`):

- **Customer chat** (`app/copilot.py`): answers account, fee and policy questions, sets up
  transfers. Tools: accounts, profile, transactions, initiate/confirm transfer, send email,
  policy search.
- **Email triage** (`app/triage.py`): turns an inbound email into a summary, category, urgency
  and a draft reply, returned as a strict JSON object a person reviews. Tools: look up the
  sender, policy search, send email.

Retrieval (`app/rag/`) chunks the policy docs by section, embeds them, and returns sections with
citation ids so a policy claim can be traced. The data layer (`app/db.py`) runs on SQLite or
PostgreSQL; money is stored as integer cents in BIGINT columns.

## The controls (`app/defenses.py`)

Each control is a switch so it can be tested alone and measured.

| Control | Kind | What it enforces |
|---|---|---|
| authorization | deterministic | a tool only touches the signed-in customer's own accounts |
| transfer_policy | deterministic | the daily limit, including split transfers |
| out_of_band_confirmation | deterministic | the model can't send a transfer; the customer confirms via the API |
| email_allowlist | deterministic | email only to the customer's own address |
| triage_sender_only | deterministic | triage lookups limited to the email's sender |
| redact_pii | data | SIN masked, date of birth dropped in tool results |
| mark_untrusted | prompt | inbound email fenced and labelled as data |
| prompt_canary | prompt + output | a canary and an output scrub that blocks instruction leaks |

The split matters: the deterministic controls hold regardless of what the model does, because
they're plain code between the model and the database. The prompt/data controls lower risk but
can't be relied on alone, and the review grades them separately.

## Assumptions

- The attacker may be a signed-in customer or someone who controls a customer's mailbox.
- Authentication is out of scope for the lab (no passwords); the controls assume the caller is
  already who the session says they are.
- The base model is third-party and may change under us; hence version is a re-validation trigger.

## Limitations

- Non-deterministic output; the same input can vary run to run.
- A small lab model (`llama3.2:3b`); a production build would use a larger one.
- The prompt/data controls are heuristic. The canary scrub catches verbatim leaks, not
  paraphrased ones.
- No migrations yet (tables are created from the schema); Alembic is future work.

## Explainability approach

Impact is high but the model makes no credit-style decision, so the explainability need is
"show your work", not "explain a score". The design meets that with the tool-call **trace**
(every action the model took, with inputs and outputs), policy **citations** (answers point to a
section id), and the **audit log** (a hash-chained record of each request). A reviewer can
reconstruct what happened without interpreting model internals.
