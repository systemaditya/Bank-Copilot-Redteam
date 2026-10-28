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
| dev | 33% (4/12) | **17% (2/12)** | 0% (0/7) |
| held-out | 25% (2/8) | **12% (1/8)** | n/a (no benign cases) |

By category (combining both splits), the attacks that still succeed with defences on are:

| Category | Defended result | Why it still gets through |
|---|---|---|
| data_access (BOLA) | 0% | Ownership check in code closes it |
| data_exfil (email) | 0% | Recipient allow-list closes it |
| pii_exfil | 0% | Redaction + allow-list close it |
| unauthorized_action | 0% | Policy engine + out-of-band confirm close it |
| prompt_leak | 0% | Canary + output scrub close the verbatim leaks tested |
| **misinformation** | **still ~100% (1/1)** | No deterministic rule makes a model state the right fee; it needs answer-grounding against the cited policy, which isn't built |
| **indirect_injection** | **still ~33-50%** | Marking content as untrusted reduces it but doesn't stop a model from, e.g., repeating a planted "fee waiver" in a draft |

## Findings

1. **The deterministic controls work and carry the result.** Every category that maps to a
   check written in code went to 0% defended, with no false refusals. These are the controls
   the residual-risk step-down in [02-risk-rating.md](02-risk-rating.md) relies on. *Severity of
   remaining gap: low.*
2. **Misinformation is not addressed.** The assistant can still state a wrong fee as fact.
   This isn't a prompt-injection problem; it needs the answer checked against the policy section
   it cites. *Severity: medium (customer-harm, conduct risk). Recommend building answer-grounding
   before general release.*
3. **Indirect injection is reduced, not solved.** Untrusted-content marking helps, but a
   determined planted instruction can still reach a draft reply. The draft is human-reviewed
   before sending, which is the mitigating control. *Severity: medium. Recommend keeping the
   human-in-the-loop condition and adding adaptive tests.*
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
- No adaptive attacks (attacker adapts to the defence) and no second, larger model yet.

## Recommendation

**Approve for a limited pilot with conditions** (see [06-approval-memo.md](06-approval-memo.md)),
**not for general release.** The deterministic controls are sound and effective. Before general
release, build answer-grounding for the misinformation gap, run an adaptive-attack round, and
repeat on a production-scale model. Keep the human review on transfers and triage drafts
throughout.
