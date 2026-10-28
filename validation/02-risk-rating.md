# 02 — Model risk rating

E-23 rates a model on its **inherent** risk (what could go wrong before controls), and that
rating sets how much review, documentation and monitoring the model gets. Residual risk is
reported for visibility but doesn't drive the governance.

## Factors

| Factor | Assessment | Weight |
|---|---|---|
| Customers exposed | All retail customers who use the assistant | High |
| Money movement | Can set up transfers (a person confirms) | High |
| PII exposure | Sees names, contact details, balances, SIN | High |
| Autonomy | Low: drafts actions, doesn't execute money movement on its own | Medium |
| Explainability | Low: generative model, non-deterministic | High |
| Reversibility | Confirmed transfers to other institutions are hard to reverse | High |
| Vendor dependence | Core model is third-party and opaque | Medium |
| Exposure to hostile input | Reads customer chat and inbound email (attacker-controlled) | High |

## Rating

**Inherent risk: High.** Any model that can touch money movement and customer PII, is hard to
explain, and reads attacker-controlled input sits at the top of the scale.

**Residual risk after the controls: Medium**, and only while the deterministic controls are on.
The red-team results ([05-independent-review-report.md](05-independent-review-report.md)) are the
evidence for that step-down. It's not Low, because the probabilistic controls (prompt handling,
untrusted-content marking) reduce risk without removing it, and the base model can still be
wrong.

## What the High rating buys (Principle 2.3)

- Independent review before approval, and again on any trigger event.
- The full documentation set in this folder.
- The monitoring in [08-monitoring-plan.md](08-monitoring-plan.md), with defined thresholds and
  an escalation path.
- Approval by a senior owner with explicit conditions of use
  ([06-approval-memo.md](06-approval-memo.md)).
- Re-assessment at least annually.
