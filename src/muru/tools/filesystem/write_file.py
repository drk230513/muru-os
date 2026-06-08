"""write_file tool: create or overwrite a single text file atomically.

Risk tier: HIGH_RISK (3). Always prompts for typed confirmation, even
for new files. Writes destroy prior content; the simpler always-strict
UX is safer than a dynamic tier that depends on target existence.

Atomic write strategy: writes to a sibling temp file, then uses
os.replace() to atomically rename into place. A crash mid-write leaves
either the prior content intact or the new content fully written -
never a half-written file.

Sandboxed via safe_resolve() to the user home directory.
"""

from __future__ import annotations

import contextlib
import os
from typing import Any

from pydantic import BaseModel, Field

from muru.policy.risk import RiskTier
from muru.tools.base import Tool, ToolExecutionError, ToolResult
from muru.tools.filesystem._safety import PathSecurityError, safe_resolve

# Cap on previous-content capture for the result. Larger files have
# previous_content=None and are noted as not undoable from result alone.
MAX_UNDO_CAPTURE_BYTES = 10 * 1024 * 1024  # 10 MB


class WriteFileArgs(BaseModel):
    """Arguments for write_file."""

    path: str = Field(
        description=(
            "File path to write. Use '~/' for home (e.g., '~/notes.txt'). "
            "Must be inside the user's home directory. The parent "
            "directory must already exist."
        ),
    )
    content: str = Field(
        description="Text content to write. UTF-8 encoded on disk.",
    )
    encoding: str = Field(
        default="utf-8",
        description="Text encoding. Defaults to utf-8. Rarely needs changing.",
    )


class WriteFileResult(ToolResult):
    """Result of write_file."""

    path: str = ""
    size_bytes: int = 0
    created: bool = False
    previous_size_bytes: int | None = None
    previous_content: str | None = None
    previous_content_truncated: bool = False


def _write_file_impl(args: WriteFileArgs) -> WriteFileResult:
    # Resolve path safely
    try:
        target = safe_resolve(args.path)
    except PathSecurityError as e:
        return WriteFileResult(success=False, message=str(e), path=args.path)

    # The parent directory must exist - we do not auto-mkdir in v0.4.0
    # because that is itself a write operation that ought to be its own
    # tool with its own confirmation tier (deferred to v0.4.1).
    if not target.parent.exists():
        return WriteFileResult(
            success=False,
            message=(
                f"Parent directory does not exist: {target.parent}. Create it first, then retry."
            ),
            path=str(target),
        )
    if not target.parent.is_dir():
        return WriteFileResult(
            success=False,
            message=f"Parent path is not a directory: {target.parent}",
            path=str(target),
        )

    # Capture prior state for undo metadata
    existed = target.exists()
    previous_size: int | None = None
    previous_content: str | None = None
    previous_truncated = False

    if existed:
        if not target.is_file():
            return WriteFileResult(
                success=False,
                message=(
                    f"Target exists but is not a regular file: {target}. Refusing to overwrite."
                ),
                path=str(target),
            )
        try:
            stat = target.stat()
            previous_size = stat.st_size
            if previous_size <= MAX_UNDO_CAPTURE_BYTES:
                try:
                    previous_content = target.read_text(encoding=args.encoding)
                except UnicodeDecodeError:
                    # Binary file or wrong encoding - skip undo capture
                    previous_content = None
            else:
                previous_truncated = True
        except OSError as e:
            return WriteFileResult(
                success=False,
                message=f"Could not read existing file: {e}",
                path=str(target),
            )

    # Atomic write: write to temp, then rename into place
    tmp = target.with_name(f"{target.name}.muru-tmp-{os.getpid()}")
    try:
        tmp.write_text(args.content, encoding=args.encoding)
        os.replace(tmp, target)
    except OSError as e:
        if tmp.exists():
            with contextlib.suppress(OSError):
                tmp.unlink()
        raise ToolExecutionError(f"Failed to write file: {e}") from e
    except Exception as e:
        if tmp.exists():
            with contextlib.suppress(OSError):
                tmp.unlink()
        raise ToolExecutionError(f"Unexpected error during atomic write: {e}") from e

    # Compute final size from what we wrote
    new_size = len(args.content.encode(args.encoding))

    action = "Created" if not existed else "Overwrote"
    return WriteFileResult(
        success=True,
        message=f"{action} {target} ({new_size} bytes).",
        path=str(target),
        size_bytes=new_size,
        created=not existed,
        previous_size_bytes=previous_size,
        previous_content=previous_content,
        previous_content_truncated=previous_truncated,
    )


write_file_tool: Tool[WriteFileArgs, WriteFileResult] = Tool(
    name="write_file",
    description=(
        "Create or overwrite a text file. Writes are atomic - either the "
        "file is fully written or unchanged. Use '~/' for home paths. "
        "Parent directory must already exist."
    ),
    args_model=WriteFileArgs,
    result_model=WriteFileResult,
    implementation=_write_file_impl,
    risk_tier=RiskTier.HIGH_RISK,
)


__all__: list[Any] = [
    "MAX_UNDO_CAPTURE_BYTES",
    "WriteFileArgs",
    "WriteFileResult",
    "write_file_tool",
]
