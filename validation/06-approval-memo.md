# 06 — Approval memo

E-23 separates review from approval: the independent reviewer recommends, and a sufficiently
senior owner approves, with conditions. This is the (fictional) approval.

- **Model:** MLB-COPILOT-001 v0.5
- **Decision:** Approved for a limited pilot, with conditions. Not approved for general release.
- **Based on:** the independent review ([05-independent-review-report.md](05-independent-review-report.md)).

## Conditions of use

1. The deterministic controls (authorization, transfer policy, out-of-band confirmation, email
   allow-list, triage sender-only) must be on in production. Turning any off requires a new
   review.
2. No transfer is sent by the assistant. The customer confirms every transfer out of band.
3. Triage output is a draft only; a staff member reviews and sends.
4. The assistant gives no financial advice; it answers from policy with citations or says it
   can't.
5. The audit log runs with PII redaction on.
6. Monitoring per [08-monitoring-plan.md](08-monitoring-plan.md) is live before any real
   customer traffic, with the escalation path staffed.

## Open items the reviewer flagged (not blockers for a pilot)

- Paraphrased prompt-leak attempts aren't fully covered by the canary scrub.
- Residual indirect-injection risk on the triage path.
- Adaptive (attacker-adapts-to-the-defence) testing and a second, larger model are outstanding.

## Pilot scope

Internal staff and opt-in customers only; capped volume; a named owner; weekly review of the
monitoring metrics during the pilot.
