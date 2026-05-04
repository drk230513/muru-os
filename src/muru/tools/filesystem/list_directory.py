"""list_directory — list files and folders in a directory.

This is the first concrete Muru tool. It returns metadata about each
entry (name, type, size, modified time) so the LLM can format a useful
response or chain into other tools.
"""

from __future__ import annotations

import fnmatch
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from muru.tools.base import Tool, ToolResult
from muru.tools.filesystem._safety import PathSecurityError, safe_resolve

# ============================================
# Input schema
# ============================================


class ListDirectoryArgs(BaseModel):
    """Arguments for list_directory."""

    path: str = Field(
        description=(
            "Directory path to list. Can use ~ for home (e.g., '~/Downloads'). "
            "Must be inside the user's home directory."
        ),
    )
    pattern: str | None = Field(
        default=None,
        description=(
            "Optional glob pattern to filter entries (e.g., '*.py', 'IMG_*'). "
            "If omitted, all entries are returned."
        ),
    )
    recursive: bool = Field(
        default=False,
        description=(
            "If True, descend into subdirectories. WARNING: can be slow on "
            "large trees. Defaults to False."
        ),
    )
    max_entries: int = Field(
        default=200,
        ge=1,
        le=10000,
        description=(
            "Maximum number of entries to return. Caps results to prevent "
            "overwhelming output. Defaults to 200."
        ),
    )


# ============================================
# Output schema
# ============================================


class FileEntry(BaseModel):
    """A single file or directory entry."""

    name: str = Field(description="Just the filename, not the full path.")
    path: str = Field(description="Full path relative to the queried directory.")
    type: Literal["file", "directory", "symlink", "other"] = Field(
        description="What kind of entry this is."
    )
    size_bytes: int | None = Field(
        default=None,
        description="Size in bytes (None for directories).",
    )
    modified_iso: str | None = Field(
        default=None,
        description="Last-modified time, ISO 8601 format.",
    )


class ListDirectoryResult(ToolResult):
    """Result of list_directory."""

    directory: str = Field(description="The resolved absolute directory path.")
    entries: list[FileEntry] = Field(
        default_factory=list,
        description="One FileEntry per matching item.",
    )
    total_found: int = Field(
        default=0,
        description=("Total entries matched. May exceed len(entries) if max_entries hit."),
    )
    truncated: bool = Field(
        default=False,
        description="True if total_found > len(entries).",
    )


# ============================================
# Implementation
# ============================================


def _classify(path: Path) -> Literal["file", "directory", "symlink", "other"]:
    """Decide what kind of entry a path is."""
    try:
        if path.is_symlink():
            return "symlink"
        if path.is_dir():
            return "directory"
        if path.is_file():
            return "file"
        return "other"
    except OSError:
        # Permission denied or transient I/O error — treat as 'other'
        return "other"


def _entry_for(path: Path, base: Path) -> FileEntry:
    """Build a FileEntry for `path`, with `path` field relative to `base`."""
    try:
        stat = path.stat() if not path.is_symlink() else path.lstat()
        size = stat.st_size if path.is_file() else None
        mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()
    except OSError:
        size = None
        mtime = None

    return FileEntry(
        name=path.name,
        path=str(path.relative_to(base)) if path != base else ".",
        type=_classify(path),
        size_bytes=size,
        modified_iso=mtime,
    )


def _list_directory_impl(args: ListDirectoryArgs) -> ListDirectoryResult:
    """Actual implementation. Called via the Tool wrapper."""
    try:
        directory = safe_resolve(args.path)
    except PathSecurityError as e:
        return ListDirectoryResult(
            success=False,
            message=f"Path rejected: {e}",
            directory=args.path,
        )

    if not directory.exists():
        return ListDirectoryResult(
            success=False,
            message=f"Directory does not exist: {directory}",
            directory=str(directory),
        )

    if not directory.is_dir():
        return ListDirectoryResult(
            success=False,
            message=f"Not a directory: {directory}",
            directory=str(directory),
        )

    # Iterator: either flat or recursive
    iterator = directory.rglob("*") if args.recursive else directory.iterdir()

    matched: list[Path] = []
    for entry_path in iterator:
        if args.pattern and not fnmatch.fnmatch(entry_path.name, args.pattern):
            continue
        matched.append(entry_path)

    total = len(matched)
    truncated = total > args.max_entries
    matched = matched[: args.max_entries]

    entries = [_entry_for(p, directory) for p in matched]

    summary = f"Found {total} entries"
    if truncated:
        summary += f" (showing first {len(entries)})"
    if args.pattern:
        summary += f" matching {args.pattern!r}"
    summary += f" in {directory}."

    return ListDirectoryResult(
        success=True,
        message=summary,
        directory=str(directory),
        entries=entries,
        total_found=total,
        truncated=truncated,
    )


# ============================================
# Tool registration
# ============================================


list_directory_tool: Tool[ListDirectoryArgs, ListDirectoryResult] = Tool(
    name="list_directory",
    description=(
        "List files and folders in a directory. Returns metadata "
        "(name, type, size, modified time) for each entry. Supports "
        "glob filtering and optional recursion. Read-only."
    ),
    args_model=ListDirectoryArgs,
    result_model=ListDirectoryResult,
    implementation=_list_directory_impl,
)


__all__ = [
    "FileEntry",
    "ListDirectoryArgs",
    "ListDirectoryResult",
    "list_directory_tool",
]
