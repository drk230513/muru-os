"""search_files — find files by name pattern and/or content."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from pydantic import BaseModel, Field

from muru.tools.base import Tool, ToolResult
from muru.tools.filesystem._safety import PathSecurityError, safe_resolve

# Skip files larger than this when searching content — large files are
# often binary (or huge logs) and not what the user wants.
CONTENT_SEARCH_SIZE_LIMIT = 5_000_000  # 5 MB

# Common directory names that should be skipped during recursive search
# (build artifacts, version control, dependency caches).
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    ".venv",
    "venv",
    "env",
    ".env",
    "dist",
    "build",
    ".next",
    ".cache",
    "target",
}


# ============================================
# Input/output schemas
# ============================================


class SearchFilesArgs(BaseModel):
    """Arguments for search_files."""

    directory: str = Field(
        description="Directory to search in. Can use ~ for home.",
    )
    name_pattern: str | None = Field(
        default=None,
        description=(
            "Optional glob pattern for filenames (e.g., '*.py'). If None, all files are eligible."
        ),
    )
    content_pattern: str | None = Field(
        default=None,
        description=(
            "Optional regex pattern to match in file contents. Files larger "
            f"than {CONTENT_SEARCH_SIZE_LIMIT // 1_000_000} MB are skipped. "
            "If None, only filename matching is performed."
        ),
    )
    case_sensitive: bool = Field(
        default=False,
        description="Whether content_pattern matching is case-sensitive.",
    )
    max_results: int = Field(
        default=50,
        ge=1,
        le=1000,
        description="Maximum matching files to return. Defaults to 50.",
    )


class SearchMatch(BaseModel):
    """One file that matched the search."""

    path: str = Field(description="Full file path.")
    name: str = Field(description="Filename only.")
    size_bytes: int = Field(description="File size on disk.")
    matching_lines: list[str] = Field(
        default_factory=list,
        description=("Up to 5 matching lines (only populated if content_pattern was given)."),
    )


class SearchFilesResult(ToolResult):
    """Result of search_files."""

    directory: str = Field(description="Resolved absolute search directory.")
    matches: list[SearchMatch] = Field(default_factory=list)
    files_scanned: int = Field(default=0, description="Total files visited.")
    truncated: bool = Field(default=False, description="True if max_results was hit.")


# ============================================
# Implementation
# ============================================


def _walk_files(root: Path) -> list[Path]:
    """Walk root recursively, yielding files and skipping known noise dirs."""
    results: list[Path] = []
    # Use os.walk-style iteration so we can prune noisy directories
    for dirpath in [root]:
        stack = [dirpath]
        while stack:
            current = stack.pop()
            try:
                entries = list(current.iterdir())
            except (OSError, PermissionError):
                continue
            for entry in entries:
                if entry.is_dir():
                    if entry.name in SKIP_DIRS:
                        continue
                    stack.append(entry)
                elif entry.is_file():
                    results.append(entry)
    return results


def _matches_content(path: Path, pattern: re.Pattern[str]) -> list[str]:
    """Return up to 5 matching lines from `path`, or [] if no match / too big."""
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size > CONTENT_SEARCH_SIZE_LIMIT:
        return []

    try:
        # latin-1 never fails to decode any byte sequence.
        # We trade encoding accuracy for not crashing on binary files.
        with path.open("r", encoding="latin-1", errors="replace") as f:
            matches: list[str] = []
            for line in f:
                if pattern.search(line):
                    matches.append(line.rstrip("\n"))
                    if len(matches) >= 5:
                        break
            return matches
    except OSError:
        return []


def _search_files_impl(args: SearchFilesArgs) -> SearchFilesResult:
    try:
        directory = safe_resolve(args.directory)
    except PathSecurityError as e:
        return SearchFilesResult(
            success=False,
            message=f"Path rejected: {e}",
            directory=args.directory,
        )

    if not directory.exists():
        return SearchFilesResult(
            success=False,
            message=f"Directory does not exist: {directory}",
            directory=str(directory),
        )

    if not directory.is_dir():
        return SearchFilesResult(
            success=False,
            message=f"Path is not a directory: {directory}",
            directory=str(directory),
        )

    if args.name_pattern is None and args.content_pattern is None:
        return SearchFilesResult(
            success=False,
            message="Must provide at least one of name_pattern or content_pattern.",
            directory=str(directory),
        )

    # Compile content pattern if provided
    content_re: re.Pattern[str] | None = None
    if args.content_pattern is not None:
        flags = 0 if args.case_sensitive else re.IGNORECASE
        try:
            content_re = re.compile(args.content_pattern, flags)
        except re.error as e:
            return SearchFilesResult(
                success=False,
                message=f"Invalid content_pattern regex: {e}",
                directory=str(directory),
            )

    matches: list[SearchMatch] = []
    files_scanned = 0
    truncated = False

    for file_path in _walk_files(directory):
        files_scanned += 1

        # Filter by name first (cheap)
        if args.name_pattern and not fnmatch.fnmatch(file_path.name, args.name_pattern):
            continue

        # Then content (expensive)
        matching_lines: list[str] = []
        if content_re is not None:
            matching_lines = _matches_content(file_path, content_re)
            if not matching_lines:
                continue

        try:
            size = file_path.stat().st_size
        except OSError:
            continue

        matches.append(
            SearchMatch(
                path=str(file_path),
                name=file_path.name,
                size_bytes=size,
                matching_lines=matching_lines,
            )
        )

        if len(matches) >= args.max_results:
            truncated = True
            break

    summary_parts = [f"Scanned {files_scanned} files, found {len(matches)} match(es)"]
    if truncated:
        summary_parts.append(f"(capped at {args.max_results})")
    if args.name_pattern:
        summary_parts.append(f"name~{args.name_pattern!r}")
    if args.content_pattern:
        summary_parts.append(f"content~{args.content_pattern!r}")

    return SearchFilesResult(
        success=True,
        message=" ".join(summary_parts) + ".",
        directory=str(directory),
        matches=matches,
        files_scanned=files_scanned,
        truncated=truncated,
    )


# ============================================
# Tool registration
# ============================================


search_files_tool: Tool[SearchFilesArgs, SearchFilesResult] = Tool(
    name="search_files",
    description=(
        "Find files by name pattern (glob), content pattern (regex), or both. "
        "Recursive. Skips common noise directories (.git, node_modules, etc). "
        "Skips files larger than 5 MB for content search. Returns up to 5 "
        "matching lines per file. Read-only."
    ),
    args_model=SearchFilesArgs,
    result_model=SearchFilesResult,
    implementation=_search_files_impl,
)


__all__ = [
    "SearchFilesArgs",
    "SearchFilesResult",
    "SearchMatch",
    "search_files_tool",
]
