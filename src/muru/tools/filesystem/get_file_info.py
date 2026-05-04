"""get_file_info — detailed metadata for a single file or directory."""

from __future__ import annotations

import hashlib
import mimetypes
import stat as stat_mod
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from muru.tools.base import Tool, ToolResult
from muru.tools.filesystem._safety import PathSecurityError, safe_resolve

# Don't compute SHA-256 for files larger than this — it's slow on big files.
HASH_SIZE_LIMIT_BYTES = 50_000_000  # 50 MB


# ============================================
# Input/output schemas
# ============================================


class GetFileInfoArgs(BaseModel):
    """Arguments for get_file_info."""

    path: str = Field(
        description="Path to inspect. Can use ~ for home.",
    )
    include_hash: bool = Field(
        default=False,
        description=(
            "If True, compute SHA-256 of file contents (skipped for files "
            f"larger than {HASH_SIZE_LIMIT_BYTES // 1_000_000} MB or for "
            "directories). Defaults to False because hashing is expensive."
        ),
    )


class GetFileInfoResult(ToolResult):
    """Result of get_file_info."""

    path: str = Field(description="Resolved absolute path.")
    type: Literal["file", "directory", "symlink", "other"] = Field(
        default="other",
        description="Kind of filesystem object.",
    )
    size_bytes: int | None = Field(default=None, description="Size in bytes.")
    modified_iso: str | None = Field(default=None, description="Last-modified ISO timestamp.")
    accessed_iso: str | None = Field(default=None, description="Last-accessed ISO timestamp.")
    created_iso: str | None = Field(
        default=None, description="Creation ISO timestamp (platform-dependent)."
    )
    permissions_octal: str | None = Field(
        default=None,
        description="POSIX permissions as octal string (e.g., '0644').",
    )
    permissions_symbolic: str | None = Field(
        default=None,
        description="POSIX permissions in symbolic form (e.g., '-rw-r--r--').",
    )
    mime_type: str | None = Field(
        default=None,
        description="Guessed MIME type based on extension (None if unknown).",
    )
    sha256: str | None = Field(
        default=None,
        description="SHA-256 hash of contents (only if include_hash=True and file is small enough).",
    )


# ============================================
# Implementation
# ============================================


def _classify(path: Path) -> Literal["file", "directory", "symlink", "other"]:
    try:
        if path.is_symlink():
            return "symlink"
        if path.is_dir():
            return "directory"
        if path.is_file():
            return "file"
        return "other"
    except OSError:
        return "other"


def _hash_file(path: Path) -> str:
    """SHA-256 a file in chunks to handle larger sizes without spiking memory."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_file_info_impl(args: GetFileInfoArgs) -> GetFileInfoResult:
    try:
        target = safe_resolve(args.path)
    except PathSecurityError as e:
        return GetFileInfoResult(
            success=False,
            message=f"Path rejected: {e}",
            path=args.path,
        )

    if not target.exists():
        return GetFileInfoResult(
            success=False,
            message=f"Path does not exist: {target}",
            path=str(target),
        )

    try:
        st = target.lstat() if target.is_symlink() else target.stat()
    except OSError as e:
        return GetFileInfoResult(
            success=False,
            message=f"Could not stat path: {e}",
            path=str(target),
        )

    file_type = _classify(target)

    # Permissions
    mode = st.st_mode
    perm_octal = oct(stat_mod.S_IMODE(mode))
    perm_symbolic = stat_mod.filemode(mode)

    # Times
    modified = datetime.fromtimestamp(st.st_mtime).isoformat()
    accessed = datetime.fromtimestamp(st.st_atime).isoformat()
    # st_ctime: change time on Unix, creation time on Windows. Best-effort.
    created = datetime.fromtimestamp(st.st_ctime).isoformat()

    # MIME (only for files)
    mime, _ = mimetypes.guess_type(target.name) if file_type == "file" else (None, None)

    # Hash (only if requested AND file is reasonably sized)
    sha = None
    if args.include_hash and file_type == "file" and st.st_size <= HASH_SIZE_LIMIT_BYTES:
        try:
            sha = _hash_file(target)
        except OSError as e:
            return GetFileInfoResult(
                success=False,
                message=f"Could not hash file: {e}",
                path=str(target),
            )

    return GetFileInfoResult(
        success=True,
        message=f"Got info for {target} ({file_type}).",
        path=str(target),
        type=file_type,
        size_bytes=st.st_size if file_type == "file" else None,
        modified_iso=modified,
        accessed_iso=accessed,
        created_iso=created,
        permissions_octal=perm_octal,
        permissions_symbolic=perm_symbolic,
        mime_type=mime,
        sha256=sha,
    )


# ============================================
# Tool registration
# ============================================


get_file_info_tool: Tool[GetFileInfoArgs, GetFileInfoResult] = Tool(
    name="get_file_info",
    description=(
        "Return detailed metadata for a single file or directory: type, "
        "size, modified/accessed/created times, POSIX permissions, MIME type, "
        "and (optionally) SHA-256 hash. Read-only."
    ),
    args_model=GetFileInfoArgs,
    result_model=GetFileInfoResult,
    implementation=_get_file_info_impl,
)


__all__ = ["GetFileInfoArgs", "GetFileInfoResult", "get_file_info_tool"]
