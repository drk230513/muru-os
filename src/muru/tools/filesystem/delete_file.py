"""delete_file tool: delete a single file within the user sandbox.

Risk tier: CRITICAL (4). The strictest UX in the confirmation engine:
- Red Rich panel
- 5-second mandatory cooldown before accepting input
- User must type the exact tool name ("delete_file") to confirm

Deletion is irreversible without undo support (v0.5.0). For files
smaller than MAX_UNDO_CAPTURE_BYTES, the tool reads the content into
the result so v0.5.0's audit log can recreate the file. Larger files
are deleted with deleted_content=None and noted as not undoable.

Safety guarantees in v0.4.0:
- Sandboxed to user home via safe_resolve()
- Refuses to delete directories (v0.4.0 scope - dirs need different UX)
- Refuses to delete non-regular files (sockets, devices, fifos)
- For symlinks: deletes the link itself, never the target
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from muru.policy.risk import RiskTier
from muru.tools.base import Tool, ToolExecutionError, ToolResult
from muru.tools.filesystem._safety import PathSecurityError, safe_resolve

# Cap on content capture for the result. Larger files have
# deleted_content=None and are noted as not undoable from result alone.
MAX_UNDO_CAPTURE_BYTES = 10 * 1024 * 1024  # 10 MB


class DeleteFileArgs(BaseModel):
    """Arguments for delete_file."""

    path: str = Field(
        description=(
            "File path to delete. Use '~/' for home (e.g., "
            "'~/old.txt'). Must be inside the user's home directory "
            "and must exist as a regular file. Symlinks delete the "
            "link, not the target. Directories are refused."
        ),
    )


class DeleteFileResult(ToolResult):
    """Result of delete_file."""

    path: str = ""
    size_bytes: int = 0
    deleted_content: str | None = None
    deleted_content_truncated: bool = False


def _delete_file_impl(args: DeleteFileArgs) -> DeleteFileResult:
    # Resolve path safely
    try:
        target = safe_resolve(args.path)
    except PathSecurityError as e:
        return DeleteFileResult(success=False, message=str(e), path=args.path)

    # Target must exist
    if not target.exists() and not target.is_symlink():
        return DeleteFileResult(
            success=False,
            message=f"Path does not exist: {target}",
            path=str(target),
        )

    # Refuse directories - they need a separate tool with bulk-aware UX
    if target.is_dir() and not target.is_symlink():
        return DeleteFileResult(
            success=False,
            message=(
                f"Path is a directory: {target}. "
                "delete_file refuses directories in v0.4.0. "
                "Use rmdir manually or wait for v0.4.1+."
            ),
            path=str(target),
        )

    # If it's a symlink, we delete the link itself - never follow.
    # If it's NOT a symlink and NOT a regular file, refuse (sockets,
    # devices, fifos, etc.)
    is_symlink = target.is_symlink()
    if not is_symlink and not target.is_file():
        return DeleteFileResult(
            success=False,
            message=(
                f"Path is not a regular file: {target}. "
                "delete_file refuses sockets, devices, and special files."
            ),
            path=str(target),
        )

    # Capture metadata + content for v0.5.0 undo
    size = 0
    deleted_content: str | None = None
    truncated = False

    if not is_symlink:
        try:
            stat = target.stat()
            size = stat.st_size
            if size <= MAX_UNDO_CAPTURE_BYTES:
                try:
                    deleted_content = target.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    # Binary file - skip undo capture
                    deleted_content = None
            else:
                truncated = True
        except OSError as e:
            return DeleteFileResult(
                success=False,
                message=f"Could not read file before delete: {e}",
                path=str(target),
            )

    # Do the delete
    try:
        target.unlink()
    except OSError as e:
        raise ToolExecutionError(f"Failed to delete file: {e}") from e
    except Exception as e:
        raise ToolExecutionError(f"Unexpected error during delete: {e}") from e

    kind = "symlink" if is_symlink else "file"
    return DeleteFileResult(
        success=True,
        message=f"Deleted {kind} {target} ({size} bytes).",
        path=str(target),
        size_bytes=size,
        deleted_content=deleted_content,
        deleted_content_truncated=truncated,
    )


delete_file_tool: Tool[DeleteFileArgs, DeleteFileResult] = Tool(
    name="delete_file",
    description=(
        "Delete a single file. Irreversible without undo support. "
        "Refuses directories and special files. For symlinks, removes "
        "the link itself, not the target. Use '~/' for home paths. "
        "Path must be inside the user's home directory."
    ),
    args_model=DeleteFileArgs,
    result_model=DeleteFileResult,
    implementation=_delete_file_impl,
    risk_tier=RiskTier.CRITICAL,
)


__all__: list[Any] = [
    "MAX_UNDO_CAPTURE_BYTES",
    "DeleteFileArgs",
    "DeleteFileResult",
    "delete_file_tool",
]
