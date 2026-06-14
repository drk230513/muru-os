"""Tests for the run_shell tool.

Coverage priorities (in order of importance):
1. Refusals - allowlist, subcommand allowlist, metacharacters, sandbox
2. Success cases - the tool actually works when used correctly
3. Limits - output truncation, timeout
4. Tool integration - tier, schema, registration
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from muru.policy.risk import RiskTier
from muru.tools.base import ToolExecutionError
from muru.tools.shell.run_shell import (
    ALLOWLIST,
    MAX_OUTPUT_BYTES,
    RunShellArgs,
    _run_shell_impl,
    run_shell_tool,
)

# ============================
# Allowlist refusals
# ============================


def test_refuses_command_not_on_allowlist() -> None:
    result = _run_shell_impl(RunShellArgs(command="rm", args=["-rf", "~/"]))
    assert result.success is False
    assert "not on the allowlist" in result.message
    assert "rm" in result.message


def test_refuses_sudo() -> None:
    """sudo elevates privileges - must never be allowlisted."""
    assert "sudo" not in ALLOWLIST
    result = _run_shell_impl(RunShellArgs(command="sudo", args=["ls"]))
    assert result.success is False


def test_refuses_bash() -> None:
    """bash with -c is the universal shell-escape vector."""
    assert "bash" not in ALLOWLIST
    result = _run_shell_impl(RunShellArgs(command="bash", args=["-c", "ls"]))
    assert result.success is False


def test_refuses_python() -> None:
    """Interpreter access defeats the whole sandbox."""
    assert "python" not in ALLOWLIST
    assert "python3" not in ALLOWLIST


def test_refuses_curl() -> None:
    """Network calls out of scope."""
    assert "curl" not in ALLOWLIST
    assert "wget" not in ALLOWLIST


# ============================
# Git subcommand allowlist
# ============================


def test_refuses_git_push() -> None:
    result = _run_shell_impl(RunShellArgs(command="git", args=["push"]))
    assert result.success is False
    assert "push" in result.message
    assert "not allowed" in result.message.lower()


def test_refuses_git_commit() -> None:
    result = _run_shell_impl(RunShellArgs(command="git", args=["commit", "-am", "x"]))
    assert result.success is False


def test_refuses_git_reset() -> None:
    result = _run_shell_impl(RunShellArgs(command="git", args=["reset", "--hard"]))
    assert result.success is False


def test_refuses_git_clean() -> None:
    result = _run_shell_impl(RunShellArgs(command="git", args=["clean", "-fd"]))
    assert result.success is False


def test_refuses_git_checkout() -> None:
    result = _run_shell_impl(RunShellArgs(command="git", args=["checkout", "."]))
    assert result.success is False


def test_refuses_git_with_no_subcommand() -> None:
    result = _run_shell_impl(RunShellArgs(command="git", args=[]))
    assert result.success is False
    assert "subcommand" in result.message.lower()


def test_allows_git_status() -> None:
    """git status is read-only and explicitly allowlisted."""
    # We mock subprocess to avoid actually running git in tests
    with patch("muru.tools.shell.run_shell.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = b""
        mock_run.return_value.stderr = b""
        result = _run_shell_impl(RunShellArgs(command="git", args=["status"]))
    assert result.success is True


def test_allows_git_log() -> None:
    with patch("muru.tools.shell.run_shell.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = b""
        mock_run.return_value.stderr = b""
        result = _run_shell_impl(RunShellArgs(command="git", args=["log", "--oneline"]))
    assert result.success is True


# ============================
# Metacharacter defense
# ============================


@pytest.mark.parametrize(
    "bad_arg",
    [
        "foo; rm -rf /",
        "foo | bash",
        "foo & evil",
        "foo > /etc/passwd",
        "foo < /etc/shadow",
        "$(rm -rf ~)",
        "`whoami`",
        "foo\nrm",  # literal newline embedded
        "&& evil",
        "|| evil",
    ],
)
def test_refuses_shell_metacharacters_in_args(bad_arg: str) -> None:
    """Defense in depth: even though we exec without a shell, refuse
    arguments containing shell metacharacters. If the LLM tries to
    sneak compound commands as a single arg, we catch it.
    """
    result = _run_shell_impl(RunShellArgs(command="echo", args=[bad_arg]))
    assert result.success is False
    assert "metacharacter" in result.message.lower()


def test_allows_normal_arguments() -> None:
    """Sanity: normal args without metacharacters work."""
    result = _run_shell_impl(RunShellArgs(command="echo", args=["hello", "world", "--verbose"]))
    assert result.success is True


# ============================
# Sandbox - cwd validation
# ============================


def test_refuses_cwd_outside_sandbox() -> None:
    from muru.tools.filesystem._safety import PathSecurityError

    with patch(
        "muru.tools.shell.run_shell.safe_resolve",
        side_effect=PathSecurityError("outside sandbox"),
    ):
        result = _run_shell_impl(RunShellArgs(command="ls", cwd="/etc"))
    assert result.success is False
    assert "rejected" in result.message.lower()
    assert "outside sandbox" in result.message


def test_refuses_cwd_that_is_a_file(tmp_path: Path) -> None:
    target = tmp_path / "not_a_dir.txt"
    target.write_text("hello")

    with patch("muru.tools.shell.run_shell.safe_resolve", return_value=target):
        result = _run_shell_impl(RunShellArgs(command="ls", cwd=str(target)))
    assert result.success is False
    assert "not a directory" in result.message.lower()


# ============================
# Missing binary
# ============================


def test_refuses_if_binary_not_on_path() -> None:
    """Command on allowlist but the binary isn\'t installed."""
    with patch("muru.tools.shell.run_shell.shutil.which", return_value=None):
        result = _run_shell_impl(RunShellArgs(command="ls"))
    assert result.success is False
    assert "not installed" in result.message


