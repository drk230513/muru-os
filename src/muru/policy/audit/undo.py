"""Undo engine: reverse a past tool invocation.

Given an AuditEntry that was previously written and not yet undone,
UndoEngine works out the inverse action and executes it via the same
sandboxed mechanisms used by the original tools.

Per-tool undo semantics:

    write_file (created)    -> delete the file
    write_file (overwrote)  -> restore previous_content
    move_file               -> move destination back to source
    delete_file             -> recreate file from deleted_content

Conflict policy: undo refuses if the current state of the world has
diverged from what the audit log expected. Examples:

    - undoing a write but the file is now larger than what we wrote
    - undoing a move but the source still exists at its original path
    - undoing a delete but a different file now occupies that path

Refusal returns an UndoResult with success=False and a message. The
user can investigate and either resolve manually or force the undo
with a future flag (not in v0.5.0).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from muru.policy.audit.entry import AuditEntry
from muru.tools.filesystem._safety import PathSecurityError, safe_resolve
from muru.utils.logging import get_logger

if TYPE_CHECKING:
    from muru.policy.audit.writer import AuditWriter

log = get_logger(__name__)


@dataclass(frozen=True)
class UndoResult:
    """Outcome of attempting to undo a past entry."""

    success: bool
    message: str
    # The new audit entry created for the undo action (when success).
    # Caller uses this to mark the original entry as undone-by-this.
    undo_entry: AuditEntry | None = None


class UndoEngine:
    """Reverses past tool invocations.

    Construction:
        engine = UndoEngine(writer)

    Usage:
        outcome = engine.undo(past_entry)
        if outcome.success:
            print("Undone:", outcome.message)
        else:
            print("Could not undo:", outcome.message)
    """

    def __init__(self, writer: AuditWriter) -> None:
        """Construct an UndoEngine.

        Args:
            writer: AuditWriter used to record the undo action itself
                (Decision 2A: undo IS audited) and to write the
                __undo_marker__ that flags the original entry as undone.
        """
        self._writer = writer

    def undo(self, entry: AuditEntry) -> UndoResult:
        """Reverse a past tool invocation.

        Args:
            entry: The AuditEntry to undo. Must not already be marked
                undone; caller should check entry.undone == False.

        Returns:
            UndoResult with success/message and, on success, the new
            undo audit entry. On success, the caller (typically the
            REPL undo command) is responsible for marking the original
            entry as undone via writer.mark_undone(...).
        """
        if entry.undone:
            return UndoResult(
                success=False,
                message="That action has already been undone.",
            )
        if entry.error is not None:
            return UndoResult(
                success=False,
                message=(
                    f"Cannot undo a failed action ({entry.error}). There is nothing to reverse."
                ),
            )
        if not entry.tool_result.get("success"):
            return UndoResult(
                success=False,
                message=("Cannot undo: the original action did not succeed."),
            )

        # Dispatch by tool name
        dispatch = {
            "write_file": self._undo_write_file,
            "move_file": self._undo_move_file,
            "delete_file": self._undo_delete_file,
        }
        handler = dispatch.get(entry.tool_name)
        if handler is None:
            return UndoResult(
                success=False,
                message=(
                    f"No undo support for tool {entry.tool_name!r}. "
                    "Only write_file, move_file, and delete_file are "
                    "currently reversible."
                ),
            )

        try:
            return handler(entry)
        except PathSecurityError as e:
            # Should not happen for entries written by sandboxed tools,
            # but guard defensively.
            return UndoResult(
                success=False,
                message=f"Path security error during undo: {e}",
            )
        except OSError as e:
            log.warning("undo_os_error", tool=entry.tool_name, error=str(e))
            return UndoResult(
                success=False,
                message=f"OS error during undo: {e}",
            )

    # ----- Per-tool undo implementations -----

    def _undo_write_file(self, entry: AuditEntry) -> UndoResult:
        """Reverse a write_file.

        If the original write created a new file -> delete it.
        If the original write overwrote -> restore previous_content.
        """
        result = entry.tool_result
        path_str = result.get("path", "")
        target = safe_resolve(str(path_str))

        if not target.exists():
            return UndoResult(
                success=False,
                message=(
                    f"Cannot undo write to {target}: the file no longer "
                    "exists. Something else may have already removed it."
                ),
            )

        # Conflict check: does the file currently match what we wrote?
        expected_size = result.get("size_bytes")
        if isinstance(expected_size, int):
            try:
                actual_size = target.stat().st_size
            except OSError as e:
                return UndoResult(
                    success=False,
                    message=f"Could not stat target for undo: {e}",
                )
            if actual_size != expected_size:
                return UndoResult(
                    success=False,
                    message=(
                        f"The file at {target} has changed since the "
                        f"original write (expected {expected_size} bytes, "
                        f"found {actual_size}). Refusing to undo - "
                        "resolve manually first."
                    ),
                )

        created = bool(result.get("created"))
        if created:
            # Undo create -> delete
            try:
                target.unlink()
            except OSError as e:
                return UndoResult(
                    success=False,
                    message=f"Failed to delete file during undo: {e}",
                )
            undo_entry = self._build_undo_entry(
                original=entry,
                action_name="undo_write_create",
                args={"path": str(target)},
                final_message=f"Removed the file {target} that the original write created.",
            )
            return UndoResult(
                success=True,
                message=f"Removed {target}.",
                undo_entry=undo_entry,
            )

        # Undo overwrite -> restore previous_content
        previous_content = result.get("previous_content")
        previous_truncated = bool(result.get("previous_content_truncated"))
        if previous_truncated:
            return UndoResult(
                success=False,
                message=(
                    "The previous content was too large to capture, so "
                    "this overwrite is not undoable from the audit log "
                    "alone."
                ),
            )
        if not isinstance(previous_content, str):
            return UndoResult(
                success=False,
                message=(
                    "No previous_content captured (may have been a binary file). Cannot restore."
                ),
            )

        try:
            target.write_text(previous_content, encoding="utf-8")
        except OSError as e:
            return UndoResult(
                success=False,
                message=f"Failed to restore previous content: {e}",
            )

        undo_entry = self._build_undo_entry(
            original=entry,
            action_name="undo_write_overwrite",
            args={"path": str(target), "restored_bytes": len(previous_content)},
            final_message=f"Restored previous content of {target} ({len(previous_content)} bytes).",
        )
        return UndoResult(
            success=True,
            message=f"Restored previous content of {target}.",
            undo_entry=undo_entry,
        )

    def _undo_move_file(self, entry: AuditEntry) -> UndoResult:
        """Reverse a move_file: move destination back to source."""
        import shutil

        result = entry.tool_result
        source_str = result.get("source", "")
        destination_str = result.get("destination", "")

        original_source = safe_resolve(str(source_str))
        original_destination = safe_resolve(str(destination_str))

        # The file we want to move back must currently be at the destination
        if not original_destination.exists():
            return UndoResult(
                success=False,
                message=(
                    f"Cannot undo move: nothing exists at {original_destination}. "
                    "It may have been moved or deleted since the original move."
                ),
            )

        # The original source path must currently be empty (we\'re moving back into it)
        if original_source.exists():
            return UndoResult(
                success=False,
                message=(
                    f"Cannot undo move: a file already exists at the original "
                    f"source path {original_source}. Resolve manually first."
                ),
            )

        try:
            shutil.move(str(original_destination), str(original_source))
        except OSError as e:
            return UndoResult(
                success=False,
                message=f"Failed to move file back: {e}",
            )

        undo_entry = self._build_undo_entry(
            original=entry,
            action_name="undo_move",
            args={
                "moved_back_from": str(original_destination),
                "moved_back_to": str(original_source),
            },
            final_message=f"Moved {original_destination} back to {original_source}.",
        )
        return UndoResult(
            success=True,
            message=f"Moved {original_destination} back to {original_source}.",
            undo_entry=undo_entry,
        )

    def _undo_delete_file(self, entry: AuditEntry) -> UndoResult:
        """Reverse a delete_file: recreate the file with the captured content."""
        result = entry.tool_result
        path_str = result.get("path", "")
        target = safe_resolve(str(path_str))

        # Conflict check: the target must NOT currently exist
        if target.exists():
            return UndoResult(
                success=False,
                message=(
                    f"Cannot undo delete: something already exists at {target}. "
                    "A new file was created in this location since the delete."
                ),
            )

        deleted_content = result.get("deleted_content")
        deleted_truncated = bool(result.get("deleted_content_truncated"))
        if deleted_truncated:
            return UndoResult(
                success=False,
                message=(
                    "The deleted file was too large to capture, so this "
                    "delete is not undoable from the audit log alone."
                ),
            )
        if not isinstance(deleted_content, str):
            return UndoResult(
                success=False,
                message=(
                    "No deleted_content captured (may have been a binary "
                    "file or a symlink). Cannot recreate."
                ),
            )

        # Parent directory must still exist
        if not target.parent.exists():
            return UndoResult(
                success=False,
                message=(f"Cannot undo delete: parent directory {target.parent} no longer exists."),
            )

        try:
            target.write_text(deleted_content, encoding="utf-8")
        except OSError as e:
            return UndoResult(
                success=False,
                message=f"Failed to recreate file: {e}",
            )

        undo_entry = self._build_undo_entry(
            original=entry,
            action_name="undo_delete",
            args={"path": str(target), "restored_bytes": len(deleted_content)},
            final_message=f"Recreated {target} from captured content ({len(deleted_content)} bytes).",
        )
        return UndoResult(
            success=True,
            message=f"Recreated {target}.",
            undo_entry=undo_entry,
        )

    # ----- Helpers -----

    def _build_undo_entry(
        self,
        *,
        original: AuditEntry,
        action_name: str,
        args: dict[str, object],
        final_message: str,
    ) -> AuditEntry:
        """Construct an AuditEntry representing this undo action.

        Note: this just builds the entry. The REPL/caller writes it via
        self._writer.append() and also calls self._writer.mark_undone()
        on the original entry.
        """
        return AuditEntry(
            intent=f"undo {original.tool_name} (event {original.event_id})",
            tool_name=action_name,
            tool_args={
                "undoes_event_id": str(original.event_id),
                **args,
            },
            tool_result={"success": True, "message": final_message},
            final_response=final_message,
        )


__all__ = ["UndoEngine", "UndoResult"]
