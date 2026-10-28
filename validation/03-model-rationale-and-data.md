# 03 — Rationale and data

## Why a model, and why this one

The business goal is faster, consistent answers to routine customer questions and faster triage
of inbound email, without a person doing the first pass each time. A generative assistant with
tool use fits because the questions are open-ended but the actions behind them are a small, fixed
set (read accounts, look up policy, set up a transfer, draft a reply).

Why an LLM rather than a rules engine or intent classifier: the inputs are free text and vary a
lot. Why keep the actions narrow and gated: see the whole point of this project — the model is
the least trustworthy part, so it proposes and a deterministic layer disposes.

## Data

| Data | Use | Sensitivity | Handling |
|---|---|---|---|
| Policy pages | Retrieval, so answers cite real policy | Low (public) | Embedded and searched; results carry citation ids |
| Customer & account records | Read at request time through tools | High (PII) | Never bulk-loaded into the prompt; tools return only what a task needs, SIN masked and DOB dropped when redaction is on |
| Inbound email | Triage input | High + hostile | Fenced and marked untrusted; never treated as instructions |
| Chat transcripts / audit log | Operations and this review | High (PII) | Hash-chained; SINs redacted before writing |

All data in the lab is synthetic (generated names, `example.com` emails, 555-01xx phones,
random Luhn-valid SIN-shaped numbers). No real customer data is used anywhere.

## Bias and data-quality notes (Principle 3.2)

- The policy corpus is small and bank-authored, so retrieval bias mostly shows up as *missing*
  coverage: a question with no matching section gets a weak answer. The monitoring plan tracks
  "no policy found" rates.
- The base model carries whatever bias it was trained with. For this use (banking Q&A and
  triage) the main risk is uneven quality across phrasings and languages rather than a protected-
  group decision, because the model makes no approve/deny decision about a customer. A bilingual
  (English/French) evaluation is listed as future work.
