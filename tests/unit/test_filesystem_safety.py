"""Tests for muru.tools.filesystem._safety — path safety helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from muru.tools.filesystem._safety import PathSecurityError, safe_resolve


def test_safe_resolve_accepts_path_inside_sandbox(tmp_path: Path) -> None:
    file_path = tmp_path / "subdir" / "file.txt"
    file_path.parent.mkdir()
    file_path.write_text("hello")
    resolved = safe_resolve(str(file_path), sandbox_root=tmp_path)
    assert resolved == file_path.resolve()


def test_safe_resolve_rejects_path_outside_sandbox(tmp_path: Path) -> None:
    other_root = tmp_path / "other"
    other_root.mkdir()
    other_file = other_root / "file.txt"
    other_file.write_text("nope")

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    with pytest.raises(PathSecurityError, match="outside the allowed sandbox"):
        safe_resolve(str(other_file), sandbox_root=sandbox)


def test_safe_resolve_rejects_dotdot_traversal(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    # Try to escape via ..
    bad = str(sandbox / ".." / "outside")
    with pytest.raises(PathSecurityError):
        safe_resolve(bad, sandbox_root=sandbox)


def test_safe_resolve_rejects_empty_path(tmp_path: Path) -> None:
    with pytest.raises(PathSecurityError, match="Empty path"):
        safe_resolve("", sandbox_root=tmp_path)


def test_safe_resolve_rejects_whitespace_path(tmp_path: Path) -> None:
    with pytest.raises(PathSecurityError, match="Empty path"):
        safe_resolve("   ", sandbox_root=tmp_path)


def test_safe_resolve_handles_nonexistent_path(tmp_path: Path) -> None:
    """Nonexistent paths should resolve cleanly — the *security* check
    isn't about existence, just sandbox containment."""
    target = tmp_path / "does_not_exist_yet.txt"
    resolved = safe_resolve(str(target), sandbox_root=tmp_path)
    assert resolved == target.resolve()
