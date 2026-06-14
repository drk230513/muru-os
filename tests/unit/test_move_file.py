"""Tests for the move_file filesystem tool."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from muru.policy.risk import RiskTier
from muru.tools.base import ToolExecutionError
from muru.tools.filesystem.move_file import (
    MoveFileArgs,
    _move_file_impl,
    move_file_tool,
)

# ----- Basic move -----


def test_moves_file_to_new_location(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("the content")

    def fake_resolve(p: str) -> Path:
        return src if p.endswith("src.txt") else dst

    with patch("muru.tools.filesystem.move_file.safe_resolve", side_effect=fake_resolve):
        result = _move_file_impl(
            MoveFileArgs(source=str(src), destination=str(dst))
        )

    assert result.success is True
    assert not src.exists(), "Source should be removed after move"
    assert dst.read_text() == "the content"
    assert result.size_bytes == len("the content")


def test_moves_file_with_rename(tmp_path: Path) -> None:
    """Rename in same directory should also work."""
    src = tmp_path / "old.txt"
    dst = tmp_path / "new.txt"
    src.write_text("data")

    def fake_resolve(p: str) -> Path:
        return src if p.endswith("old.txt") else dst

    with patch("muru.tools.filesystem.move_file.safe_resolve", side_effect=fake_resolve):
        result = _move_file_impl(
            MoveFileArgs(source=str(src), destination=str(dst))
        )

    assert result.success is True
    assert dst.read_text() == "data"


# ----- Refusal: destination exists -----


def test_refuses_when_destination_exists(tmp_path: Path) -> None:
    """Critical safety guarantee: never silently overwrite a destination."""
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("new content")
    dst.write_text("existing content - do not overwrite")

    def fake_resolve(p: str) -> Path:
        return src if p.endswith("src.txt") else dst

    with patch("muru.tools.filesystem.move_file.safe_resolve", side_effect=fake_resolve):
        result = _move_file_impl(
            MoveFileArgs(source=str(src), destination=str(dst))
        )

    assert result.success is False
    assert "already exists" in result.message
    # Source is unchanged
    assert src.read_text() == "new content"
    # Destination is unchanged
    assert dst.read_text() == "existing content - do not overwrite"


# ----- Refusal: source problems -----


def test_refuses_when_source_does_not_exist(tmp_path: Path) -> None:
    src = tmp_path / "nonexistent.txt"
    dst = tmp_path / "dst.txt"

    def fake_resolve(p: str) -> Path:
        return src if p.endswith("nonexistent.txt") else dst

    with patch("muru.tools.filesystem.move_file.safe_resolve", side_effect=fake_resolve):
        result = _move_file_impl(
            MoveFileArgs(source=str(src), destination=str(dst))
        )

    assert result.success is False
    assert "does not exist" in result.message


def test_refuses_when_source_is_a_directory(tmp_path: Path) -> None:
    src = tmp_path / "i_am_a_dir"
    src.mkdir()
    dst = tmp_path / "dst"

    def fake_resolve(p: str) -> Path:
        return src if "i_am_a_dir" in p else dst

    with patch("muru.tools.filesystem.move_file.safe_resolve", side_effect=fake_resolve):
        result = _move_file_impl(
            MoveFileArgs(source=str(src), destination=str(dst))
        )

    assert result.success is False
    assert "not a regular file" in result.message
    # Directory is unchanged
    assert src.is_dir()


# ----- Refusal: destination parent missing -----


def test_refuses_when_destination_parent_missing(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    dst = tmp_path / "no-such-dir" / "dst.txt"
    src.write_text("data")

    def fake_resolve(p: str) -> Path:
        return src if p.endswith("src.txt") else dst

    with patch("muru.tools.filesystem.move_file.safe_resolve", side_effect=fake_resolve):
        result = _move_file_impl(
            MoveFileArgs(source=str(src), destination=str(dst))
        )

    assert result.success is False
    assert "parent directory does not exist" in result.message.lower()
    # Source unchanged
    assert src.read_text() == "data"


# ----- Safety / sandbox -----


def test_rejects_source_outside_sandbox(tmp_path: Path) -> None:
    from muru.tools.filesystem._safety import PathSecurityError

    with patch(
        "muru.tools.filesystem.move_file.safe_resolve",
        side_effect=PathSecurityError("not inside sandbox"),
    ):
        result = _move_file_impl(
            MoveFileArgs(source="/etc/passwd", destination="~/safe.txt")
        )

    assert result.success is False
    assert "Source rejected" in result.message
    assert "not inside sandbox" in result.message


def test_rejects_destination_outside_sandbox(tmp_path: Path) -> None:
    from muru.tools.filesystem._safety import PathSecurityError

    src = tmp_path / "src.txt"
    src.write_text("data")

    call_count = {"n": 0}

    def fake_resolve(p: str) -> Path:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return src
        raise PathSecurityError("destination outside sandbox")

    with patch("muru.tools.filesystem.move_file.safe_resolve", side_effect=fake_resolve):
        result = _move_file_impl(
            MoveFileArgs(source=str(src), destination="/etc/output.txt")
        )

    assert result.success is False
    assert "Destination rejected" in result.message
    # Source still exists (move was aborted before doing anything)
    assert src.exists()


# ----- shutil.move failure handling -----


def test_raises_tool_execution_error_on_move_failure(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("data")

    def fake_resolve(p: str) -> Path:
        return src if p.endswith("src.txt") else dst

    with (
        patch("muru.tools.filesystem.move_file.safe_resolve", side_effect=fake_resolve),
        patch(
            "muru.tools.filesystem.move_file.shutil.move",
            side_effect=OSError("simulated disk failure"),
        ),
        pytest.raises(ToolExecutionError, match="Failed to move file"),
    ):
        _move_file_impl(MoveFileArgs(source=str(src), destination=str(dst)))


# ----- Tool wrapper integration -----


def test_tool_registers_as_tier_3() -> None:
    assert move_file_tool.risk_tier == RiskTier.HIGH_RISK


def test_tool_schema_includes_risk_tier_3() -> None:
    schema = move_file_tool.schema()
    assert schema["risk_tier"] == 3
    assert schema["risk_tier_label"] == "High risk"
