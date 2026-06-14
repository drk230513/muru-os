"""run_shell tool: execute a single allowlisted command in the user sandbox.

Risk tier: MEDIUM_RISK (2). User sees the full command + cwd in a
yellow Rich panel and approves with y/n. The strictest tier in the
project that still allows single-keystroke approval.

Security model:
- Allowlist only: 16 commands hardcoded. Anything else refused at
  pre-execution time, before any process is spawned.
- No shell metacharacters: arguments come in as a Python list and
  go to subprocess.run() with shell=False. Pipes, redirects,
  command chaining, and shell substitution are structurally
  impossible.
- cwd sandboxed: working directory must be inside the user\'s home
  directory (safe_resolve from filesystem tools).
- Output capped: 1MB stdout+stderr total. Excess truncated.
- Runtime capped: 30 seconds. Killed beyond.
- Stdin disabled: subprocess.DEVNULL. No piping content in.

This is the foundation for v0.6.x; future versions can extend the
allowlist on a per-project basis (Phase 2) or add restricted
pipelines once the threat model is better understood.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from pydantic import BaseModel, Field

from muru.policy.risk import RiskTier
from muru.tools.base import Tool, ToolExecutionError, ToolResult
from muru.tools.filesystem._safety import PathSecurityError, safe_resolve

# Allowlist. Tuple of (command, allowed_subcommands_or_None).
# None means any args are allowed; a tuple means the first arg must
# be in that set (used for git which has both safe + dangerous subcommands).
ALLOWLIST: dict[str, tuple[str, ...] | None] = {
    # File / text inspection
    "ls": None,
    "cat": None,
    "head": None,
    "tail": None,
    "wc": None,
    "grep": None,
    # System info
    "pwd": None,
    "df": None,
    "du": None,
    "ps": None,
    "free": None,
    "uptime": None,
    "whoami": None,
    "date": None,
    "echo": None,
    # Git, but only read-only subcommands. No commit/push/pull/reset/clean/checkout etc.
    "git": ("status", "log", "diff", "branch", "show", "remote", "describe", "blame"),
}

# Hard caps
MAX_OUTPUT_BYTES = 1_000_000  # 1 MB combined stdout+stderr
MAX_RUNTIME_SECONDS = 30


class RunShellArgs(BaseModel):
    """Arguments for run_shell."""

    command: str = Field(
        description=(
            "The command to run. Must be one of the allowlisted commands. "
            "No shell metacharacters (no pipes, redirects, semicolons, "
            "or command substitution) - the command is executed without "
            "a shell."
        ),
    )
    args: list[str] = Field(
        default_factory=list,
        description=(
            "Positional arguments to pass to the command. Each arg is "
            "passed literally; no shell interpretation. Example: for "
            "'ls -la ~/Downloads', command=\"ls\" and "
            'args=["-la", "~/Downloads"].'
        ),
    )
    cwd: str = Field(
        default="~",
        description=(
            "Working directory to run the command in. Use '~/' for home. "
            "Must be inside the user's home directory. Defaults to ~."
        ),
    )


class RunShellResult(ToolResult):
    """Result of run_shell."""

    command: str = ""
    args: list[str] = Field(default_factory=list)
    cwd: str = ""
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False
    timed_out: bool = False


def _is_allowed(command: str, args: list[str]) -> tuple[bool, str]:
    """Check if a command+args invocation is allowed.

    Returns (allowed, reason). reason is empty when allowed.
    """
    if command not in ALLOWLIST:
        return False, (
            f"Command {command!r} is not on the allowlist. "
            f"Allowed commands: {sorted(ALLOWLIST.keys())}."
        )
    # For commands that restrict subcommands (currently just git)
    subcommand_allowlist = ALLOWLIST[command]
    if subcommand_allowlist is not None:
        if not args:
            return False, (
                f"Command {command!r} requires a subcommand "
                f"(one of: {sorted(subcommand_allowlist)})."
            )
        if args[0] not in subcommand_allowlist:
            return False, (
                f"Subcommand {args[0]!r} is not allowed for {command!r}. "
                f"Allowed: {sorted(subcommand_allowlist)}."
            )
    # Defense in depth: scan args for shell metacharacters even though
    # we won\'t pass to a shell. If the LLM tries to sneak something
    # like "ls; rm -rf ~" as a single arg, refuse it.
    dangerous_chars = {";", "|", "&", "$", "`", ">", "<", "\n"}
    for arg in args:
        if any(c in arg for c in dangerous_chars):
            return False, (
                f"Argument {arg!r} contains a shell metacharacter. "
                "run_shell does not execute via a shell; metacharacters "
                "in args are refused as a safety check."
            )
    return True, ""


def _run_shell_impl(args: RunShellArgs) -> RunShellResult:
    # Validate command + args
    ok, reason = _is_allowed(args.command, args.args)
    if not ok:
        return RunShellResult(
            success=False,
            message=reason,
            command=args.command,
            args=list(args.args),
            cwd=args.cwd,
        )

    # Resolve cwd safely (must be inside user home)
    try:
        resolved_cwd = safe_resolve(args.cwd)
    except PathSecurityError as e:
        return RunShellResult(
            success=False,
            message=f"Working directory rejected: {e}",
            command=args.command,
            args=list(args.args),
            cwd=args.cwd,
        )
    if not resolved_cwd.is_dir():
        return RunShellResult(
            success=False,
            message=(f"Working directory is not a directory: {resolved_cwd}"),
            command=args.command,
            args=list(args.args),
            cwd=str(resolved_cwd),
        )

    # Verify the binary exists on PATH
    binary = shutil.which(args.command)
    if binary is None:
        return RunShellResult(
            success=False,
            message=(
                f"Command {args.command!r} is allowlisted but not "
                "installed on this system (not found on PATH)."
            ),
            command=args.command,
            args=list(args.args),
            cwd=str(resolved_cwd),
        )

    # Execute. We deliberately pass argv as a list (shell=False) so
    # no shell interprets anything. stdin is disabled.
    argv = [binary, *args.args]
    try:
        completed = subprocess.run(
            argv,
            cwd=str(resolved_cwd),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=MAX_RUNTIME_SECONDS,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        stdout_b = e.stdout or b""
        stderr_b = e.stderr or b""
        return RunShellResult(
            success=False,
            message=(
                f"Command timed out after {MAX_RUNTIME_SECONDS}s. Partial output captured below."
            ),
            command=args.command,
            args=list(args.args),
            cwd=str(resolved_cwd),
            exit_code=-1,
            stdout=_decode_with_limit(stdout_b)[0],
            stderr=_decode_with_limit(stderr_b)[0],
            truncated=False,
            timed_out=True,
        )
    except OSError as e:
        raise ToolExecutionError(f"Failed to launch {args.command}: {e}") from e

    stdout_text, stdout_truncated = _decode_with_limit(completed.stdout)
    stderr_text, stderr_truncated = _decode_with_limit(completed.stderr)
    truncated = stdout_truncated or stderr_truncated

    success = completed.returncode == 0
    message = (
        f"Exit {completed.returncode}." if not success else f"Ran {args.command} successfully."
    )
    if truncated:
        message += f" Output truncated at {MAX_OUTPUT_BYTES} bytes."

    return RunShellResult(
        success=success,
        message=message,
        command=args.command,
        args=list(args.args),
        cwd=str(resolved_cwd),
        exit_code=completed.returncode,
        stdout=stdout_text,
        stderr=stderr_text,
        truncated=truncated,
        timed_out=False,
    )


def _decode_with_limit(data: bytes) -> tuple[str, bool]:
    """Decode bytes to text with a cap. Returns (text, was_truncated)."""
    if data is None:
        return "", False
    if len(data) <= MAX_OUTPUT_BYTES:
        return data.decode("utf-8", errors="replace"), False
    return (
        data[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"),
        True,
    )


def _validate_run_shell(args: RunShellArgs) -> str | None:
    """Pre-execution validator: refuse non-allowlisted commands BEFORE
    the orchestrator fires the confirmation prompt. Fixes the v0.6.0
    UX bug where rm/sudo/etc. would reach the confirmation panel
    before being refused at execution time.
    """
    ok, reason = _is_allowed(args.command, args.args)
    if ok:
        return None
    return reason


run_shell_tool: Tool[RunShellArgs, RunShellResult] = Tool(
    name="run_shell",
    description=(
        "Run a shell command from a strict allowlist of safe, mostly "
        "read-only commands (ls, cat, df, ps, git status, etc.). No "
        "shell metacharacters allowed - one command + args only, no "
        "pipes or redirects. Working directory must be inside the "
        "user's home. Output capped at 1MB. Timeout 30s."
    ),
    args_model=RunShellArgs,
    result_model=RunShellResult,
    implementation=_run_shell_impl,
    risk_tier=RiskTier.MEDIUM_RISK,
    validator=_validate_run_shell,
)


__all__: list[Any] = [
    "ALLOWLIST",
    "MAX_OUTPUT_BYTES",
    "MAX_RUNTIME_SECONDS",
    "RunShellArgs",
    "RunShellResult",
    "run_shell_tool",
]