# ============================
# Output limits + timeout
# ============================


def test_truncates_large_output() -> None:
    """Output exceeding MAX_OUTPUT_BYTES is truncated and flagged."""
    huge = b"x" * (MAX_OUTPUT_BYTES + 100)
    with patch("muru.tools.shell.run_shell.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = huge
        mock_run.return_value.stderr = b""
        result = _run_shell_impl(RunShellArgs(command="cat"))

    assert result.truncated is True
    assert len(result.stdout) == MAX_OUTPUT_BYTES
    assert "truncated" in result.message.lower()


def test_timeout_marks_result(tmp_path: Path) -> None:
    """A timeout returns success=False with timed_out=True."""
    import subprocess as sp

    # Patch subprocess.run to raise TimeoutExpired
    timeout_error = sp.TimeoutExpired(cmd=["ls"], timeout=30.0, output=b"partial", stderr=b"")
    with patch("muru.tools.shell.run_shell.subprocess.run", side_effect=timeout_error):
        result = _run_shell_impl(RunShellArgs(command="ls"))

    assert result.success is False
    assert result.timed_out is True
    assert result.stdout == "partial"
    assert "timed out" in result.message.lower()


def test_os_error_during_exec_raises(tmp_path: Path) -> None:
    """If subprocess.run raises an unrelated OSError, propagate as ToolExecutionError."""
    with (
        patch(
            "muru.tools.shell.run_shell.subprocess.run",
            side_effect=OSError("simulated exec failure"),
        ),
        pytest.raises(ToolExecutionError, match="Failed to launch"),
    ):
        _run_shell_impl(RunShellArgs(command="ls"))


# ============================
# Exit code handling
# ============================


def test_non_zero_exit_marks_success_false() -> None:
    """A command that runs but exits non-zero is success=False."""
    with patch("muru.tools.shell.run_shell.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = b""
        mock_run.return_value.stderr = b"error: something"
        result = _run_shell_impl(RunShellArgs(command="grep", args=["pattern"]))
    assert result.success is False
    assert result.exit_code == 1
    assert "Exit 1" in result.message


# ============================
# Tool wrapper integration
# ============================


def test_tool_is_tier_2_medium_risk() -> None:
    """v0.6.0 ships shell as Tier 2 (Option A)."""
    assert run_shell_tool.risk_tier == RiskTier.MEDIUM_RISK


def test_tool_does_not_auto_execute() -> None:
    """Tier 2 must require user confirmation."""
    assert run_shell_tool.risk_tier.auto_execute is False


def test_tool_schema_includes_risk_tier_2() -> None:
    schema = run_shell_tool.schema()
    assert schema["risk_tier"] == 2


def test_tool_is_registered_in_registry() -> None:
    """Importing the shell package auto-registers run_shell."""
    from muru.tools import shell  # noqa: F401
    from muru.tools.registry import registry

    assert "run_shell" in registry.list_names()
