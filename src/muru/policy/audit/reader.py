"""Audit log reader: turn the JSONL file into a queryable view.

The audit file is append-only and never modified. "Undo" is represented
by appending an __undo_marker__ entry whose tool_args["undoes_event_id"]
points at the original entry. The reader scans for these markers and
reconstructs the undone state in memory.

Typical usage:
    reader = AuditReader(audit_path)
    recent = reader.recent(n=10, exclude_undone=True)
    for entry in recent:
        print(entry.tool_name, entry.timestamp)

    target = reader.get_by_event_id(uuid)
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from uuid import UUID

from muru.policy.audit.entry import AuditEntry
from muru.utils.logging import get_logger

log = get_logger(__name__)

UNDO_MARKER_TOOL_NAME = "__undo_marker__"


class AuditReader:
    """Loads + queries the audit log.

    Reads are eager: every call to a query method re-reads the file
    from disk. The cost is small for our scale (thousands of entries),
    and re-reading means we always see fresh data without invalidation
    bookkeeping. If this becomes a hotspot we add caching, not before.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    def _iter_raw_entries(self) -> Iterator[AuditEntry]:
        """Yield every entry (including undo markers) in file order."""
        if not self._path.exists():
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                for line_no, line in enumerate(f, start=1):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        yield AuditEntry.from_jsonl(stripped)
                    except Exception as e:
                        # One bad line doesn\'t kill the whole audit log.
                        log.warning(
                            "audit_entry_parse_failed",
                            path=str(self._path),
                            line=line_no,
                            error=str(e),
                        )
                        continue
        except OSError as e:
            log.error(
                "audit_read_failed",
                path=str(self._path),
                error=str(e),
            )
            raise

    def _load_with_undone_state(self) -> list[AuditEntry]:
        """Read the file and stamp the undone flag onto entries.

        Returns:
            List of all non-marker entries, in file order, with the
            .undone, .undone_at, .undone_by_event_id fields filled
            in by scanning for matching undo markers.
        """
        # First pass: collect every entry
        all_entries = list(self._iter_raw_entries())

        # Build a map from event_id -> undo marker info
        undo_map: dict[UUID, tuple[datetime, UUID]] = {}
        for entry in all_entries:
            if entry.tool_name == UNDO_MARKER_TOOL_NAME:
                undoes = entry.tool_args.get("undoes_event_id")
                if not undoes:
                    continue
                try:
                    undone_id = UUID(str(undoes))
                except (ValueError, TypeError):
                    continue
                undo_map[undone_id] = (entry.timestamp, entry.event_id)

        # Second pass: emit non-marker entries, applying undone state
        result: list[AuditEntry] = []
        for entry in all_entries:
            if entry.tool_name == UNDO_MARKER_TOOL_NAME:
                continue
            if entry.event_id in undo_map:
                timestamp, undo_event_id = undo_map[entry.event_id]
                # AuditEntry is a Pydantic model - use model_copy to
                # produce a new entry with the undone fields populated
                entry = entry.model_copy(
                    update={
                        "undone": True,
                        "undone_at": timestamp,
                        "undone_by_event_id": undo_event_id,
                    }
                )
            result.append(entry)

        return result

    def all_entries(self) -> list[AuditEntry]:
        """Return every entry (with undone state applied), oldest first."""
        return self._load_with_undone_state()

    def recent(
        self,
        n: int = 10,
        exclude_undone: bool = False,
        tool_name: str | None = None,
    ) -> list[AuditEntry]:
        """Return the most recent entries, newest first.

        Args:
            n: Maximum number of entries to return.
            exclude_undone: If True, skip entries already undone.
            tool_name: If set, only entries with this tool_name.

        Returns:
            List of entries, newest first.
        """
        entries = self._load_with_undone_state()

        if tool_name is not None:
            entries = [e for e in entries if e.tool_name == tool_name]
        if exclude_undone:
            entries = [e for e in entries if not e.undone]

        entries.reverse()  # newest first
        return entries[:n]

    def get_by_event_id(self, event_id: UUID | str) -> AuditEntry | None:
        """Look up a specific entry by event_id.

        Returns:
            The entry if found (with undone state applied), else None.
        """
        target = event_id if isinstance(event_id, UUID) else UUID(str(event_id))
        for entry in self._load_with_undone_state():
            if entry.event_id == target:
                return entry
        return None

    def last_undoable(self, tool_name: str | None = None) -> AuditEntry | None:
        """Return the most recent successful, not-yet-undone entry.

        This is what the REPL \'undo\' command uses by default - "undo
        the last thing I actually did". Skips errored entries and ones
        already undone.

        Args:
            tool_name: If set, only consider entries with this name.

        Returns:
            The most recent applicable entry, or None.
        """
        for entry in self.recent(n=1000, exclude_undone=True, tool_name=tool_name):
            if entry.error is not None:
                continue
            if not entry.tool_result.get("success"):
                continue
            return entry
        return None


__all__ = ["UNDO_MARKER_TOOL_NAME", "AuditReader"]
