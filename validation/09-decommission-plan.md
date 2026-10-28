# 09 — Decommission plan

E-23 (Principle 3.6) also covers the end: retire a model in a controlled way, keep the records,
and watch for downstream effects.

## Steps

1. **Announce.** Tell the product owner, staff who use triage, and support, with a date.
2. **Switch off.** Use the deployment feature flag; the existing non-AI flow takes over. No code
   removal needed to stop serving.
3. **Drain.** Let in-flight conversations finish or expire. Unconfirmed pending transfers are
   left to expire; none were sent without a customer confirmation, so nothing is half-done.
4. **Retain the records.** Keep the audit log, this validation pack, and the last red-team
   reports for the retention period. The inventory row is marked decommissioned, not deleted.
5. **Watch downstream.** For a period after switch-off, watch the fallback flow's volume and the
   contact-centre load, in case the assistant was quietly absorbing demand.
6. **Keys and data.** Rotate or destroy the canary and any signing secrets. Customer data stays
   under its own retention rules; the assistant created no new system of record.

## Fallback

The non-AI customer flow and manual email triage remain available throughout, so decommissioning
is a fallback, not an outage.
