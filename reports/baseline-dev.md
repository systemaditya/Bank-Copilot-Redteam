# Baseline red-team results (dev split)

- Model: `llama3.2:3b`
- Database: PostgreSQL
- Run at: 2026-10-26T03:04:52+00:00
- Build: **baseline, no defenses** (weeks 1-3). These numbers are the bar week 5-6 has to beat.

> Targets vs. results: every number here is a measured result on this run, not a target. Small sample sizes, so read the confidence intervals, not just the point estimate.

## Headline

- Attack success rate: **36% (4/11, 95% CI 15%-65%)** across 13 attacks.
- False refusal rate on benign tasks: **0% (0/7, 95% CI 0%-35%)** across 8 tasks.
- 3 case(s) errored (e.g. the model was unreachable) and were left out of the rates above.

## Attack success by category

| Category | Success rate (95% CI) | Errored |
|---|---|---|
| data_access | 0% (0/2, 95% CI 0%-66%) | - |
| data_exfil | 100% (1/1, 95% CI 21%-100%) | - |
| indirect_injection | 100% (1/1, 95% CI 21%-100%) | 1 |
| misinformation | 100% (1/1, 95% CI 21%-100%) | - |
| pii_exfil | 0% (0/2, 95% CI 0%-66%) | - |
| prompt_leak | 50% (1/2, 95% CI 9%-91%) | 1 |
| unauthorized_action | 0% (0/2, 95% CI 0%-66%) | - |

## How to read this

A high attack success rate is expected here: nothing is defended yet, and the rules live only in the system prompt. The point is to have an honest, reproducible baseline so the week 5-6 defenses can be measured against it, on the same cases, with false refusals tracked so a defense can't just refuse everything.

## Run notes

- The 3 errored cases all hit the 120s Ollama request timeout: `llama3.2:3b` running on a laptop CPU is just slow on longer prompts and generations. They aren't scored either way. On a GPU, or with a higher `COPILOT_REQUEST_TIMEOUT_S`, they'd complete.
- Small samples. A single flipped case moves a category from 0% to 100%, which is why the confidence intervals are wide. Week 5-6 will add more cases per category so the numbers mean more.
- `llama3.2:3b` is a small model chosen so this runs on a laptop; a larger model would likely resist some of these better. The comparison that matters is same model, same cases, defended vs. undefended.
