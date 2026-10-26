"""Split the policy docs into chunks, one per "## " section.

Each chunk gets a stable id like ``fees#transfer-fees``. The assistant cites that id, so a
reviewer can check every policy claim against the exact section it came from.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Chunk:
    id: str
    source: str
    title: str
    text: str

    @property
    def embed_text(self) -> str:
        return f"{self.title}\n{self.text}"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def load_chunks(directory: Path) -> list[Chunk]:
    chunks = []
    for path in sorted(directory.glob("*.md")):
        for title, body in split_sections(path.read_text(encoding="utf-8")):
            chunks.append(Chunk(f"{path.stem}#{slugify(title)}", path.name, title, body.strip()))
    return chunks


def split_sections(markdown: str) -> Iterator[tuple[str, str]]:
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
