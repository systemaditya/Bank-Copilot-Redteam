# Model validation pack

This folder is my attempt to document the assistant the way a Canadian bank's model-risk team
would have to under OSFI Guideline E-23, *Model Risk Management* (final version published
September 2025, in force 1 May 2027). It treats the LLM assistant as a model and walks it through
the guideline's lifecycle: identify it, rate its risk, document how it was built, review it
independently, approve it with conditions, deploy it, monitor it, and plan to retire it.

**This is a student's reading of a principles-based guideline, for a portfolio project. It is not
compliance advice, and it isn't a real submission to anyone.** E-23 doesn't mention generative AI
specifically, so I'm mapping the assistant onto its AI/ML provisions and saying so where I do.

## The documents

| File | E-23 touch-point |
|---|---|
| [01-model-inventory-record.md](01-model-inventory-record.md) | Model identification and inventory (Principle 2.1, Appendix 1) |
| [02-risk-rating.md](02-risk-rating.md) | Model risk rating and intensity (Principles 2.2-2.3) |
| [03-model-rationale-and-data.md](03-model-rationale-and-data.md) | Rationale and data (Principle 3.2) |
| [04-development-documentation.md](04-development-documentation.md) | Development documentation and explainability (Principle 3.3) |
| [05-independent-review-report.md](05-independent-review-report.md) | Independent review (Principle 3.4) |
| [06-approval-memo.md](06-approval-memo.md) | Approval and conditions of use |
| [07-deployment-checklist.md](07-deployment-checklist.md) | Deployment (Principle 3.5) |
| [08-monitoring-plan.md](08-monitoring-plan.md) | Monitoring and re-validation (Principle 3.6) |
| [09-decommission-plan.md](09-decommission-plan.md) | Decommissioning (Principle 3.6) |

## How it ties to the code

The review and monitoring documents lean on the red-team results in
[../reports/](../reports/): the attack suite run with defences off (the baseline) and on (the
defended build), on the same cases, with false refusals tracked. The controls they describe are
the ones in `app/defenses.py` and the tools, and the threat IDs (T1-T15) are the ones in
[../docs/threat-model.md](../docs/threat-model.md).

Other frameworks worth a cross-reference, not done here: the NIST AI Risk Management Framework
and its Generative AI Profile (NIST AI 600-1), and OSFI's technology-and-cyber guideline B-13.
