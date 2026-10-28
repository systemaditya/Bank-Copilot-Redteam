"""Turn scored case results into a summary: attack success and false-refusal rates with
confidence intervals, broken down by category, plus a Markdown report and raw JSONL."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from redteam.runner import CaseResult
from redteam.stats import Proportion, wilson


@dataclass(frozen=True)
class GroupSummary:
    name: str
    proportion: Proportion
    errored: int


@dataclass(frozen=True)
class Summary:
    model: str
    database: str
    mode: str  # "baseline" or "defended"
    when: str
    attack_total: int
    benign_total: int
    errored: int
    attack_overall: Proportion
    benign_overall: Proportion
    attacks_by_category: list[GroupSummary]


def _rate(results: list[CaseResult]) -> tuple[Proportion, int]:
    scorable = [r for r in results if r.record.error is None]
    errored = len(results) - len(scorable)
    hits = sum(1 for r in scorable if r.succeeded)
    return wilson(hits, len(scorable)), errored


def summarise(
    results: list[CaseResult], *, model: str, database: str, mode: str = "baseline"
) -> Summary:
    attacks = [r for r in results if not r.case.benign]
    benign = [r for r in results if r.case.benign]
    attack_overall, attack_err = _rate(attacks)
    benign_overall, benign_err = _rate(benign)

    by_category: dict[str, list[CaseResult]] = defaultdict(list)
    for result in attacks:
        by_category[result.case.category].append(result)
    category_summaries = []
    for name in sorted(by_category):
        proportion, errored = _rate(by_category[name])
        category_summaries.append(GroupSummary(name, proportion, errored))

    return Summary(
        model=model,
        database=database,
        mode=mode,
        when=datetime.now(UTC).isoformat(timespec="seconds"),
        attack_total=len(attacks),
        benign_total=len(benign),
        errored=attack_err + benign_err,
        attack_overall=attack_overall,
        benign_overall=benign_overall,
        attacks_by_category=category_summaries,
    )


def write_raw(results: list[CaseResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for result in results:
            row = {
                "case_id": result.case.id,
                "channel": result.case.channel,
                "category": result.case.category,
                "split": result.case.split,
                "benign": result.case.benign,
                "goal": result.case.goal,
                "succeeded": result.succeeded,
                "label": result.label,
                "record": {k: v for k, v in asdict(result.record).items() if k != "context"},
            }
            handle.write(json.dumps(row, default=str, ensure_ascii=False) + "\n")


def render_markdown(summary: Summary, split: str) -> str:
    if summary.mode == "defended":
        build_line = "- Build: **defences on**. Compare against the baseline run on the same split."
    else:
        build_line = (
            "- Build: **baseline, no defences**. This is the bar the defended run has to beat."
        )
    lines = [
        f"# Red-team results — {summary.mode} ({split} split)",
        "",
        f"- Model: `{summary.model}`",
        f"- Database: {summary.database}",
        f"- Run at: {summary.when}",
        build_line,
        "",
        "> Every number here is a measured result on this run, not a target. Small sample sizes, "
        "so read the confidence intervals, not just the point estimate.",
        "",
        "## Headline",
        "",
        f"- Attack success rate: **{summary.attack_overall.pct()}** across "
        f"{summary.attack_total} attacks.",
        f"- False refusal rate on benign tasks: **{summary.benign_overall.pct()}** across "
        f"{summary.benign_total} tasks.",
    ]
    if summary.errored:
        lines.append(
            f"- {summary.errored} case(s) errored (e.g. the model was unreachable) and were "
            "left out of the rates above."
        )
    lines += [
        "",
        "## Attack success by category",
        "",
        "| Category | Success rate (95% CI) | Errored |",
        "|---|---|---|",
    ]
    for group in summary.attacks_by_category:
        errored = str(group.errored) if group.errored else "-"
        lines.append(f"| {group.name} | {group.proportion.pct()} | {errored} |")
    lines += [
        "",
        "## How to read this",
        "",
        "Run both modes on the same split: the baseline shows what gets through with the rules "
        "living only in the system prompt, and the defended run shows what the in-code controls "
        "stop. False refusals on benign tasks are tracked alongside, so a control can't score "
        "well just by refusing everything.",
        "",
    ]
    return "\n".join(lines)
