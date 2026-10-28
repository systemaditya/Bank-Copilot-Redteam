# Bank Copilot Red Team

I'm building a banking AI assistant so I can break it, fix it, and then write it up the way a
Canadian bank's model-risk team would have to under OSFI Guideline E-23 (in force May 2027).

Most "secure chatbot" demos stop at a system prompt that says *please don't leak data*. I wanted
to measure how often that actually fails, which fixes really help, and what it costs in
false refusals for normal customers.

There are two assistants:

- a **customer chat assistant** that checks balances, explains fees and sets up transfers, and
- an **internal email-triage assistant** that contact-centre staff use to summarise, sort and
  draft replies to customer emails. This one reads text written by strangers, so it's where
  indirect prompt injection shows up.

**Heads up:** Maple Ledger Bank doesn't exist, and neither do its customers. Every name, account
and transaction is generated (Faker names, `example.com` emails, 555-01xx phone numbers, random
SIN-shaped numbers). I only run attacks against my own local copy. The current build is insecure
on purpose. The weak spots are listed in [docs/threat-model.md](docs/threat-model.md).

## Where it's at

| Week | What | Done? |
|---|---|---|
| 1 | Threat model, architecture, repo setup, CI | Yes |
| 2 | Synthetic data, mock banking tools, a basic assistant with no defenses | Yes |
| 3 | Retrieval over policy docs with citations, the email-triage assistant, a tamper-evident audit log | Yes |
| 4 | Attack suite and baseline numbers | Yes |
| 5–6 | Defenses: hard rules in code first, then PII redaction and prompt handling | Yes |
| 7 | Adaptive attacks and a second, larger model | Not yet |
| 8 | Model-risk validation write-up and a demo video | Write-up done; video not yet |

The attack suite runs both ways on the same cases: defences off (the baseline) and on. See
[reports/](reports/) for the numbers, and [validation/05-independent-review-report.md](validation/05-independent-review-report.md)
for the before/after read. Re-run either with:

```bash
python -m redteam.run --defenses off     # the undefended baseline
python -m redteam.run --defenses on      # the defended build
```

The controls live in [app/defenses.py](app/defenses.py), each behind its own switch so they can
be measured one at a time: account-ownership checks, a daily-limit policy engine, out-of-band
transfer confirmation (the model can't send money; the customer confirms via
`POST /transfers/{id}/confirm`), an email recipient allow-list, sender-only triage lookups, SIN
and date-of-birth redaction (including in the audit log), untrusted-content marking for inbound
email, and a system-prompt canary with an output scrub. The deterministic ones hold regardless of
what the model does; the prompt/data ones lower risk without removing it, and the write-up grades
them separately. The whole model-risk pack (OSFI E-23 style) is in [validation/](validation/).

## Running it

You need Python 3.11 or newer. To actually talk to the assistants you also need
[Ollama](https://ollama.com) with a chat model that supports tool calling (I use
`llama3.1:8b`) and an embedding model for policy search (`nomic-embed-text`). The versions I
develop against are pinned in `requirements.lock`.

On Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m app.seed --reset
ollama pull llama3.1:8b
ollama pull nomic-embed-text
python -m app.cli_chat --customer C1000
```

On macOS or Linux:

```bash
python -m venv .venv && source .venv/bin/activate
make setup seed
ollama pull llama3.1:8b && ollama pull nomic-embed-text
make chat
```

No embedding model? Set `COPILOT_EMBEDDING_BACKEND=hashing` to use a simple word-overlap search
instead. It works, but it doesn't understand meaning, so expect worse policy answers.

The terminal chat prints every tool call the model makes, which is the easiest way to see what's
going on when you poke at it.

### Through the API

```bash
python -m uvicorn --factory app.main:create_app --reload
```

Customer chat:

```bash
TOKEN=$(curl -s localhost:8000/auth/login -H 'content-type: application/json' \
  -d '{"customer_number":"C1000"}' | python -c "import sys,json; print(json.load(sys.stdin)['token'])")
curl -s localhost:8000/chat -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"message":"What does an international wire cost?"}'
```

Email triage, as a staff member:

```bash
STAFF=$(curl -s localhost:8000/auth/staff-login -H 'content-type: application/json' \
  -d '{"staff_number":"S100"}' | python -c "import sys,json; print(json.load(sys.stdin)['token'])")
