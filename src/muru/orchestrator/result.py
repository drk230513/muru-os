"""OrchestratorResult — a complete record of one user interaction.

This object captures everything that happened when handling a single
user intent: the plan, the tool result (if any), the final response,
and any errors. It's the audit-friendly handoff between orchestrator
and REPL.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from muru.planner.plan import Plan


class OrchestratorResult(BaseModel):
    """Complete record of one orchestrator invocation.

    The REPL will typically just display `final_response`, but the rest
    is preserved for logging, debugging, and (in v0.5.0+) audit and undo.
    """

    intent: str = Field(description="The user's original input.")
    plan: Plan | None = Field(
        default=None,
        description="The plan the planner produced, or None if planning failed.",
    )
    tool_result: dict[str, Any] | None = Field(
        default=None,
        description=(
            "If the plan called a tool, this is the tool's result serialized "
            "as a dict. None if no tool ran or the tool errored."
        ),
    )
    final_response: str = Field(
        description="The text to show the user. Always populated.",
    )
    error: str | None = Field(
        default=None,
        description=(
            "If something went wrong, a human-readable error message. "
            "final_response will already have been set to a user-friendly "
            "version of this error."
        ),
    )


__all__ = ["OrchestratorResult"]
