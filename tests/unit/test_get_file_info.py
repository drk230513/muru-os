"""Tests for muru.tools.filesystem.get_file_info."""

from __future__ import annotations

from pathlib import Path

from muru.tools.filesystem.get_file_info import (
    GetFileInfoArgs,
    GetFileInfoResult,
    _get_file_info_impl,
)


def _invoke(args_dict: dict[str, object], sandbox: Path) -> GetFileInfoResult:
    import muru.tools.filesystem._safety as safety_mod

    original = safety_mod.get_default_sandbox_root
    safety_mod.get_default_sandbox_root = lambda: sandbox.resolve()
    try:
        args = GetFileInfoArgs(**args_dict)
        return _get_file_info_impl(args)
    finally:
        safety_mod.get_default_sandbox_root = original


def test_file_info_basic(tmp_path: Path) -> None:
    f = tmp_path / "data.txt"
    f.write_text("hello")
    r = _invoke({"path": str(f)}, tmp_path)
    assert r.success
    assert r.type == "file"
    assert r.size_bytes == 5
    assert r.modified_iso is not None
    assert r.permissions_symbolic is not None
    assert r.permissions_symbolic.startswith("-")


def test_directory_info(tmp_path: Path) -> None:
    sub = tmp_path / "subdir"
    sub.mkdir()
    r = _invoke({"path": str(sub)}, tmp_path)
    assert r.success
    assert r.type == "directory"
    assert r.size_bytes is None
    assert r.permissions_symbolic is not None
    assert r.permissions_symbolic.startswith("d")


def test_mime_type_for_known_extensions(tmp_path: Path) -> None:
    f = tmp_path / "doc.html"
    f.write_text("<html></html>")
    r = _invoke({"path": str(f)}, tmp_path)
    assert r.success
    assert r.mime_type == "text/html"


def test_hash_when_requested(tmp_path: Path) -> None:
    f = tmp_path / "data.txt"
    f.write_text("hello")
    r = _invoke({"path": str(f), "include_hash": True}, tmp_path)
    assert r.success
    assert r.sha256 is not None
    # SHA-256 of "hello" is well-known
    assert r.sha256 == ("2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")


def test_hash_skipped_when_not_requested(tmp_path: Path) -> None:
    f = tmp_path / "data.txt"
    f.write_text("hello")
    r = _invoke({"path": str(f)}, tmp_path)
    assert r.sha256 is None


def test_nonexistent_path_returns_failure(tmp_path: Path) -> None:
    r = _invoke({"path": str(tmp_path / "nope")}, tmp_path)
    assert not r.success


def test_outside_sandbox_rejected(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("nope")
    r = _invoke({"path": str(outside)}, sandbox)
    assert not r.success
