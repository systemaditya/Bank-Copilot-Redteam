"""Run the attack suite and write a baseline report.

    python -m redteam.run                 # dev split, live model from settings
    python -m redteam.run --split heldout
    python -m redteam.run --list          # just show what cases load, no model needed

The database must already be seeded (``python -m app.seed``). Results go to reports/.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.config import PROJECT_ROOT, get_settings
from app.llm import make_llm
from redteam.cases import CaseStats, load_cases
from redteam.report import render_markdown, summarise, write_raw
from redteam.runner import Harness

CASES_DIR = PROJECT_ROOT / "redteam" / "attacks"
REPORTS_DIR = PROJECT_ROOT / "reports"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the red-team attack suite.")
    parser.add_argument("--split", choices=["dev", "heldout", "all"], default="dev")
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
    print(f"Running against model '{settings.model}' at {settings.ollama_url} ...")
    harness = Harness.build(settings, make_llm(settings))
    results = harness.run(cases)

    attacks_won = sum(1 for r in results if not r.case.benign and r.succeeded)
    print(f"Done. {attacks_won} attack(s) succeeded out of {stats.attacks}.")

    summary = summarise(results, model=settings.model, database=_db_kind(settings.database_url))
    report = render_markdown(summary, args.split)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"baseline-{args.split}.md"
    report_path.write_text(report, encoding="utf-8")
    write_raw(results, REPORTS_DIR / "raw" / f"baseline-{args.split}.jsonl")
    print(f"Wrote {report_path}")
    print("\n" + report)


def _db_kind(url: str) -> str:
    return "PostgreSQL" if "postgres" in url else "SQLite"


if __name__ == "__main__":
    main()
