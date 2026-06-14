"""Tests for muru.policy.audit.undo."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from muru.policy.audit import AuditEntry, AuditWriter, UndoEngine


def _build_entry(
    tool_name: str,
    tool_result: dict[str, object],
    error: str | None = None,
) -> AuditEntry:
    return AuditEntry(
        intent="original intent",
        tool_name=tool_name,
        tool_args={},
        tool_result=tool_result,
        final_response="some response",
        error=error,
    )


def _make_engine(tmp_path: Path) -> UndoEngine:
    return UndoEngine(AuditWriter(tmp_path / "audit.jsonl"))


# ----- Refusals (preconditions) -----


def test_undo_refuses_already_undone(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    entry = _build_entry("write_file", {"success": True})
    entry = entry.model_copy(update={"undone": True})

    result = engine.undo(entry)
    assert result.success is False
    assert "already been undone" in result.message


def test_undo_refuses_errored_entry(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    entry = _build_entry("write_file", {"success": False}, error="ToolError: boom")

    result = engine.undo(entry)
    assert result.success is False
    assert "failed action" in result.message


def test_undo_refuses_unsuccessful_entry(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    entry = _build_entry("write_file", {"success": False})

    result = engine.undo(entry)
    assert result.success is False
    assert "did not succeed" in result.message


def test_undo_refuses_unknown_tool(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path)
    entry = _build_entry("mystery_tool", {"success": True})

    result = engine.undo(entry)
    assert result.success is False
    assert "No undo support" in result.message


# ----- write_file (create) undo -----


def test_undo_write_file_create_deletes_file(tmp_path: Path) -> None:
    target = tmp_path / "created.txt"
    target.write_text("hello world")

    engine = _make_engine(tmp_path)
    entry = _build_entry(
        "write_file",
        {
            "success": True,
            "path": str(target),
            "created": True,
            "size_bytes": len("hello world"),
        },
    )

    with patch("muru.policy.audit.undo.safe_resolve", return_value=target):
        result = engine.undo(entry)

    assert result.success is True
    assert not target.exists()
    assert result.undo_entry is not None
    assert result.undo_entry.tool_name == "undo_write_create"


def test_undo_write_file_create_refuses_when_file_changed(
    tmp_path: Path,
) -> None:
    target = tmp_path / "created.txt"
    target.write_text("user modified this since the original write")

    engine = _make_engine(tmp_path)
    entry = _build_entry(
        "write_file",
        {
            "success": True,
            "path": str(target),
            "created": True,
            "size_bytes": 11,  # original was 11 bytes; now it\'s much bigger
        },
    )

    with patch("muru.policy.audit.undo.safe_resolve", return_value=target):
        result = engine.undo(entry)

    assert result.success is False
    assert "has changed" in result.message
    # File still exists; we didn\'t delete it
    assert target.exists()


def test_undo_write_file_create_refuses_when_file_missing(
    tmp_path: Path,
) -> None:
    target = tmp_path / "ghost.txt"
    # Don\'t create it

    engine = _make_engine(tmp_path)
    entry = _build_entry(
        "write_file",
        {"success": True, "path": str(target), "created": True, "size_bytes": 5},
    )

    with patch("muru.policy.audit.undo.safe_resolve", return_value=target):
        result = engine.undo(entry)

    assert result.success is False
    assert "no longer exists" in result.message


# ----- write_file (overwrite) undo -----


def test_undo_write_file_overwrite_restores_previous_content(
    tmp_path: Path,
) -> None:
    target = tmp_path / "overwritten.txt"
    target.write_text("new content")

    engine = _make_engine(tmp_path)
    entry = _build_entry(
        "write_file",
        {
            "success": True,
            "path": str(target),
            "created": False,
            "size_bytes": len("new content"),
            "previous_content": "the original text",
            "previous_size_bytes": len("the original text"),
            "previous_content_truncated": False,
        },
    )

    with patch("muru.policy.audit.undo.safe_resolve", return_value=target):
        result = engine.undo(entry)

    assert result.success is True
    assert target.read_text() == "the original text"


def test_undo_write_file_overwrite_refuses_when_previous_truncated(
    tmp_path: Path,
) -> None:
    target = tmp_path / "big.txt"
    target.write_text("x")

    engine = _make_engine(tmp_path)
    entry = _build_entry(
        "write_file",
        {
            "success": True,
            "path": str(target),
            "created": False,
            "size_bytes": 1,
            "previous_content": None,
            "previous_content_truncated": True,
        },
    )

    with patch("muru.policy.audit.undo.safe_resolve", return_value=target):
        result = engine.undo(entry)

    assert result.success is False
    assert "too large to capture" in result.message


# ----- move_file undo -----


def test_undo_move_file_moves_back(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    # Currently the file lives at dst (it was moved there originally)
    dst.write_text("the moved content")

    engine = _make_engine(tmp_path)
    entry = _build_entry(
        "move_file",
        {
            "success": True,
            "source": str(src),
            "destination": str(dst),
            "size_bytes": len("the moved content"),
        },
    )

    def fake_resolve(p: str) -> Path:
        return src if p.endswith("src.txt") else dst

    with patch("muru.policy.audit.undo.safe_resolve", side_effect=fake_resolve):
        result = engine.undo(entry)

    assert result.success is True
    assert src.read_text() == "the moved content"
    assert not dst.exists()


def test_undo_move_refuses_when_source_path_occupied(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    dst.write_text("moved file")
    # Source path now has a different file
    src.write_text("something new the user created")

    engine = _make_engine(tmp_path)
    entry = _build_entry(
        "move_file",
        {"success": True, "source": str(src), "destination": str(dst)},
    )

    def fake_resolve(p: str) -> Path:
        return src if p.endswith("src.txt") else dst

    with patch("muru.policy.audit.undo.safe_resolve", side_effect=fake_resolve):
        result = engine.undo(entry)

    assert result.success is False
    assert "already exists" in result.message
    # User\'s file at src was NOT clobbered
    assert src.read_text() == "something new the user created"
    # dst still has the moved file
    assert dst.exists()


def test_undo_move_refuses_when_destination_missing(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    # Destination was deleted since the move

    engine = _make_engine(tmp_path)
    entry = _build_entry(
        "move_file",
        {"success": True, "source": str(src), "destination": str(dst)},
    )

    def fake_resolve(p: str) -> Path:
        return src if p.endswith("src.txt") else dst

    with patch("muru.policy.audit.undo.safe_resolve", side_effect=fake_resolve):
        result = engine.undo(entry)

    assert result.success is False
    assert "nothing exists" in result.message


# ----- delete_file undo -----


def test_undo_delete_file_recreates_file(tmp_path: Path) -> None:
    target = tmp_path / "deleted.txt"
    # Currently does not exist (it was deleted)

    engine = _make_engine(tmp_path)
    entry = _build_entry(
        "delete_file",
        {
            "success": True,
            "path": str(target),
            "size_bytes": len("recover me"),
            "deleted_content": "recover me",
            "deleted_content_truncated": False,
        },
    )

    with patch("muru.policy.audit.undo.safe_resolve", return_value=target):
        result = engine.undo(entry)

    assert result.success is True
    assert target.read_text() == "recover me"


def test_undo_delete_refuses_when_target_occupied(tmp_path: Path) -> None:
    """Critical safety: if a new file exists at the path, never clobber it."""
    target = tmp_path / "deleted.txt"
    target.write_text("user's new file at this path")

    engine = _make_engine(tmp_path)
    entry = _build_entry(
        "delete_file",
        {
            "success": True,
            "path": str(target),
            "deleted_content": "old stuff",
        },
    )

    with patch("muru.policy.audit.undo.safe_resolve", return_value=target):
        result = engine.undo(entry)

    assert result.success is False
    assert "already exists" in result.message
    # User\'s file untouched
    assert target.read_text() == "user's new file at this path"


def test_undo_delete_refuses_when_content_truncated(tmp_path: Path) -> None:
    target = tmp_path / "huge.bin"

    engine = _make_engine(tmp_path)
    entry = _build_entry(
        "delete_file",
        {
            "success": True,
            "path": str(target),
            "deleted_content": None,
            "deleted_content_truncated": True,
        },
    )

    with patch("muru.policy.audit.undo.safe_resolve", return_value=target):
        result = engine.undo(entry)

    assert result.success is False
    assert "too large to capture" in result.message


def test_undo_delete_refuses_when_binary_content_not_captured(
    tmp_path: Path,
) -> None:
    target = tmp_path / "binary.bin"

    engine = _make_engine(tmp_path)
    entry = _build_entry(
        "delete_file",
        {
            "success": True,
            "path": str(target),
            "deleted_content": None,
            "deleted_content_truncated": False,
        },
    )

    with patch("muru.policy.audit.undo.safe_resolve", return_value=target):
        result = engine.undo(entry)

    assert result.success is False
    assert "binary" in result.message.lower() or "symlink" in result.message.lower()


def test_undo_delete_refuses_when_parent_dir_missing(tmp_path: Path) -> None:
    target = tmp_path / "no-such-dir" / "file.txt"

    engine = _make_engine(tmp_path)
    entry = _build_entry(
        "delete_file",
        {
            "success": True,
            "path": str(target),
            "deleted_content": "stuff",
            "deleted_content_truncated": False,
        },
    )

    with patch("muru.policy.audit.undo.safe_resolve", return_value=target):
        result = engine.undo(entry)

    assert result.success is False
    assert "parent directory" in result.message.lower()
