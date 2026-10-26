"""Load attack and benign cases from YAML and decide, from a run, whether each one succeeded.

A case file is a list of cases. An attack case names one or more scorers; by default it counts as
a successful attack if *any* of them fire (set ``mode: all`` to require all). A benign case sets
``benign: true`` and is scored only for a false refusal, so the same runner measures both attack
success and the usability cost of defending against it.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from redteam.scoring import RunRecord, known_scorers, run_scorer

CHANNELS = ("chat", "triage")


@dataclass(frozen=True)
class Case:
    id: str
    channel: str
    category: str
    split: str  # "dev" or "heldout"
    benign: bool
    scorers: list[dict[str, Any]]
    mode: str  # "any" or "all"
    # chat inputs
    customer: str | None
    message: str | None
    # triage inputs
    email_id: int | None
    email: dict[str, Any] | None
    goal: str

    def evaluate(self, record: RunRecord) -> bool:
        """For an attack: did it succeed? For a benign case: was it falsely refused?"""
        if self.benign:
            return run_scorer("refusal", record, {})
        if not self.scorers:
            return False
        fired = (run_scorer(s["type"], record, s) for s in self.scorers)
        return all(fired) if self.mode == "all" else any(fired)


@dataclass(frozen=True)
class CaseError:
    source: str
    message: str


def _coerce(raw: dict[str, Any], source: str) -> Case:
    def require(key: str) -> Any:
        if key not in raw:
            raise ValueError(f"{source}: case {raw.get('id', '?')!r} is missing '{key}'")
        return raw[key]

    channel = require("channel")
    if channel not in CHANNELS:
        raise ValueError(f"{source}: case {raw['id']!r} has unknown channel {channel!r}")
    benign = bool(raw.get("benign", False))
    scorers = raw.get("scorers", [])
    if not benign:
        if not scorers:
            raise ValueError(f"{source}: attack case {raw['id']!r} needs at least one scorer")
        for spec in scorers:
            if spec.get("type") not in known_scorers():
                raise ValueError(
                    f"{source}: case {raw['id']!r} uses unknown scorer {spec.get('type')!r}"
                )
    if channel == "chat" and not raw.get("message"):
        raise ValueError(f"{source}: chat case {raw['id']!r} needs a 'message'")
    if channel == "triage" and not raw.get("email_id") and not raw.get("email"):
        raise ValueError(f"{source}: triage case {raw['id']!r} needs 'email_id' or 'email'")
    return Case(
        id=require("id"),
        channel=channel,
        category=raw.get("category", "uncategorised"),
        split=raw.get("split", "dev"),
        benign=benign,
        scorers=scorers,
        mode=raw.get("mode", "any"),
        customer=raw.get("customer"),
        message=raw.get("message"),
        email_id=raw.get("email_id"),
        email=raw.get("email"),
        goal=raw.get("goal", ""),
    )


def load_cases(directory: Path) -> tuple[list[Case], list[CaseError]]:
    """Load every ``*.yaml`` case under ``directory``. Returns the cases and any load errors,
    so one malformed file doesn't hide the rest."""
    cases: list[Case] = []
    errors: list[CaseError] = []
    seen_ids: dict[str, str] = {}
    for path in sorted(directory.rglob("*.yaml")):
        source = path.name
        try:
            documents = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        except yaml.YAMLError as exc:
            errors.append(CaseError(source, f"invalid YAML: {exc}"))
            continue
        if not isinstance(documents, list):
            errors.append(CaseError(source, "file must be a list of cases"))
            continue
        for raw in documents:
            try:
                case = _coerce(raw, source)
            except (ValueError, KeyError, TypeError) as exc:
                errors.append(CaseError(source, str(exc)))
                continue
            if case.id in seen_ids:
                errors.append(CaseError(source, f"duplicate case id {case.id!r}"))
                continue
            seen_ids[case.id] = source
            cases.append(case)
    return cases, errors


def iter_splits(cases: list[Case]) -> Iterator[tuple[str, list[Case]]]:
    for split in ("dev", "heldout"):
        yield split, [c for c in cases if c.split == split]


@dataclass
class CaseStats:
    total: int = 0
    attacks: int = 0
    benign: int = 0
    by_category: dict[str, int] = field(default_factory=dict)

    @classmethod
    def of(cls, cases: list[Case]) -> CaseStats:
        stats = cls(total=len(cases))
        for case in cases:
            if case.benign:
                stats.benign += 1
            else:
                stats.attacks += 1
            stats.by_category[case.category] = stats.by_category.get(case.category, 0) + 1
        return stats
