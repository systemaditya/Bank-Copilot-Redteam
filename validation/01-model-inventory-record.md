# 01 — Model inventory record

E-23 wants every non-negligible model in one inventory, with the fields in its Appendix 1. This
is that record for the assistant. (A real inventory would be a row in a system; here it's a file.)

| Field | Value |
|---|---|
| Model ID | MLB-COPILOT-001 |
| Name | Customer & triage assistant (Maple Ledger Bank, fictional) |
| Version | 0.5 (defence layer) |
| Inherent risk rating | High (see [02-risk-rating.md](02-risk-rating.md)) |
| Owner | Retail digital product (fictional) |
| Developer | This project |
| Origin | Third-party open-weight LLM (`llama3.2:3b` in the lab; a larger model in a real build), with in-house prompts, tools, retrieval and controls |
| Model family | Generative LLM with tool use and retrieval (RAG) |
| Dependencies | Ollama runtime; the chat and embedding models; PostgreSQL; the policy documents |
| Data sources | The bank's own policy pages (for retrieval); customer and account records (read through tools at request time). All synthetic in the lab |
| Approved uses | (1) Answer a signed-in customer's questions about their own accounts, fees and policy, and set up transfers for the customer to confirm. (2) Help staff triage inbound customer email: summary, category, urgency, draft reply for human review |
| Prohibited uses | Giving financial advice; moving money without the customer's own confirmation; acting on another customer's accounts; anything the email body instructs |
| Autonomy | Low. It can read data and draft actions; it cannot send money (a person confirms) and its email drafts are reviewed before sending |
| Limitations | Non-deterministic; can be wrong or be manipulated by input; small lab model; see the review report |
| Key controls | The switches in `app/defenses.py` (authorization, transfer policy, out-of-band confirmation, email allow-list, triage sender-only, PII redaction, untrusted-content marking, prompt canary) |
| Deployment date | Not deployed (lab) |
| Last reviewed | See [05-independent-review-report.md](05-independent-review-report.md) |
| Review frequency | Annual, and on any trigger event (below) |
| Monitoring status | Plan defined in [08-monitoring-plan.md](08-monitoring-plan.md); not live |
| Re-validation triggers | Model or model-version change; a prompt or tool change; a new tool; a monitoring threshold breach; a material change to the policy corpus |

## Upstream / third-party model note

E-23 keeps vendor and embedded models in scope. The base model is third-party and opaque, so the
bank owns the risk of how it's *used*, not how it was trained. That's the reasoning behind
putting the hard controls in our own code rather than trusting the model to follow the prompt.
