"""move_file tool: move or rename a file within the user sandbox.

Risk tier: HIGH_RISK (3). Move is destructive at the source - the file
disappears from where it was. User must type 'yes' to confirm.

Refuses to overwrite an existing destination - if the user truly wants
to replace dest, they delete it first (Tier 4) then move again. This
prevents silent destruction when the user did not realize dest existed.

Uses shutil.move() so cross-filesystem moves work correctly. shutil's
implementation copies-then-deletes, cleaning up partial destination on
error.

Both source and destination must resolve inside the user sandbox.
"""

from __future__ import annotations

import shutil
from typing import Any

from pydantic import BaseModel, Field

from muru.policy.risk import RiskTier
from muru.tools.base import Tool, ToolExecutionError, ToolResult
from muru.tools.filesystem._safety import PathSecurityError, safe_resolve


class MoveFileArgs(BaseModel):
    """Arguments for move_file."""

    source: str = Field(
        description=(
            "Path of the file to move. Use '~/' for home (e.g., "
            "'~/Downloads/old.txt'). Must be inside the user's "
            "home directory and must already exist."
        ),
    )
    destination: str = Field(
        description=(
            "Path to move the file to. Use '~/' for home. Must be "
            "inside the user's home directory. The parent directory "
            "must exist. If the destination already exists, the move "
            "is refused - delete it first."
        ),
    )


class MoveFileResult(ToolResult):
    """Result of move_file."""

    source: str = ""
    destination: str = ""
    size_bytes: int = 0


def _move_file_impl(args: MoveFileArgs) -> MoveFileResult:
    # Resolve both paths safely
    try:
        src = safe_resolve(args.source)
    except PathSecurityError as e:
        return MoveFileResult(
            success=False,
            message=f"Source rejected: {e}",
            source=args.source,
            destination=args.destination,
        )
    try:
        dst = safe_resolve(args.destination)
    except PathSecurityError as e:
        return MoveFileResult(
            success=False,
            message=f"Destination rejected: {e}",
            source=str(src),
            destination=args.destination,
        )

    # Source must exist and be a regular file (not a directory)
    if not src.exists():
        return MoveFileResult(
            success=False,
            message=f"Source does not exist: {src}",
            source=str(src),
            destination=str(dst),
        )
    if not src.is_file():
        return MoveFileResult(
            success=False,
            message=(
                f"Source is not a regular file: {src}. "
                "move_file refuses to move directories or special files in v0.4.0."
            ),
            source=str(src),
            destination=str(dst),
        )

    # Destination parent must exist
    if not dst.parent.exists():
        return MoveFileResult(
            success=False,
            message=(
                f"Destination parent directory does not exist: {dst.parent}. "
                "Create it first, then retry."
            ),
            source=str(src),
            destination=str(dst),
        )
    if not dst.parent.is_dir():
        return MoveFileResult(
            success=False,
            message=f"Destination parent is not a directory: {dst.parent}",
            source=str(src),
            destination=str(dst),
        )

    # Refuse to overwrite an existing destination - the user must delete it
    # first (Tier 4) if they really want to replace it.
    if dst.exists():
        return MoveFileResult(
            success=False,
            message=(
                f"Destination already exists: {dst}. "
                "Refusing to overwrite. Delete the destination first if you "
                "truly want to replace it."
            ),
            source=str(src),
            destination=str(dst),
        )

    # Capture size before move (for the result + future undo metadata)
    try:
        size = src.stat().st_size
    except OSError as e:
        return MoveFileResult(
            success=False,
            message=f"Could not stat source: {e}",
            source=str(src),
            destination=str(dst),
        )

    # Do the move
    try:
        shutil.move(str(src), str(dst))
    except OSError as e:
        raise ToolExecutionError(f"Failed to move file: {e}") from e
    except Exception as e:
        raise ToolExecutionError(f"Unexpected error during move: {e}") from e

    return MoveFileResult(
        success=True,
        message=f"Moved {src} to {dst} ({size} bytes).",
        source=str(src),
        destination=str(dst),
        size_bytes=size,
    )


move_file_tool: Tool[MoveFileArgs, MoveFileResult] = Tool(
    name="move_file",
    description=(
        "Move or rename a file. The source must exist and the destination "
        "must NOT exist (refuses to overwrite). Use '~/' for home paths. "
        "Both paths must be inside the user's home directory."
    ),
    args_model=MoveFileArgs,
    result_model=MoveFileResult,
    implementation=_move_file_impl,
    risk_tier=RiskTier.HIGH_RISK,
)


__all__: list[Any] = [
    "MoveFileArgs",
    "MoveFileResult",
    "move_file_tool",
]
