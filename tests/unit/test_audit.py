"""Tests for muru.policy.audit (entry schema + writer)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from muru.policy.audit import AuditEntry, AuditWriter

# ----- AuditEntry schema -----


def test_entry_has_auto_event_id() -> None:
    e1 = AuditEntry(intent="x", tool_name="t", tool_args={}, tool_result={}, final_response="y")
    e2 = AuditEntry(intent="x", tool_name="t", tool_args={}, tool_result={}, final_response="y")
    assert isinstance(e1.event_id, UUID)
    assert e1.event_id != e2.event_id, "event_id must be unique per entry"


def test_entry_timestamp_is_utc() -> None:
    e = AuditEntry(intent="x", tool_name="t", tool_args={}, tool_result={}, final_response="y")
    assert e.timestamp.tzinfo is not None
    assert e.timestamp.utcoffset() == datetime.now(UTC).utcoffset()


def test_entry_defaults_undone_false() -> None:
    e = AuditEntry(intent="x", tool_name="t", tool_args={}, tool_result={}, final_response="y")
    assert e.undone is False
    assert e.undone_at is None
    assert e.undone_by_event_id is None


def test_entry_jsonl_roundtrip() -> None:
    original = AuditEntry(
        intent="delete the file",
        tool_name="delete_file",
        tool_args={"path": "~/x.txt"},
        tool_result={
            "success": True,
            "path": "/home/user/x.txt",
            "size_bytes": 42,
            "deleted_content": "hello",
        },
        final_response="Deleted x.txt.",
    )
    line = original.to_jsonl()
    assert line.endswith("\n")

    parsed = AuditEntry.from_jsonl(line)
    assert parsed.event_id == original.event_id
    assert parsed.tool_name == "delete_file"
    assert parsed.tool_result["deleted_content"] == "hello"


def test_entry_jsonl_is_valid_json() -> None:
    e = AuditEntry(
        intent="x",
        tool_name="t",
        tool_args={"k": 1},
        tool_result={},
        final_response="y",
    )
    line = e.to_jsonl().rstrip("\n")
    # Should round-trip through stdlib json
    parsed = json.loads(line)
    assert parsed["tool_name"] == "t"
    assert parsed["tool_args"]["k"] == 1


# ----- AuditWriter -----


def test_writer_creates_parent_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "deep" / "audit.jsonl"
    # Parent does not yet exist
    assert not target.parent.exists()

    _ = AuditWriter(target)
    assert target.parent.exists()
    assert target.parent.is_dir()


def test_writer_appends_one_entry(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    writer = AuditWriter(target)

    entry = AuditEntry(
        intent="ls",
        tool_name="list_directory",
        tool_args={"path": "~"},
        tool_result={"success": True},
        final_response="here are the files",
    )
    writer.append(entry)

    assert target.exists()
    contents = target.read_text()
    assert contents.endswith("\n")
    parsed = AuditEntry.from_jsonl(contents.strip())
    assert parsed.event_id == entry.event_id


def test_writer_appends_multiple_entries(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    writer = AuditWriter(target)

    entries = [
        AuditEntry(
            intent=f"action {i}",
            tool_name="t",
            tool_args={"i": i},
            tool_result={},
            final_response=f"did {i}",
        )
        for i in range(3)
    ]
    for e in entries:
        writer.append(e)

    lines = target.read_text().splitlines()
    assert len(lines) == 3
    parsed_ids = [AuditEntry.from_jsonl(line).event_id for line in lines]
    assert parsed_ids == [e.event_id for e in entries]


def test_writer_each_entry_is_one_line(tmp_path: Path) -> None:
    """Critical for JSONL: even with nested content, one entry == one line."""
    target = tmp_path / "audit.jsonl"
    writer = AuditWriter(target)

    # Content with newlines inside - should still be one JSONL line
    entry = AuditEntry(
        intent="write a file with newlines",
        tool_name="write_file",
        tool_args={"path": "~/x.txt", "content": "line1\nline2\nline3"},
        tool_result={
            "success": True,
            "previous_content": "old\nlines\nhere",
        },
        final_response="Wrote 3 lines.",
    )
    writer.append(entry)

    lines = target.read_text().splitlines()
    assert len(lines) == 1, (
        f"Expected 1 JSONL line, got {len(lines)}. The embedded newlines "
        "should be escaped inside the JSON string, not break the line."
    )

    parsed = AuditEntry.from_jsonl(lines[0])
    assert parsed.tool_args["content"] == "line1\nline2\nline3"


def test_writer_mark_undone_returns_false_when_no_audit_file(
    tmp_path: Path,
) -> None:
    target = tmp_path / "audit.jsonl"
    writer = AuditWriter(target)

    # File doesn\'t exist yet - mark_undone should refuse
    marked = writer.mark_undone(event_id=str(uuid4()), undone_by_event_id=str(uuid4()))
    assert marked is False
    assert not target.exists()


def test_writer_mark_undone_writes_marker(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    writer = AuditWriter(target)

    # Write an original entry first so the file exists
    original = AuditEntry(
        intent="write",
        tool_name="write_file",
        tool_args={"path": "~/x.txt", "content": "data"},
        tool_result={"success": True, "path": "/home/u/x.txt"},
        final_response="ok",
    )
    writer.append(original)

    undo_event = uuid4()
    marked = writer.mark_undone(
        event_id=str(original.event_id),
        undone_by_event_id=str(undo_event),
    )
    assert marked is True

    lines = target.read_text().splitlines()
    assert len(lines) == 2

    marker = AuditEntry.from_jsonl(lines[1])
    assert marker.tool_name == "__undo_marker__"
    assert marker.tool_args["undoes_event_id"] == str(original.event_id)
    assert marker.event_id == undo_event


def test_writer_raises_oserror_on_disk_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "audit.jsonl"
    writer = AuditWriter(target)
    entry = AuditEntry(intent="x", tool_name="t", tool_args={}, tool_result={}, final_response="y")

    # Force open() to raise
    import builtins

    real_open = builtins.open

    def fake_open(*args: object, **kwargs: object) -> object:
        if str(target) in str(args[0]):
            raise OSError("simulated disk full")
        return real_open(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "open", fake_open)

    with pytest.raises(OSError, match="simulated disk full"):
        writer.append(entry)
