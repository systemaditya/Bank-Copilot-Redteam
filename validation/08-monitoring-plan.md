# 08 — Monitoring plan

E-23 (Principle 3.6) wants defined monitoring: what's measured, the thresholds, who's alerted,
and what triggers a re-validation. The hooks for most of this already exist in the audit log and
the red-team harness.

## Metrics and thresholds

| Metric | Source | Threshold → action |
|---|---|---|
| Attack success rate on a weekly regression run | `python -m redteam.run --defenses on` in CI | Above the last approved figure → investigate before the next release |
| False refusal rate on the benign set | same run | Above ~5% → tune; a control that refuses real customers isn't worth it |
| Prompt-leak blocks (`prompt_leak_blocked` events) | audit log | Any spike → review for a new leak technique |
| Confirm rejections (`confirm_rejected`) | audit log | A rise may mean customers are confused by the confirm step → UX review |
| Tool-call errors / `tool_loop_truncated` | audit log | Rising → model or tool-schema drift |
| "No policy found" rate | tool results | Rising → a coverage gap in the policy corpus |
| Auth failures (`auth_failed`) | audit log | Spike → possible probing |
| Latency (p50/p95) and cost per request | runtime | Budget breach → investigate |

## Integrity checks

- `python -m app.audit verify` runs on a schedule; a broken chain is a security incident.
- Known gap (T15): a hash chain can't detect records cut from the end. A production build needs
  an external witness (periodically publish the latest hash somewhere append-only). Tracked, not
  built.

## Re-validation triggers

- A change of base model or model version.
- A change to a system prompt, a tool, or the tool set.
- A monitoring threshold breached and not explained.
- A material change to the policy corpus.
- At least once a year regardless.

## Human oversight

The assistant proposes; people dispose. No transfer goes out without the customer's own
confirmation, and no triage reply is sent without a staff member. Monitoring is a backstop, not
the only line of defence.
