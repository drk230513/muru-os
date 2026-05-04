"""read_file — read the contents of a text file."""

from __future__ import annotations

from pydantic import BaseModel, Field

from muru.policy.risk import RiskTier
from muru.tools.base import Tool, ToolResult
from muru.tools.filesystem._safety import PathSecurityError, safe_resolve

# ============================================
# Input/output schemas
# ============================================


class ReadFileArgs(BaseModel):
    """Arguments for read_file."""

    path: str = Field(
        description=(
            "File path to read. Can use ~ for home (e.g., '~/notes.txt'). "
            "Must be inside the user's home directory."
        ),
    )
    max_bytes: int = Field(
        default=100_000,
        ge=1,
        le=10_000_000,
        description=(
            "Maximum bytes to read. Files larger than this return their "
            "first max_bytes plus a 'truncated' flag. Defaults to 100 KB."
        ),
    )
    encoding: str = Field(
        default="utf-8",
        description=(
            "Text encoding to use when decoding. Defaults to utf-8. "
            "Use 'latin-1' for files with unknown encoding (it never fails)."
        ),
    )


class ReadFileResult(ToolResult):
    """Result of read_file."""

    path: str = Field(description="Resolved absolute file path.")
    content: str = Field(default="", description="File contents (decoded text).")
    size_bytes: int = Field(default=0, description="Total file size on disk.")
    bytes_read: int = Field(default=0, description="How many bytes were actually read.")
    truncated: bool = Field(
        default=False,
        description="True if file was larger than max_bytes.",
    )


# ============================================
# Implementation
# ============================================


def _read_file_impl(args: ReadFileArgs) -> ReadFileResult:
    """Read up to max_bytes from a file, return as decoded text."""
    try:
        target = safe_resolve(args.path)
    except PathSecurityError as e:
        return ReadFileResult(
            success=False,
            message=f"Path rejected: {e}",
            path=args.path,
        )

    if not target.exists():
        return ReadFileResult(
            success=False,
            message=f"File does not exist: {target}",
            path=str(target),
        )

    if target.is_dir():
        return ReadFileResult(
            success=False,
            message=f"Path is a directory, not a file: {target}",
            path=str(target),
        )

    if not target.is_file():
        return ReadFileResult(
            success=False,
            message=f"Path is not a regular file: {target}",
            path=str(target),
        )

    try:
        size = target.stat().st_size
    except OSError as e:
        return ReadFileResult(
            success=False,
            message=f"Could not stat file: {e}",
            path=str(target),
        )

    truncated = size > args.max_bytes
    bytes_to_read = min(size, args.max_bytes)

    try:
        with target.open("rb") as f:
            raw = f.read(bytes_to_read)
    except OSError as e:
        return ReadFileResult(
            success=False,
            message=f"Could not read file: {e}",
            path=str(target),
            size_bytes=size,
        )

    try:
        content = raw.decode(args.encoding)
    except (UnicodeDecodeError, LookupError) as e:
        return ReadFileResult(
            success=False,
            message=(
                f"Could not decode file as {args.encoding!r}: {e}. "
                f"Try encoding='latin-1' for binary or unknown-encoding files."
            ),
            path=str(target),
            size_bytes=size,
            bytes_read=len(raw),
        )

    summary = f"Read {len(raw)} bytes from {target}"
    if truncated:
        summary += f" (truncated; full size {size} bytes)"
    summary += "."

    return ReadFileResult(
        success=True,
        message=summary,
        path=str(target),
        content=content,
        size_bytes=size,
        bytes_read=len(raw),
        truncated=truncated,
    )


# ============================================
# Tool registration
# ============================================


read_file_tool: Tool[ReadFileArgs, ReadFileResult] = Tool(
    name="read_file",
    description=(
        "Read the contents of a text file. Returns the file's text plus "
        "metadata (size, bytes read, whether truncated). Caps reads at "
        "max_bytes (default 100 KB) to avoid loading huge files. Read-only."
    ),
    args_model=ReadFileArgs,
    result_model=ReadFileResult,
    implementation=_read_file_impl,
    risk_tier=RiskTier.READ_ONLY,
)


__all__ = ["ReadFileArgs", "ReadFileResult", "read_file_tool"]
