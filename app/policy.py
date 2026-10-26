"""Keyword search over the fictional bank's policy documents.

This is the Week 2 stand-in for retrieval. Week 3 replaces it with embedding search (RAG)
behind the same ``search(query, top_k)`` interface.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_WORD = re.compile(r"[a-z0-9]+")
# fmt: off
_STOPWORDS = frozenset([
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "how",
    "i", "in", "is", "it", "me", "my", "of", "on", "or", "the", "to", "what", "when", "where",
    "which", "with", "you", "your",
])
# fmt: on


def _normalise(token: str) -> str:
    return token[:-1] if len(token) > 3 and token.endswith("s") else token


def _tokens(text: str) -> frozenset[str]:
    return frozenset(_normalise(t) for t in _WORD.findall(text.lower()) if t not in _STOPWORDS)


@dataclass(frozen=True)
class PolicySection:
    source: str
    title: str
    text: str
    tokens: frozenset[str]


class PolicyIndex:
    def __init__(self, sections: list[PolicySection]) -> None:
        self.sections = sections

    @classmethod
    def from_directory(cls, directory: Path) -> PolicyIndex:
        sections = []
        for path in sorted(directory.glob("*.md")):
            for title, body in _split_sections(path.read_text(encoding="utf-8")):
                body = body.strip()
                sections.append(PolicySection(path.name, title, body, _tokens(f"{title} {body}")))
        return cls(sections)

    def search(self, query: str, top_k: int = 3) -> list[PolicySection]:
        wanted = _tokens(query)
        if not wanted:
            return []
        scored = [
            (len(wanted & section.tokens), position, section)
            for position, section in enumerate(self.sections)
        ]
        scored = [item for item in scored if item[0] > 0]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [section for _, _, section in scored[:top_k]]


def _split_sections(markdown: str) -> Iterator[tuple[str, str]]:
    title: str | None = None
    lines: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("## "):
            if title is not None:
                yield title, "\n".join(lines)
            title, lines = line[3:].strip(), []
        elif title is not None:
            lines.append(line)
    if title is not None:
        yield title, "\n".join(lines)


@lru_cache(maxsize=8)
def load_policy_index(directory: str) -> PolicyIndex:
    return PolicyIndex.from_directory(Path(directory))
