# Bank Copilot Red Team

I'm building a banking AI assistant so I can break it, fix it, and then write it up the way a
Canadian bank's model-risk team would have to under OSFI Guideline E-23 (in force May 2027).

Most "secure chatbot" demos stop at a system prompt that says *please don't leak data*. I wanted
to measure how often that actually fails, which fixes really help, and what it costs in
false refusals for normal customers.

**Heads up:** Maple Ledger Bank doesn't exist, and neither do its customers. Every name, account
and transaction is generated (Faker names, `example.com` emails, 555-01xx phone numbers, random
SIN-shaped numbers). I only run attacks against my own local copy. The current build is insecure
on purpose. The weak spots are listed in [docs/threat-model.md](docs/threat-model.md).

## Where it's at

| Week | What | Done? |
|---|---|---|
| 1 | Threat model, architecture, repo setup, CI | Yes |
| 2 | Synthetic data, mock banking tools, a basic assistant with no defenses | Yes |
| 3 | Retrieval over policy docs, an email-triage assistant, audit logging | Next |
| 4 | Attack suite and baseline numbers | |
| 5–6 | Defenses: hard rules in code first, then classifiers and PII filters | |
| 7 | Held-out and adaptive attacks, a second model | |
| 8 | E-23 style validation write-up and a demo video | |

## Running it

You need Python 3.11 or newer. To actually chat with it you also need
[Ollama](https://ollama.com) and a model that supports tool calling. I've been using
`llama3.1:8b`. The versions I develop against are pinned in `requirements.lock`.

On Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m app.seed --reset
ollama pull llama3.1:8b
python -m app.cli_chat --customer C1000
```

On macOS or Linux:

```bash
python -m venv .venv && source .venv/bin/activate
make setup seed
ollama pull llama3.1:8b
make chat
```

The terminal chat prints every tool call the model makes, which is the easiest way to see what's
going on when you poke at it.

### Through the API

```bash
python -m uvicorn --factory app.main:create_app --reload
```

```bash
TOKEN=$(curl -s localhost:8000/auth/login -H 'content-type: application/json' \
  -d '{"customer_number":"C1000"}' | python -c "import sys,json; print(json.load(sys.stdin)['token'])")
curl -s localhost:8000/chat -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"message":"What are my account balances?"}'
```

Each reply comes back with a `trace` of the tool calls behind it. I keep that on because the
attack scoring needs it; set `COPILOT_RETURN_TRACE=false` to turn it off. FastAPI's docs page is
at `http://localhost:8000/docs`.

### With Docker

```bash
docker compose up --build
docker compose exec ollama ollama pull llama3.1:8b
```

## Tests

```bash
make check
```

That runs ruff and pytest. You don't need a model for the tests: they use a scripted fake model
and a mocked Ollama endpoint, so CI runs them too.

One thing that might look odd: the tests named `test_baseline_T*` check that the security holes
are still there. That's deliberate. When I add a fix, I flip the matching test so it proves the
hole is closed.

## What the assistant can do

| Tool | What it does | Known hole in this build |
|---|---|---|
| `get_accounts` | Lists your accounts and balances | |
| `get_profile` | Your contact details | T8: also hands the model your full SIN and birth date |
| `list_transactions` | Recent transactions on an account | T3: doesn't check the account is yours |
| `initiate_transfer` | Sets up a pending transfer | T4: doesn't check the account is yours; T5: daily limit isn't enforced in code |
| `confirm_transfer` | Sends a pending transfer | T6: the model decides when you've "confirmed" |
| `send_email` | Drops an email in a sandbox outbox (nothing is ever sent) | T7: any recipient is accepted |
| `lookup_policy` | Keyword search over the bank's policy pages | T9: the model can still get answers wrong |

## Layout

```
app/               the assistant, API, tools, database models and seeding
data/policy_docs/  made-up fee, transfer, account and privacy policies
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
