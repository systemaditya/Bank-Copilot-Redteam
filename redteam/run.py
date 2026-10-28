"""Run the attack suite and write a report.

    python -m redteam.run                       # dev split, defenses off (the baseline)
    python -m redteam.run --defenses on         # same cases, defenses on
    python -m redteam.run --split heldout --defenses on
    python -m redteam.run --list                # just show what cases load, no model needed

The database must already be seeded (``python -m app.seed``). Results go to reports/. Running
both modes on the same split is the before/after comparison the defenses are judged on.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.config import PROJECT_ROOT, get_settings
from app.defenses import Defenses
from app.llm import make_llm
from redteam.cases import CaseStats, load_cases
from redteam.report import render_markdown, summarise, write_raw
from redteam.runner import Harness

CASES_DIR = PROJECT_ROOT / "redteam" / "attacks"
REPORTS_DIR = PROJECT_ROOT / "reports"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the red-team attack suite.")
    parser.add_argument("--split", choices=["dev", "heldout", "all"], default="dev")
    parser.add_argument("--defenses", choices=["on", "off"], default="off")
    parser.add_argument(
        "--adaptive",
        type=int,
        default=0,
        metavar="ROUNDS",
        help="Let an attacker model rewrite a failed attack and retry up to ROUNDS times.",
    )
    parser.add_argument("--cases-dir", type=Path, default=CASES_DIR)
    parser.add_argument("--list", action="store_true", help="List loaded cases and exit.")
    args = parser.parse_args(argv)

    cases, errors = load_cases(args.cases_dir)
    for error in errors:
        print(f"[case error] {error.source}: {error.message}")
    if not cases:
        parser.error(f"No cases loaded from {args.cases_dir}.")
    if args.split != "all":
        cases = [c for c in cases if c.split == args.split]

    stats = CaseStats.of(cases)
    print(
        f"Loaded {stats.total} cases ({stats.attacks} attacks, {stats.benign} benign) "
        f"for split '{args.split}'. By category: "
        + ", ".join(f"{k}={v}" for k, v in sorted(stats.by_category.items()))
    )
    if args.list:
        return
    if errors:
        parser.error("Fix the case errors above before running.")

    settings = get_settings()
    defenses = Defenses.all_on() if args.defenses == "on" else Defenses.all_off()
    mode = "defended" if args.defenses == "on" else "baseline"
    print(
        f"Running against model '{settings.model}' at {settings.ollama_url} "
        f"with defenses {args.defenses} ({mode}) ..."
    )
    harness = Harness.build(settings, make_llm(settings), defenses=defenses)
    if args.adaptive > 0:
        from redteam.adaptive import AdaptiveAttacker

        mode = f"{mode}-adaptive"
        print(f"Adaptive attacker on, up to {args.adaptive} rounds per attack.")
        results = harness.run_adaptive(cases, AdaptiveAttacker(make_llm(settings)), args.adaptive)
    else:
        results = harness.run(cases)

    attacks_won = sum(1 for r in results if not r.case.benign and r.succeeded)
    print(f"Done. {attacks_won} attack(s) succeeded out of {stats.attacks}.")

    summary = summarise(
        results, model=settings.model, database=_db_kind(settings.database_url), mode=mode
    )
    report = render_markdown(summary, args.split)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"{mode}-{args.split}.md"
    report_path.write_text(report, encoding="utf-8")
    write_raw(results, REPORTS_DIR / "raw" / f"{mode}-{args.split}.jsonl")
    print(f"Wrote {report_path}")
    print("\n" + report)


def _db_kind(url: str) -> str:
    return "PostgreSQL" if "postgres" in url else "SQLite"


if __name__ == "__main__":
    main()
