"""Tests for muru.tools.filesystem.list_directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from muru.tools.filesystem.list_directory import (
    ListDirectoryArgs,
    ListDirectoryResult,
    _list_directory_impl,
)


@pytest.fixture
def sample_dir(tmp_path: Path) -> Path:
    """Create a directory with a few files and a subdirectory."""
    (tmp_path / "alpha.txt").write_text("a")
    (tmp_path / "beta.py").write_text("b" * 100)
    (tmp_path / "gamma.py").write_text("g" * 50)
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "delta.txt").write_text("d")
    return tmp_path


def _invoke(args_dict: dict[str, object], sandbox: Path) -> ListDirectoryResult:
    """Helper: build args, run impl with custom sandbox via monkey-patching."""
    # We need to override the sandbox root for tests. Since the tool uses
    # the default (~), we just pass paths that are inside our tmp_path
    # and assume tmp_path is inside ~. Pytest's tmp_path *is* inside the
    # user's temp dir, which is usually under /tmp on Linux — NOT inside ~.
    # So we need to use the sandbox_root override via safe_resolve directly.
    # For simplicity, we patch get_default_sandbox_root for these tests.
    import muru.tools.filesystem._safety as safety_mod

    original = safety_mod.get_default_sandbox_root
    safety_mod.get_default_sandbox_root = lambda: sandbox.resolve()
    try:
        args = ListDirectoryArgs(**args_dict)
        return _list_directory_impl(args)
    finally:
        safety_mod.get_default_sandbox_root = original


def test_lists_all_entries(sample_dir: Path) -> None:
    result = _invoke({"path": str(sample_dir)}, sample_dir)
    assert result.success is True
    names = {e.name for e in result.entries}
    assert names == {"alpha.txt", "beta.py", "gamma.py", "subdir"}


def test_pattern_filters_entries(sample_dir: Path) -> None:
    result = _invoke({"path": str(sample_dir), "pattern": "*.py"}, sample_dir)
    assert result.success is True
    names = {e.name for e in result.entries}
    assert names == {"beta.py", "gamma.py"}


def test_recursive_descends_into_subdirs(sample_dir: Path) -> None:
    result = _invoke(
        {"path": str(sample_dir), "recursive": True, "pattern": "*.txt"},
        sample_dir,
    )
    names = {e.name for e in result.entries}
    assert names == {"alpha.txt", "delta.txt"}


def test_max_entries_caps_results(sample_dir: Path) -> None:
    result = _invoke({"path": str(sample_dir), "max_entries": 2}, sample_dir)
    assert result.success is True
    assert len(result.entries) == 2
    assert result.total_found == 4
    assert result.truncated is True


def test_nonexistent_directory(sample_dir: Path) -> None:
    fake = sample_dir / "does_not_exist"
    result = _invoke({"path": str(fake)}, sample_dir)
    assert result.success is False
    assert "does not exist" in result.message


def test_path_outside_sandbox_rejected(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    result = _invoke({"path": str(outside)}, sandbox)
    assert result.success is False
    assert "rejected" in result.message.lower()


def test_file_path_rejected_as_not_a_directory(sample_dir: Path) -> None:
    file_path = sample_dir / "alpha.txt"
    result = _invoke({"path": str(file_path)}, sample_dir)
    assert result.success is False
    assert "not a directory" in result.message.lower()


def test_entries_have_metadata(sample_dir: Path) -> None:
    result = _invoke({"path": str(sample_dir), "pattern": "beta.py"}, sample_dir)
    assert len(result.entries) == 1
    entry = result.entries[0]
    assert entry.name == "beta.py"
    assert entry.type == "file"
    assert entry.size_bytes == 100  # We wrote "b" * 100
    assert entry.modified_iso is not None
