"""Pydantic schema for a single audit log entry.

Each entry represents one tool invocation: what the user asked for,
what tool ran, with what args, what came back, what Muru ultimately
told the user. The full tool_result dict is preserved so undo can
replay metadata that was captured at the time (previous_content,
deleted_content, etc.).

Format on disk: JSON Lines (one Entry per line, append-only).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AuditEntry(BaseModel):
    """One audited tool invocation.

    Created at orchestrator time (after the tool runs, before the
    response is rendered). Persisted by AuditWriter.
    """

    event_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=_utc_now)
    intent: str
    tool_name: str
    tool_args: dict[str, Any]
    tool_result: dict[str, Any]
    final_response: str
    error: str | None = None
    undone: bool = False
    undone_at: datetime | None = None
    undone_by_event_id: UUID | None = None

    def to_jsonl(self) -> str:
        """Serialize to one JSON line, ready for the audit file."""
        return self.model_dump_json() + "\n"

    @classmethod
    def from_jsonl(cls, line: str) -> AuditEntry:
        """Parse one JSON line back into an AuditEntry."""
        return cls.model_validate_json(line)


__all__ = ["AuditEntry"]
