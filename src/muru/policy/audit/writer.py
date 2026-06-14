"""Append-only audit log writer.

AuditWriter serializes AuditEntry instances to a JSONL file. Writes
are append-only and durable (fsync after write) so a crash never
leaves the audit file in a corrupted intermediate state.

The audit file location is configurable but defaults to
~/.local/share/muru/audit.jsonl (per the data_dir from config).
The directory is auto-created if missing.
"""

from __future__ import annotations

import os
from datetime import UTC
from pathlib import Path

from muru.policy.audit.entry import AuditEntry
from muru.utils.logging import get_logger

log = get_logger(__name__)


DEFAULT_AUDIT_FILENAME = "audit.jsonl"


class AuditWriter:
    """Appends AuditEntry records to a JSONL file durably.

    Thread-safety: Python\'s file append in O_APPEND mode is atomic
    per write() on POSIX, so concurrent writers don\'t interleave
    bytes within a single line. We rely on that.
    """

    def __init__(self, path: Path) -> None:
        """Construct an AuditWriter.

        Args:
            path: Absolute path to the audit file. Parent dirs are
                auto-created if missing.
        """
        self._path = path
        self._ensure_parent_dir()

    def _ensure_parent_dir(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def append(self, entry: AuditEntry) -> None:
        """Append one entry to the audit file durably.

        Steps:
        1. Open in append mode (O_APPEND on POSIX)
        2. Write the entry as one JSON line
        3. flush + fsync so the entry is on disk before we return
        """
        line = entry.to_jsonl()
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            # Don\'t crash the user-facing flow if audit can\'t write.
            # Log loudly so we know it happened.
            log.error(
                "audit_write_failed",
                path=str(self._path),
                event_id=str(entry.event_id),
                error=str(e),
            )
            raise

        log.info(
            "audit_appended",
            path=str(self._path),
            event_id=str(entry.event_id),
            tool=entry.tool_name,
        )

    def mark_undone(
        self,
        event_id: str,
        undone_by_event_id: str,
    ) -> bool:
        """Mark a prior entry as undone.

        This does NOT rewrite the original entry (the audit log is
        append-only). It writes a new "undone marker" entry that
        references the original event_id. Readers reconstruct undone
        state by scanning for these markers.

        Returns:
            True if a marker was written. False if the file does not
            yet exist (nothing could have been undone).
        """
        if not self._path.exists():
            return False

        from datetime import datetime
        from uuid import UUID

        marker = AuditEntry(
            event_id=UUID(undone_by_event_id),
            timestamp=datetime.now(UTC),
            intent="(undo marker)",
            tool_name="__undo_marker__",
            tool_args={"undoes_event_id": event_id},
            tool_result={"success": True, "message": "Marker for undo."},
            final_response="(undo marker)",
        )
        self.append(marker)
        return True


__all__ = ["DEFAULT_AUDIT_FILENAME", "AuditWriter"]
