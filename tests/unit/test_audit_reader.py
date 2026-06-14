"""Tests for muru.policy.audit.reader."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from muru.policy.audit import AuditEntry, AuditReader, AuditWriter


def _make_entry(
    tool_name: str = "list_directory",
    success: bool = True,
    error: str | None = None,
    intent: str = "do a thing",
) -> AuditEntry:
    return AuditEntry(
        intent=intent,
        tool_name=tool_name,
        tool_args={},
        tool_result={"success": success},
        final_response="ok",
        error=error,
    )


# ----- Reader handles missing/empty files -----


def test_reader_returns_empty_for_missing_file(tmp_path: Path) -> None:
    reader = AuditReader(tmp_path / "missing.jsonl")
    assert reader.exists() is False
    assert reader.all_entries() == []
    assert reader.recent() == []
    assert reader.get_by_event_id(uuid4()) is None
    assert reader.last_undoable() is None


def test_reader_returns_empty_for_empty_file(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    target.write_text("")

    reader = AuditReader(target)
    assert reader.exists() is True
    assert reader.all_entries() == []


def test_reader_skips_blank_lines(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    writer = AuditWriter(target)
    e1 = _make_entry()
    writer.append(e1)

    # Inject blank lines
    target.write_text(target.read_text() + "\n   \n\n")

    reader = AuditReader(target)
    all_entries = reader.all_entries()
    assert len(all_entries) == 1
    assert all_entries[0].event_id == e1.event_id


def test_reader_skips_malformed_lines(tmp_path: Path) -> None:
    """One bad line should not kill the whole audit log."""
    target = tmp_path / "audit.jsonl"
    writer = AuditWriter(target)
    e1 = _make_entry()
    writer.append(e1)

    # Inject garbage
    with open(target, "a") as f:
        f.write("THIS IS NOT JSON\n")

    e2 = _make_entry()
    writer.append(e2)

    reader = AuditReader(target)
    all_entries = reader.all_entries()
    # Good entries survived, bad one was logged + skipped
    assert len(all_entries) == 2
    assert {e.event_id for e in all_entries} == {e1.event_id, e2.event_id}


# ----- Order + recency -----


def test_all_entries_returns_oldest_first(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    writer = AuditWriter(target)
    entries = [_make_entry(intent=f"action {i}") for i in range(3)]
    for e in entries:
        writer.append(e)

    all_entries = AuditReader(target).all_entries()
    assert [e.intent for e in all_entries] == [
        "action 0",
        "action 1",
        "action 2",
    ]


def test_recent_returns_newest_first(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    writer = AuditWriter(target)
    entries = [_make_entry(intent=f"action {i}") for i in range(3)]
    for e in entries:
        writer.append(e)

    recent = AuditReader(target).recent(n=10)
    assert [e.intent for e in recent] == [
        "action 2",
        "action 1",
        "action 0",
    ]


def test_recent_respects_limit(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    writer = AuditWriter(target)
    for i in range(5):
        writer.append(_make_entry(intent=f"a{i}"))

    recent = AuditReader(target).recent(n=2)
    assert len(recent) == 2
    assert [e.intent for e in recent] == ["a4", "a3"]


# ----- Filtering -----


def test_recent_filters_by_tool_name(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    writer = AuditWriter(target)
    writer.append(_make_entry(tool_name="list_directory"))
    writer.append(_make_entry(tool_name="write_file"))
    writer.append(_make_entry(tool_name="write_file"))

    recent_writes = AuditReader(target).recent(n=10, tool_name="write_file")
    assert len(recent_writes) == 2
    assert all(e.tool_name == "write_file" for e in recent_writes)


# ----- Undo markers -----


def test_reader_marks_entries_undone_when_marker_present(
    tmp_path: Path,
) -> None:
    target = tmp_path / "audit.jsonl"
    writer = AuditWriter(target)
    original = _make_entry(tool_name="write_file", intent="write x")
    writer.append(original)

    # Write the undo marker
    undo_id = str(uuid4())
    writer.mark_undone(
        event_id=str(original.event_id),
        undone_by_event_id=undo_id,
    )

    reader = AuditReader(target)
    all_entries = reader.all_entries()
    # Marker entries are filtered out of the returned list
    assert len(all_entries) == 1
    assert all_entries[0].event_id == original.event_id
    assert all_entries[0].undone is True
    assert all_entries[0].undone_by_event_id == UUID(undo_id)
    assert all_entries[0].undone_at is not None


def test_recent_excludes_undone_when_requested(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    writer = AuditWriter(target)
    e1 = _make_entry(intent="kept")
    e2 = _make_entry(intent="undone")
    writer.append(e1)
    writer.append(e2)
    writer.mark_undone(event_id=str(e2.event_id), undone_by_event_id=str(uuid4()))

    recent = AuditReader(target).recent(n=10, exclude_undone=True)
    assert len(recent) == 1
    assert recent[0].intent == "kept"


# ----- get_by_event_id -----


def test_get_by_event_id_finds_existing(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    writer = AuditWriter(target)
    e1 = _make_entry()
    e2 = _make_entry()
    writer.append(e1)
    writer.append(e2)

    reader = AuditReader(target)
    found = reader.get_by_event_id(e2.event_id)
    assert found is not None
    assert found.event_id == e2.event_id


def test_get_by_event_id_returns_none_when_missing(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    writer = AuditWriter(target)
    writer.append(_make_entry())

    reader = AuditReader(target)
    assert reader.get_by_event_id(uuid4()) is None


# ----- last_undoable -----


def test_last_undoable_returns_most_recent_success(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    writer = AuditWriter(target)
    e1 = _make_entry(intent="first")
    e2 = _make_entry(intent="last")
    writer.append(e1)
    writer.append(e2)

    last = AuditReader(target).last_undoable()
    assert last is not None
    assert last.intent == "last"


def test_last_undoable_skips_errored_entries(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    writer = AuditWriter(target)
    e1 = _make_entry(intent="good")
    e2 = _make_entry(intent="failed", error="planner blew up", success=False)
    writer.append(e1)
    writer.append(e2)

    last = AuditReader(target).last_undoable()
    assert last is not None
    assert last.intent == "good"


def test_last_undoable_skips_already_undone(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    writer = AuditWriter(target)
    e1 = _make_entry(intent="keep")
    e2 = _make_entry(intent="already undone")
    writer.append(e1)
    writer.append(e2)
    writer.mark_undone(event_id=str(e2.event_id), undone_by_event_id=str(uuid4()))

    last = AuditReader(target).last_undoable()
    assert last is not None
    assert last.intent == "keep"


def test_last_undoable_returns_none_when_audit_empty(tmp_path: Path) -> None:
    target = tmp_path / "missing.jsonl"
    assert AuditReader(target).last_undoable() is None
