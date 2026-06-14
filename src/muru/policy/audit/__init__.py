"""Audit log for Muru: persistent record of tool invocations.

Architecture:

    AuditEntry (entry.py): Pydantic schema for one log line
    AuditWriter (writer.py): durable append-only writer
    AuditReader (reader.py, v0.5.0 Chunk 22): load + filter entries

File format: JSON Lines (one entry per line). Append-only by design.
"Undo" is represented by writing a separate marker entry rather than
modifying past entries - the audit log itself is immutable.
"""

from muru.policy.audit.entry import AuditEntry
from muru.policy.audit.reader import AuditReader
from muru.policy.audit.undo import UndoEngine, UndoResult
from muru.policy.audit.writer import DEFAULT_AUDIT_FILENAME, AuditWriter

__all__ = [
    "DEFAULT_AUDIT_FILENAME",
    "AuditEntry",
    "AuditReader",
    "AuditWriter",
    "UndoEngine",
    "UndoResult",
]
