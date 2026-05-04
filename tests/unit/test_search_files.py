"""Tests for muru.tools.filesystem.search_files."""

from __future__ import annotations

from pathlib import Path

import pytest

from muru.tools.filesystem.search_files import (
    SearchFilesArgs,
    SearchFilesResult,
    _search_files_impl,
)


def _invoke(args_dict: dict[str, object], sandbox: Path) -> SearchFilesResult:
    import muru.tools.filesystem._safety as safety_mod

    original = safety_mod.get_default_sandbox_root
    safety_mod.get_default_sandbox_root = lambda: sandbox.resolve()
    try:
        args = SearchFilesArgs(**args_dict)
        return _search_files_impl(args)
    finally:
        safety_mod.get_default_sandbox_root = original


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a sample directory tree."""
    (tmp_path / "alpha.py").write_text("import os\nprint('hello')")
    (tmp_path / "beta.py").write_text("def add(a, b):\n    return a + b")
    (tmp_path / "readme.md").write_text("This is the readme.\nFind me.")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.py").write_text("# deep file\nprint('deep hello')")
    # Noisy dir that should be skipped
    git = tmp_path / ".git"
    git.mkdir()
    (git / "junk.py").write_text("should be skipped")
    return tmp_path


def test_search_by_name_pattern(project_dir: Path) -> None:
    r = _invoke({"directory": str(project_dir), "name_pattern": "*.py"}, project_dir)
    assert r.success
    names = {m.name for m in r.matches}
    assert names == {"alpha.py", "beta.py", "deep.py"}  # .git dir skipped


def test_search_by_content(project_dir: Path) -> None:
    r = _invoke(
        {"directory": str(project_dir), "content_pattern": "hello"},
        project_dir,
    )
    assert r.success
    names = {m.name for m in r.matches}
    assert "alpha.py" in names
    assert "deep.py" in names
    assert "beta.py" not in names  # no 'hello' in beta


def test_search_combines_name_and_content(project_dir: Path) -> None:
    """Filter by name, then within those, filter by content."""
    r = _invoke(
        {
            "directory": str(project_dir),
            "name_pattern": "*.py",
            "content_pattern": "deep",
        },
        project_dir,
    )
    assert r.success
    names = {m.name for m in r.matches}
    assert names == {"deep.py"}


def test_case_insensitive_by_default(project_dir: Path) -> None:
    r = _invoke(
        {"directory": str(project_dir), "content_pattern": "FIND ME"},
        project_dir,
    )
    assert r.success
    assert any(m.name == "readme.md" for m in r.matches)


def test_case_sensitive_when_requested(project_dir: Path) -> None:
    r = _invoke(
        {
            "directory": str(project_dir),
            "content_pattern": "FIND ME",
            "case_sensitive": True,
        },
        project_dir,
    )
    assert r.success
    assert not any(m.name == "readme.md" for m in r.matches)


def test_returns_matching_lines(project_dir: Path) -> None:
    r = _invoke(
        {"directory": str(project_dir), "content_pattern": "hello"},
        project_dir,
    )
    alpha_match = next(m for m in r.matches if m.name == "alpha.py")
    assert any("hello" in line for line in alpha_match.matching_lines)


def test_max_results_caps_output(project_dir: Path) -> None:
    r = _invoke(
        {"directory": str(project_dir), "name_pattern": "*.py", "max_results": 2},
        project_dir,
    )
    assert r.success
    assert len(r.matches) == 2
    assert r.truncated


def test_invalid_regex_returns_failure(project_dir: Path) -> None:
    r = _invoke(
        {"directory": str(project_dir), "content_pattern": "[unclosed"},
        project_dir,
    )
    assert not r.success
    assert "regex" in r.message.lower()


def test_no_patterns_returns_failure(project_dir: Path) -> None:
    r = _invoke({"directory": str(project_dir)}, project_dir)
    assert not r.success
    assert "at least one" in r.message.lower()


def test_skips_noise_directories(project_dir: Path) -> None:
    """Make sure .git etc are not searched."""
    r = _invoke(
        {"directory": str(project_dir), "name_pattern": "junk.py"},
        project_dir,
    )
    assert r.success
    # junk.py is in .git, which is in SKIP_DIRS
    assert len(r.matches) == 0
