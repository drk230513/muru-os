"""Tests for muru.tools.filesystem.read_file."""

from __future__ import annotations

from pathlib import Path

from muru.tools.filesystem.read_file import (
    ReadFileArgs,
    ReadFileResult,
    _read_file_impl,
)


def _invoke(args_dict: dict[str, object], sandbox: Path) -> ReadFileResult:
    import muru.tools.filesystem._safety as safety_mod

    original = safety_mod.get_default_sandbox_root
    safety_mod.get_default_sandbox_root = lambda: sandbox.resolve()
    try:
        args = ReadFileArgs(**args_dict)
        return _read_file_impl(args)
    finally:
        safety_mod.get_default_sandbox_root = original


def test_reads_text_file(tmp_path: Path) -> None:
    f = tmp_path / "hello.txt"
    f.write_text("Hello, world!")
    r = _invoke({"path": str(f)}, tmp_path)
    assert r.success
    assert r.content == "Hello, world!"
    assert r.size_bytes == 13
    assert not r.truncated


def test_truncates_at_max_bytes(tmp_path: Path) -> None:
    f = tmp_path / "big.txt"
    f.write_text("a" * 10_000)
    r = _invoke({"path": str(f), "max_bytes": 100}, tmp_path)
    assert r.success
    assert len(r.content) == 100
    assert r.size_bytes == 10_000
    assert r.truncated


def test_nonexistent_file_returns_failure(tmp_path: Path) -> None:
    r = _invoke({"path": str(tmp_path / "nope.txt")}, tmp_path)
    assert not r.success
    assert "does not exist" in r.message


def test_directory_returns_failure(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    r = _invoke({"path": str(sub)}, tmp_path)
    assert not r.success
    assert "directory" in r.message.lower()


def test_outside_sandbox_rejected(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("nope")
    r = _invoke({"path": str(outside)}, sandbox)
    assert not r.success
    assert "rejected" in r.message.lower()


def test_unicode_decode_error_falls_back(tmp_path: Path) -> None:
    f = tmp_path / "binary.dat"
    f.write_bytes(b"\xff\xfe\xfd\xfc")
    # Default encoding (utf-8) can't decode this
    r = _invoke({"path": str(f)}, tmp_path)
    assert not r.success
    assert "decode" in r.message.lower()
    # latin-1 should succeed
    r2 = _invoke({"path": str(f), "encoding": "latin-1"}, tmp_path)
    assert r2.success


def test_empty_file_succeeds(tmp_path: Path) -> None:
    f = tmp_path / "empty.txt"
    f.touch()
    r = _invoke({"path": str(f)}, tmp_path)
    assert r.success
    assert r.content == ""
    assert r.size_bytes == 0
