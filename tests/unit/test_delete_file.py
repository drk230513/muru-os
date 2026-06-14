"""Tests for the delete_file filesystem tool."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from muru.policy.risk import RiskTier
from muru.tools.base import ToolExecutionError
from muru.tools.filesystem.delete_file import (
    MAX_UNDO_CAPTURE_BYTES,
    DeleteFileArgs,
    _delete_file_impl,
    delete_file_tool,
)

# ----- Basic delete -----


def test_deletes_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "to-delete.txt"
    target.write_text("delete me")

    with patch("muru.tools.filesystem.delete_file.safe_resolve", return_value=target):
        result = _delete_file_impl(DeleteFileArgs(path=str(target)))

    assert result.success is True
    assert not target.exists()
    assert result.size_bytes == len("delete me")


def test_captures_content_for_small_files(tmp_path: Path) -> None:
    """v0.5.0 undo support: small file content is captured in result."""
    target = tmp_path / "important.txt"
    target.write_text("crucial data we might want back")

    with patch("muru.tools.filesystem.delete_file.safe_resolve", return_value=target):
        result = _delete_file_impl(DeleteFileArgs(path=str(target)))

    assert result.success is True
    assert result.deleted_content == "crucial data we might want back"
    assert result.deleted_content_truncated is False


def test_skips_content_capture_for_large_files(tmp_path: Path) -> None:
    """Files > MAX_UNDO_CAPTURE_BYTES are deleted but no content captured."""
    target = tmp_path / "big.bin"
    target.write_text("placeholder")

    original_stat = Path.stat

    def fake_stat(self: Path, *args: object, **kwargs: object) -> os.stat_result:
        real = original_stat(self, *args, **kwargs)
        if self == target:
            values = list(real)
            values[6] = MAX_UNDO_CAPTURE_BYTES + 1  # st_size
            return os.stat_result(values)
        return real

    with (
        patch("muru.tools.filesystem.delete_file.safe_resolve", return_value=target),
        patch.object(Path, "stat", fake_stat),
    ):
        result = _delete_file_impl(DeleteFileArgs(path=str(target)))

    assert result.success is True
    assert result.deleted_content is None
    assert result.deleted_content_truncated is True
    assert not target.exists()


def test_skips_content_capture_for_binary_files(tmp_path: Path) -> None:
    target = tmp_path / "binary.dat"
    # Write bytes that aren't valid UTF-8
    target.write_bytes(b"\xff\xfe\xfd not text")

    with patch("muru.tools.filesystem.delete_file.safe_resolve", return_value=target):
        result = _delete_file_impl(DeleteFileArgs(path=str(target)))

    assert result.success is True
    assert result.deleted_content is None  # binary -> no capture
    assert not target.exists()


# ----- Refusal cases -----


def test_refuses_nonexistent_file(tmp_path: Path) -> None:
    target = tmp_path / "ghost.txt"
    with patch("muru.tools.filesystem.delete_file.safe_resolve", return_value=target):
        result = _delete_file_impl(DeleteFileArgs(path=str(target)))

    assert result.success is False
    assert "does not exist" in result.message


def test_refuses_directories(tmp_path: Path) -> None:
    target = tmp_path / "i_am_a_dir"
    target.mkdir()

    with patch("muru.tools.filesystem.delete_file.safe_resolve", return_value=target):
        result = _delete_file_impl(DeleteFileArgs(path=str(target)))

    assert result.success is False
    assert "directory" in result.message.lower()
    assert "refuses" in result.message.lower() or "refuse" in result.message.lower()
    # Directory must still exist
    assert target.is_dir()


def test_refuses_path_outside_sandbox(tmp_path: Path) -> None:
    from muru.tools.filesystem._safety import PathSecurityError

    with patch(
        "muru.tools.filesystem.delete_file.safe_resolve",
        side_effect=PathSecurityError("outside sandbox"),
    ):
        result = _delete_file_impl(DeleteFileArgs(path="/etc/passwd"))

    assert result.success is False
    assert "outside sandbox" in result.message


# ----- Symlink handling -----


def test_deletes_symlink_not_target(tmp_path: Path) -> None:
    """A symlink to a real file: delete the link, leave target intact."""
    real_file = tmp_path / "real.txt"
    real_file.write_text("important content")

    link = tmp_path / "link.txt"
    link.symlink_to(real_file)

    assert link.is_symlink()
    assert real_file.exists()

    with patch("muru.tools.filesystem.delete_file.safe_resolve", return_value=link):
        result = _delete_file_impl(DeleteFileArgs(path=str(link)))

    assert result.success is True
    # Symlink removed
    assert not link.is_symlink()
    # Target untouched
    assert real_file.exists()
    assert real_file.read_text() == "important content"


def test_deletes_dangling_symlink(tmp_path: Path) -> None:
    """A symlink whose target does not exist: still delete the link."""
    link = tmp_path / "dangling.txt"
    link.symlink_to(tmp_path / "nonexistent-target.txt")

    assert link.is_symlink()

    with patch("muru.tools.filesystem.delete_file.safe_resolve", return_value=link):
        result = _delete_file_impl(DeleteFileArgs(path=str(link)))

    assert result.success is True
    assert not link.is_symlink()


# ----- Failure handling -----


def test_raises_tool_execution_error_on_unlink_failure(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("data")

    with (
        patch("muru.tools.filesystem.delete_file.safe_resolve", return_value=target),
        patch.object(Path, "unlink", side_effect=OSError("simulated unlink failure")),
        pytest.raises(ToolExecutionError, match="Failed to delete file"),
    ):
        _delete_file_impl(DeleteFileArgs(path=str(target)))


# ----- Tool wrapper integration -----


def test_tool_registers_as_tier_4_critical() -> None:
    assert delete_file_tool.risk_tier == RiskTier.CRITICAL


def test_tool_tier_does_not_auto_execute() -> None:
    """Critical tools MUST require user confirmation."""
    assert delete_file_tool.risk_tier.auto_execute is False


def test_tool_schema_includes_risk_tier_4() -> None:
    schema = delete_file_tool.schema()
    assert schema["risk_tier"] == 4
    assert schema["risk_tier_label"] == "Critical"
