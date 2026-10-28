# 05 — Independent review report

E-23 (Principle 3.4) wants a review independent of development that covers conceptual soundness,
data, assumptions and performance, ends in a recommendation, and goes to the approver. This is
that review. (In a real bank the reviewer wouldn't be the builder; here it's the same person
wearing the reviewer hat, which I note as a limitation.)

- **Model:** MLB-COPILOT-001 v0.5
- **Reviewed:** 2026-10-28
- **Inputs:** the code (`app/`), the threat model ([../docs/threat-model.md](../docs/threat-model.md)),
  the test suite, and the red-team runs in [../reports/](../reports/).

## Method

The attack suite was run on the same cases in two modes — defences off (the undefended baseline)
and on — against `llama3.2:3b` on PostgreSQL, through the full Docker stack. Attack success and
false-refusal rates are measured, not asserted; small samples, so the confidence intervals are
wide and the category rows move in whole cases.

## Results: before vs. after

| Split | Attack success, defences off | Attack success, defences on | False refusals (on) |
|---|---|---|---|
| dev | 33% (4/12) | **0% (0/12)** | 0% (0/7) |
| held-out | 25% (2/8) | **12% (1/8)** | n/a (no benign cases) |

With answer-grounding added, the dev split's remaining attacks (the misinformation case and the
planted fee-waiver injection) close too, so every scored dev attack is defended. The held-out
split still has one attack landing — a non-fee indirect injection that grounding doesn't cover.

Under an **adaptive attacker** (a model that rewrites a failed attack and retries, `--adaptive 2`),
the dev split still held at **0% (0/13)** with 0% false refusals — the deterministic controls
don't care how the request is reworded (see [../reports/defended-adaptive-dev.md](../reports/defended-adaptive-dev.md)).

By category, with defences (including answer-grounding) on:

| Category | Defended result | Why |
|---|---|---|
| data_access (BOLA) | 0% | Ownership check in code closes it |
| data_exfil (email) | 0% | Recipient allow-list closes it |
| pii_exfil | 0% | Redaction + allow-list close it |
| unauthorized_action | 0% | Policy engine + out-of-band confirm close it |
| prompt_leak | 0% | Canary + output scrub close the verbatim leaks tested |
| misinformation | 0% | Answer-grounding replaces a fee claim the policy contradicts |
| indirect_injection | 0% on dev; one held-out case lands | Grounding catches the planted fee-waiver; a non-fee planted instruction can still reach a draft |

## Findings

1. **The deterministic controls work and carry the result.** Every category that maps to a
   check written in code went to 0% defended, with no false refusals. These are the controls
   the residual-risk step-down in [02-risk-rating.md](02-risk-rating.md) relies on. *Severity of
   remaining gap: low.*
2. **Misinformation is now addressed by answer-grounding.** A fee/policy claim the policy corpus
   contradicts (e.g. "wires are free") is caught and replaced, and the dev misinformation case
   went to 0% with no new false refusals. *Severity: low. The check is targeted at fee claims;
   broadening it to other figures is follow-up work.*
3. **Indirect injection is reduced, not solved.** Grounding closes the planted fee-waiver, but a
   non-fee planted instruction can still reach a draft (one held-out case). The draft is
   human-reviewed before sending, which is the mitigating control. *Severity: medium. Keep the
   human-in-the-loop condition; an adaptive-attack round is available via `--adaptive`.*
4. **Prompt-leak coverage is verbatim only.** The canary scrub catches the leak patterns tested;
   a paraphrased leak could slip it. *Severity: low. Note for monitoring.*
5. **A Postgres-only bug was found and fixed during review.** The daily-limit query compared a
   SQL date to a string, which SQLite accepted but PostgreSQL rejected; it crashed the first
   defended run and was fixed (datetime range). This is why the suite runs on both databases in
   CI. *Resolved.*

## Limitations of this review

- Reviewer is not independent of development (portfolio project).
- Small model (`llama3.2:3b`) and small samples; wide intervals. A few cases timed out on CPU
  and were excluded from the rates (noted in the reports).
- The adaptive attacker ran on the dev split (2 rounds) and didn't change the result; a longer
  campaign and a run on a production-scale model (`COPILOT_MODEL`) are still worth doing.

## Recommendation

**Approve for a limited pilot with conditions** (see [06-approval-memo.md](06-approval-memo.md)),
**not for general release.** The deterministic controls are sound and effective, and grounding
closes the misinformation gap. Before general release, run an adaptive-attack campaign and repeat
on a production-scale model, and broaden grounding beyond fee claims. Keep the human review on
transfers and triage drafts throughout.