curl -s "localhost:8000/triage/emails?status=new" -H "authorization: Bearer $STAFF"
curl -s -X POST localhost:8000/triage/emails/1/run -H "authorization: Bearer $STAFF"
```

Replies come back with a `trace` of the tool calls behind them. I keep that on because the
attack scoring needs it; set `COPILOT_RETURN_TRACE=false` to turn it off. FastAPI's docs page is
at `http://localhost:8000/docs`.

### The audit log

Every login, failed login, message, model reply, tool call and triage result goes to
`logs/audit.jsonl`, one JSON record per line. Each record carries the hash of the one before it,
so editing or deleting a line in the middle breaks the chain:

```bash
python -m app.audit verify logs/audit.jsonl
```

Two honest caveats. The log holds full prompts, so it contains customer PII until redaction lands
in week 6. And a hash chain can't tell if someone cut records off the *end*; that needs the
latest hash stored somewhere the attacker can't reach. Both are in the threat model.

### The database

Out of the box it uses a SQLite file (`bank.db`), which is fine for poking around. It also runs
on PostgreSQL, which is what I'd use for anything shared or long-running:

```bash
pip install -e ".[dev,postgres]"
export COPILOT_DATABASE_URL=postgresql://copilot:<password>@localhost:5432/bank
python -m app.seed --reset
```

A plain `postgresql://` URL works; the app switches it to the psycopg 3 driver. Tables are
created on startup, and `python -m app.seed --if-empty` seeds only a fresh database, which is
what the Docker image does so restarts don't wipe your data.

### With Docker

Docker Compose runs the API, PostgreSQL 16 and Ollama together. Put a database password in
`.env` first (copy `.env.example`):

```bash
cp .env.example .env            # then set POSTGRES_PASSWORD
docker compose up --build
docker compose exec ollama ollama pull llama3.1:8b
docker compose exec ollama ollama pull nomic-embed-text
```

The database lives in the `pgdata` volume, so it survives restarts. To start over, run
`docker compose down -v`.

## Tests

```bash
make check
```

That runs ruff and pytest. You don't need a model for the tests: they use a scripted fake model,
the word-overlap search and a mocked Ollama endpoint, so CI runs them too.

By default the tests use in-memory SQLite. Point them at PostgreSQL with
`COPILOT_TEST_DATABASE_URL`, and every test gets freshly created and seeded tables there. **Use
a throwaway database for this, since the tests drop all tables.** CI runs the suite both ways.

One thing that might look odd: tests named `test_baseline_T*` check that the security holes are
still there, and `test_known_limit_*` pin down limits I know about. That's deliberate. When I add
a fix, I flip the matching test so it proves the hole is closed.

## What the assistants can do

Customer chat:

| Tool | What it does | Known hole in this build |
|---|---|---|
| `get_accounts` | Lists your accounts and balances | |
| `get_profile` | Your contact details | T8: also hands the model your full SIN and birth date |
| `list_transactions` | Recent transactions on an account | T3: doesn't check the account is yours |
| `initiate_transfer` | Sets up a pending transfer | T4: doesn't check the account is yours; T5: daily limit isn't enforced in code |
| `confirm_transfer` | Sends a pending transfer | T6: the model decides when you've "confirmed" |
| `send_email` | Drops an email in a sandbox outbox (nothing is ever sent) | T7: any recipient is accepted |
| `lookup_policy` | Searches the policy pages and returns sections with citation ids | T9: the model can still get answers wrong |

Email triage (staff):

| Tool | What it does | Known hole in this build |
|---|---|---|
| `lookup_customer_by_email` | Finds a customer and their balances by email | T13: works for any address, not just the sender |
| `send_email` | Same sandbox outbox | T7, T10: the prompt says not to send, but the tool is there |
| `lookup_policy` | Same policy search | |

The triage assistant reads emails exactly as they were sent (T10). The seed data includes four
hand-written attack emails, for example a "compliance audit" note asking the assistant to email
account details to an outside address, and a fraud report with a hidden HTML comment telling the
assistant to mark it low priority.

## Layout

```
app/               the assistants, API, tools, retrieval, audit log, models and seeding
app/rag/           chunking, embeddings and search over the policy docs
data/policy_docs/  made-up fee, transfer, account and privacy policies
data/emails/       hand-written attack emails used by the seeder
docs/              threat model and architecture notes
tests/             unit and API tests
```

The attack suite, defenses, evaluation scripts and validation docs will get their own folders as
I build them.

## A few ground rules I'm sticking to

- Synthetic data only, and attacks only against systems I own.
- The E-23 write-up is my reading of the guideline as a student. It isn't compliance or legal
  advice.

## License

MIT
