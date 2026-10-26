"""Append-only audit log, one JSON object per line, with a hash chain.

Every record stores the hash of the record before it, so if anyone edits, reorders or deletes
a line in the middle of the file, ``verify`` finds the exact spot. What a chain like this
*can't* catch is someone cutting lines off the end, since the remaining file is still a valid
chain. Closing that gap needs an outside witness (for example, periodically publishing the
latest hash somewhere else), which is noted as T15 in the threat model.

The log holds full prompts and tool results, so it contains customer PII. That's T14; week 6
adds redaction before records are written.

    python -m app.audit verify logs/audit.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64
MAX_FIELD_CHARS = 4000


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _digest(record: dict[str, Any]) -> str:
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _clip(value: Any) -> Any:
    """Make a value JSON-safe and cap long strings so one huge prompt can't bloat the log."""
    if isinstance(value, str):
        if len(value) > MAX_FIELD_CHARS:
            return value[:MAX_FIELD_CHARS] + f"...[{len(value) - MAX_FIELD_CHARS} chars cut]"
        return value
    if isinstance(value, dict):
        return {str(k): _clip(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clip(v) for v in value]
    if value is None or isinstance(value, bool | int | float):
        return value
    return _clip(str(value))


class AuditLog:
    def __init__(self, path: Path, clock: Callable[[], str] = _now_iso) -> None:
        self.path = path
        self._clock = clock
        self._lock = threading.Lock()
        self._seq, self._prev_hash = self._resume()

    def _resume(self) -> tuple[int, str]:
        """Continue the chain from the last record already in the file."""
        if not self.path.exists():
            return 0, GENESIS_HASH
        last = None
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last = line
        if last is None:
            return 0, GENESIS_HASH
        record = json.loads(last)
        return int(record["seq"]), str(record["hash"])

    def append(self, fields: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            record = {
                "seq": self._seq + 1,
                "ts": self._clock(),
                **_clip(fields),
                "prev_hash": self._prev_hash,
            }
            record["hash"] = _digest(record)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._seq, self._prev_hash = record["seq"], record["hash"]
            return record

    def scope(self, *, channel: str, actor: str, request_id: str | None = None) -> RequestAudit:
        return RequestAudit(self, channel, actor, request_id or uuid.uuid4().hex)


class RequestAudit:
    """Audit handle for one request: stamps every event with the same request id and actor."""

    def __init__(
        self, log: AuditLog | None, channel: str, actor: str, request_id: str = ""
    ) -> None:
        self._log = log
        self.channel = channel
        self.actor = actor
        self.request_id = request_id

    def event(self, event_name: str, /, **fields: Any) -> None:
        # Positional-only so callers can log a field called "name" (tool calls do).
        if self._log is None:
            return
        self._log.append(
            {
                "request_id": self.request_id,
                "channel": self.channel,
                "actor": self.actor,
                "event": event_name,
                **fields,
            }
        )


NULL_AUDIT = RequestAudit(None, channel="none", actor="none")


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    records: int
    error: str = ""
    line: int | None = None


def verify(path: Path) -> VerifyResult:
    prev_hash, expected_seq, count = GENESIS_HASH, 1, 0
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                return VerifyResult(False, count, "line is not valid JSON", line_number)
            stored_hash = record.pop("hash", None)
            if record.get("seq") != expected_seq:
                found = record.get("seq")
                return VerifyResult(
                    False, count, f"expected seq {expected_seq}, found {found}", line_number
                )
            if record.get("prev_hash") != prev_hash:
                return VerifyResult(False, count, "prev_hash doesn't match", line_number)
            if _digest(record) != stored_hash:
                return VerifyResult(False, count, "record was modified", line_number)
            prev_hash, expected_seq, count = stored_hash, expected_seq + 1, count + 1
    return VerifyResult(True, count)


def make_audit_log(enabled: bool, path: Path) -> AuditLog | None:
    return AuditLog(path) if enabled else None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Audit log tools.")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("verify", help="Check the hash chain of an audit log.")
    check.add_argument("path", nargs="?", type=Path, default=Path("logs") / "audit.jsonl")
    args = parser.parse_args(argv)

    if not args.path.exists():
        parser.error(f"{args.path} doesn't exist yet.")
    result = verify(args.path)
    if result.ok:
        print(f"OK: {result.records} records, chain intact.")
        return
    print(f"BROKEN at line {result.line}: {result.error} ({result.records} good records before it)")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
