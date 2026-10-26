import json

import pytest

from app.audit import GENESIS_HASH, MAX_FIELD_CHARS, NULL_AUDIT, AuditLog, main, verify

FIXED_TS = "2026-10-01T09:00:00.000+00:00"


def write_events(path, count, start=0):
    scope = AuditLog(path, clock=lambda: FIXED_TS).scope(
        channel="chat", actor="customer:C1000", request_id="req-1"
    )
    for i in range(start, start + count):
        scope.event("note", n=i)


def read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_records_are_chained_and_stamped(tmp_path):
    path = tmp_path / "audit.jsonl"
    write_events(path, 2)
    first, second = read(path)
    assert (first["seq"], second["seq"]) == (1, 2)
    assert first["prev_hash"] == GENESIS_HASH
    assert second["prev_hash"] == first["hash"]
    assert first["request_id"] == "req-1"
    assert first["actor"] == "customer:C1000"
    assert first["event"] == "note"
    assert verify(path).ok


def test_verify_catches_an_edited_record(tmp_path):
    path = tmp_path / "audit.jsonl"
    write_events(path, 3)
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace('"n": 1', '"n": 99')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = verify(path)
    assert not result.ok
    assert result.line == 2
    assert "modified" in result.error


def test_verify_catches_a_deleted_middle_record(tmp_path):
    path = tmp_path / "audit.jsonl"
    write_events(path, 3)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    result = verify(path)
    assert not result.ok
    assert result.line == 2


def test_known_limit_T15_cutting_off_the_tail_still_verifies(tmp_path):
    # Documents a real weakness of a plain hash chain: dropping the newest records leaves a
    # valid chain. Fixing it needs an outside witness for the latest hash.
    path = tmp_path / "audit.jsonl"
    write_events(path, 3)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
    result = verify(path)
    assert result.ok
    assert result.records == 2


def test_a_new_logger_continues_the_existing_chain(tmp_path):
    path = tmp_path / "audit.jsonl"
    write_events(path, 2)
    write_events(path, 1, start=2)  # new AuditLog instance, same file
    records = read(path)
    assert [r["seq"] for r in records] == [1, 2, 3]
    assert records[2]["prev_hash"] == records[1]["hash"]
    assert verify(path).ok


def test_long_values_are_clipped(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.scope(channel="chat", actor="x").event("note", message="a" * (MAX_FIELD_CHARS + 50))
    message = read(path)[0]["message"]
    assert message.startswith("a" * MAX_FIELD_CHARS)
    assert message.endswith("[50 chars cut]")


def test_non_json_values_are_stored_as_text(tmp_path):
    path = tmp_path / "audit.jsonl"
    AuditLog(path).scope(channel="chat", actor="x").event("note", value=object.__new__(object))
    assert isinstance(read(path)[0]["value"], str)
    assert verify(path).ok


def test_null_audit_is_a_no_op():
    NULL_AUDIT.event("anything", detail="ignored")


def test_cli_verify(tmp_path, capsys):
    path = tmp_path / "audit.jsonl"
    write_events(path, 2)
    main(["verify", str(path)])
    assert "OK: 2 records" in capsys.readouterr().out

    path.write_text(path.read_text(encoding="utf-8").replace('"n": 0', '"n": 5'), encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["verify", str(path)])
    assert "BROKEN at line 1" in capsys.readouterr().out
