"""Tests for the write_file filesystem tool."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from muru.policy.risk import RiskTier
from muru.tools.base import ToolExecutionError
from muru.tools.filesystem.write_file import (
    MAX_UNDO_CAPTURE_BYTES,
    WriteFileArgs,
    _write_file_impl,
    write_file_tool,
)

# ----- Basic write (new file) -----


def test_creates_new_file(tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    with patch("muru.tools.filesystem.write_file.safe_resolve", return_value=target):
        result = _write_file_impl(WriteFileArgs(path=str(target), content="hi there"))

    assert result.success is True
    assert result.created is True
    assert result.previous_size_bytes is None
    assert result.previous_content is None
    assert target.read_text() == "hi there"
    assert result.size_bytes == len("hi there")


def test_creates_unicode_content(tmp_path: Path) -> None:
    target = tmp_path / "u.txt"
    text = "Hello \u4e16\u754c"  # "Hello 世界"
    with patch("muru.tools.filesystem.write_file.safe_resolve", return_value=target):
        result = _write_file_impl(WriteFileArgs(path=str(target), content=text))
    assert result.success is True
    assert target.read_text() == text


# ----- Overwrite (existing file) -----


def test_overwrites_existing_file_and_captures_previous(tmp_path: Path) -> None:
    target = tmp_path / "existing.txt"
    target.write_text("old content")

    with patch("muru.tools.filesystem.write_file.safe_resolve", return_value=target):
        result = _write_file_impl(WriteFileArgs(path=str(target), content="new content"))

    assert result.success is True
    assert result.created is False
    assert result.previous_size_bytes == len("old content")
    assert result.previous_content == "old content"
    assert result.previous_content_truncated is False
    assert target.read_text() == "new content"


def test_overwrite_skips_capture_for_large_files(tmp_path: Path) -> None:
    """Files larger than MAX_UNDO_CAPTURE_BYTES set previous_content=None."""
    target = tmp_path / "big.txt"
    # Write something that *reports* as huge via a stat patch
    target.write_text("small but lies about size")

    # Mock the stat to claim it's bigger than the cap
    original_stat = Path.stat

    def fake_stat(self: Path, *args: object, **kwargs: object) -> os.stat_result:
        real = original_stat(self, *args, **kwargs)
        if self == target:
            # Build a fake stat_result claiming a huge size
            values = list(real)
            values[6] = MAX_UNDO_CAPTURE_BYTES + 1  # st_size index
            return os.stat_result(values)
        return real

    with (
        patch("muru.tools.filesystem.write_file.safe_resolve", return_value=target),
        patch.object(Path, "stat", fake_stat),
    ):
        result = _write_file_impl(WriteFileArgs(path=str(target), content="replacement"))

    assert result.success is True
    assert result.previous_content is None
    assert result.previous_content_truncated is True
    assert result.previous_size_bytes == MAX_UNDO_CAPTURE_BYTES + 1


# ----- Atomicity (no temp file left over) -----


def test_no_tempfile_left_after_success(tmp_path: Path) -> None:
    target = tmp_path / "atomic.txt"
    with patch("muru.tools.filesystem.write_file.safe_resolve", return_value=target):
        _write_file_impl(WriteFileArgs(path=str(target), content="x"))

    # No .muru-tmp-* files should remain
    leftovers = list(tmp_path.glob("*.muru-tmp-*"))
    assert leftovers == [], f"Found leftover temp files: {leftovers}"


def test_tempfile_cleaned_up_on_rename_failure(tmp_path: Path) -> None:
    """If os.replace fails, the temp file must be cleaned up."""
    target = tmp_path / "atomic.txt"

    with (
        patch("muru.tools.filesystem.write_file.safe_resolve", return_value=target),
        patch(
            "muru.tools.filesystem.write_file.os.replace",
            side_effect=OSError("simulated rename failure"),
        ),
        pytest.raises(ToolExecutionError, match="Failed to write file"),
    ):
        _write_file_impl(WriteFileArgs(path=str(target), content="x"))

    leftovers = list(tmp_path.glob("*.muru-tmp-*"))
    assert leftovers == [], f"Temp file not cleaned up after failure: {leftovers}"


# ----- Safety / sandbox -----


def test_rejects_path_outside_sandbox(tmp_path: Path) -> None:
    from muru.tools.filesystem._safety import PathSecurityError

    with patch(
        "muru.tools.filesystem.write_file.safe_resolve",
        side_effect=PathSecurityError("not inside sandbox"),
    ):
        result = _write_file_impl(WriteFileArgs(path="/etc/passwd", content="x"))

    assert result.success is False
    assert "not inside sandbox" in result.message


def test_rejects_when_parent_directory_does_not_exist(tmp_path: Path) -> None:
    target = tmp_path / "no-such-dir" / "file.txt"
    with patch("muru.tools.filesystem.write_file.safe_resolve", return_value=target):
        result = _write_file_impl(WriteFileArgs(path=str(target), content="x"))

    assert result.success is False
    assert "Parent directory does not exist" in result.message
    # The file should NOT have been created
    assert not target.exists()


def test_rejects_when_target_is_a_directory(tmp_path: Path) -> None:
    target = tmp_path / "i_am_a_dir"
    target.mkdir()

    with patch("muru.tools.filesystem.write_file.safe_resolve", return_value=target):
        result = _write_file_impl(WriteFileArgs(path=str(target), content="x"))

    assert result.success is False
    assert "not a regular file" in result.message
    # The directory should still exist
    assert target.is_dir()


# ----- Tool wrapper integration -----


def test_tool_is_registered_as_tier_3() -> None:
    assert write_file_tool.risk_tier == RiskTier.HIGH_RISK


def test_tool_schema_includes_risk_tier_3() -> None:
    schema = write_file_tool.schema()
    assert schema["risk_tier"] == 3
    assert schema["risk_tier_label"] == "High risk"
