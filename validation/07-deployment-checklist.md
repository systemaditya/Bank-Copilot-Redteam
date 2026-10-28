# 07 — Deployment checklist

E-23 (Principle 3.5) wants deployment controlled: pre-production checks, access control, and a
way back. This is the checklist for the pilot.

## Before production

- [ ] All five deterministic controls on (`COPILOT_DEFENSES_ENABLED=true`); verified with a
      defended red-team run on both splits.
- [ ] Audit log on, with PII redaction on; `python -m app.audit verify` passes on a sample.
- [ ] A real signing/canary secret set (not the lab default `system_prompt_canary`).
- [ ] The database is PostgreSQL, not the SQLite file; migrations reviewed.
- [ ] `return_trace` off for customer-facing responses (it's a lab aid).
- [ ] Rate and size limits in front of the API.
- [ ] Monitoring dashboards and alerts live ([08-monitoring-plan.md](08-monitoring-plan.md)).
- [ ] The model and embedding versions are pinned and recorded in the inventory.
- [ ] Access: customer tokens and staff tokens are separate; staff endpoints reject customer
      tokens and vice versa (there's a test for this).

## Rollout

- Internal staff first, then opt-in customers, at a capped volume.
- Feature-flagged so it can be turned off without a deploy.

## Rollback

- A single flag disables the assistant and falls back to the existing (non-AI) flow.
- Because no transfer is sent without the customer's own confirmation, a mid-session rollback
  can't leave a half-finished money movement.
- Pending transfers created but not confirmed simply expire unconfirmed.
