"""Path-safety helpers for filesystem tools.

All filesystem tools must use safe_resolve() to convert a user-provided
path string into a real filesystem Path. This guarantees:

    1. ~ is expanded (~ → /home/me)
    2. Symlinks are resolved (so attackers can't use ~/foo → /etc/shadow)
    3. The resolved path is inside the configured sandbox root

The leading underscore in the filename means "this is a module-internal
helper — please don't import it from outside the filesystem package."
"""

from __future__ import annotations

from pathlib import Path

from muru.utils.logging import get_logger

log = get_logger(__name__)


class PathSecurityError(Exception):
    """Raised when a user-provided path tries to escape the sandbox."""


def get_default_sandbox_root() -> Path:
    """Return the default sandbox root: the user's home directory.

    Future versions (Phase 2+) will read this from config so users can
    add additional allowed roots (e.g., /mnt/data).
    """
    return Path.home().resolve()


def safe_resolve(
    user_path: str,
    sandbox_root: Path | None = None,
) -> Path:
    """Resolve a user-provided path string into an absolute, safe Path.

    Args:
        user_path: The raw path string from the user/LLM. May contain
            ~, relative components, or symlinks.
        sandbox_root: The directory the result must live inside. Defaults
            to the user's home directory.

    Returns:
        A resolved absolute Path that is guaranteed to be inside sandbox_root.

    Raises:
        PathSecurityError: If the resolved path escapes the sandbox,
            or if the input is structurally invalid.
    """
    if sandbox_root is None:
        sandbox_root = get_default_sandbox_root()

    sandbox_root = sandbox_root.resolve()

    # Reject obviously bad inputs early
    if not user_path or not user_path.strip():
        raise PathSecurityError("Empty path is not allowed.")

    # Expand ~ to home directory
    expanded = Path(user_path).expanduser()

    # Resolve symlinks and relative components.
    # strict=False: don't require the path to exist (we want to handle
    # "file doesn't exist" later as a normal error, not a security error).
    try:
        resolved = expanded.resolve(strict=False)
    except (OSError, RuntimeError) as e:
        raise PathSecurityError(f"Could not resolve path {user_path!r}: {e}") from e

    # The big check: is the resolved path inside the sandbox root?
    # We use Path.is_relative_to() (Python 3.9+).
    if not resolved.is_relative_to(sandbox_root):
        log.warning(
            "path_security_violation",
            user_path=user_path,
            resolved=str(resolved),
            sandbox_root=str(sandbox_root),
        )
        raise PathSecurityError(
            f"Path {user_path!r} resolves to {resolved}, which is outside "
            f"the allowed sandbox ({sandbox_root})."
        )

    return resolved


__all__ = ["PathSecurityError", "get_default_sandbox_root", "safe_resolve"]
