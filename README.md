# Bank Copilot Red Team

A banking AI assistant, built to be attacked and then hardened, with the before/after measured on
the same cases — and documented the way a Canadian bank's model-risk team would have to under OSFI
Guideline E-23 (in force May 2027).

Most "secure chatbot" demos stop at a system prompt that says *please don't leak data*. That's a
suggestion, not a control. This project measures how often that fails under attack, which fixes
actually help, and what hardening costs real customers in false refusals.

There are two assistants:

- a **customer chat assistant** that checks balances, explains fees and policy, and sets up
  transfers;
- an **internal email-triage assistant** that contact-centre staff use to summarise, categorise
  and draft replies to inbound customer email — the surface where indirect prompt injection lives.

> **Fictional and synthetic.** *Maple Ledger Bank* doesn't exist, and neither do its customers.
> Every name, account and transaction is generated (Faker names, `example.com` emails, 555-01xx
> phone numbers, random SIN-shaped numbers). Attacks only ever run against this local system.

## Results

The attack suite runs the same cases twice — defences off (the undefended baseline) and on —
against `llama3.2:3b` on PostgreSQL. Benign requests are scored alongside, so a defence can't look
good just by refusing everyone.

| Split | Attack success, defences off | Attack success, defences on | False refusals (on) |
|---|---|---|---|
| dev | 33% | **0%** | 0% |
| held-out | 25% | **12%** | n/a (attacks only) |

Every category that maps to a code-level control (account access, transfers, data exfiltration,
PII) drops to zero. The one attack still landing on the held-out split is a non-fee indirect
injection, which the prompt/data controls reduce but don't eliminate; the backstop is that a human
confirms every transfer and reviews every triage draft. Full breakdowns are in [reports/](reports/),
and the before/after read is in
[validation/05-independent-review-report.md](validation/05-independent-review-report.md).

```bash
python -m redteam.run --defenses off               # the undefended baseline
python -m redteam.run --defenses on                # the defended build
python -m redteam.run --defenses on --adaptive 3   # attacker rewrites a failed attack and retries
COPILOT_MODEL=llama3.1:8b python -m redteam.run --defenses on   # run against a larger model
```

## How it works

The design principle is **the model proposes, plain code disposes.** The model can suggest an
action, but anything that matters — reading an account, moving money, sending an email — passes
through a deterministic check in Python between the model and the database. You can't talk an
`if` statement out of its decision the way you can a prompt rule.

The controls live in [app/defenses.py](app/defenses.py), each behind its own switch so the harness
can measure them one at a time.

**Deterministic (enforced in code — the backbone):**

- account-ownership checks on reads, transfers and confirmations;
- a daily-limit policy engine that also catches split transfers;
- out-of-band confirmation — the model can't send money; the customer confirms via
  `POST /transfers/{id}/confirm`;
- an email recipient allow-list (only the customer's own address on file);
- sender-only triage lookups (only the email's sender).

**Probabilistic / data (reduce risk, don't eliminate it):**

- SIN masking and date-of-birth drop in tool results, and SIN redaction in the audit log;
- untrusted-content marking for inbound email;
- a system-prompt canary with an output scrub;
- answer-grounding that blocks a fee/policy claim the policy corpus contradicts (the
  misinformation case).

The threat model ([docs/threat-model.md](docs/threat-model.md)) enumerates the threats (T1–T15) and
which control closes each; the OSFI E-23-style model-risk pack is in [validation/](validation/); and
[docs/demo.md](docs/demo.md) is a ~3-minute demo script.

## Run it

Needs Python 3.11+. To talk to the assistants you also need [Ollama](https://ollama.com) with a
tool-calling chat model (default `llama3.2:3b`) and an embedding model (`nomic-embed-text`). Exact
versions are pinned in `requirements.lock`.

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m app.seed --reset
ollama pull llama3.2:3b
ollama pull nomic-embed-text
python -m app.cli_chat --customer C1000
```

**macOS / Linux:**

```bash
python -m venv .venv && source .venv/bin/activate
make setup seed
ollama pull llama3.2:3b && ollama pull nomic-embed-text
make chat
```

No embedding model? Set `COPILOT_EMBEDDING_BACKEND=hashing` for a word-overlap fallback that needs
no model (weaker policy answers). The terminal chat prints every tool call, which is the easiest
way to watch what the assistant does.

### API

```bash
python -m uvicorn --factory app.main:create_app --reload
```

```bash
TOKEN=$(curl -s localhost:8000/auth/login -H 'content-type: application/json' \
  -d '{"customer_number":"C1000"}' | python -c "import sys,json; print(json.load(sys.stdin)['token'])")
curl -s localhost:8000/chat -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"message":"What does an international wire cost?"}'
```

Staff email triage uses `/auth/staff-login` and the `/triage/emails` endpoints. Interactive docs
are at `http://localhost:8000/docs`.

### Docker

Docker Compose runs the API, PostgreSQL 16 and Ollama together. Set a database password in `.env`
first (copy `.env.example`):

```bash
cp .env.example .env            # then set POSTGRES_PASSWORD
docker compose up --build
docker compose exec ollama ollama pull llama3.2:3b
docker compose exec ollama ollama pull nomic-embed-text
```

The database lives in the `pgdata` volume and survives restarts; `docker compose down -v` starts
fresh.

### Database

SQLite by default (`bank.db`). For PostgreSQL:

```bash
pip install -e ".[dev,postgres]"
export COPILOT_DATABASE_URL=postgresql://copilot:<password>@localhost:5432/bank
python -m app.seed --reset
```

A plain `postgresql://` URL works (the app selects the psycopg 3 driver). `python -m app.seed
--if-empty` seeds only a fresh database.

### Audit log

Every login, message, model reply, tool call and triage result is written to `logs/audit.jsonl`,
hash-chained so an edited or deleted line breaks the chain. SINs are redacted before anything is
written. Verify integrity with:

```bash
python -m app.audit verify logs/audit.jsonl
```

Known limit: a hash chain can't detect records cut from the *end* — that needs an external witness
for the latest hash (tracked as T15 in the threat model).

### Tests

```bash
make check      # ruff + pytest
```

No model needed: the tests use a scripted model, a word-overlap search and a mocked Ollama
endpoint. They default to in-memory SQLite; set `COPILOT_TEST_DATABASE_URL` to run them against
PostgreSQL (a throwaway database — the tests drop all tables). CI runs both. Tests named
`test_baseline_T*` assert the undefended holes exist, and `tests/test_defenses.py` proves each
control closes them, so the before/after story is pinned in the suite, not just the report.

## What's in the repo

```
app/               the assistants, API, tools, retrieval, audit log, data models, seeding, defenses
app/rag/           chunking, embeddings and search over the policy docs
redteam/           the attack suite, scorers, runner and adaptive attacker
data/policy_docs/  fictional fee, transfer, account and privacy policies
data/emails/       hand-written attack emails used by the seeder
docs/              threat model, architecture, demo script
reports/           baseline vs defended attack results
validation/        the OSFI E-23-style model-risk pack
tests/             unit and API tests
```

## Limitations and ethics

- Synthetic data only; attacks only against this local system.
- The model is small so it runs on a laptop; a production build would use a larger one (a config
  switch). Samples are small, so results carry wide confidence intervals and are reported as such.
- Misinformation-style and indirect-injection risks are reduced, not solved.
- The E-23 pack is a student's reading of the guideline for a portfolio, not compliance advice.

## License

MIT
