"""Plan schema — what the LLM produces in response to a user intent.

A Plan is the planner's output. It says either "I'll just respond"
(needs_tool=False) or "I want to call this tool with these arguments"
(needs_tool=True). The Executor (Chunk 10) takes a Plan and acts on it.

Why a structured Plan instead of just calling tools directly?
- Testable: we can verify the planner without running tools
- Auditable: every plan is logged before any action
- Confirmable: v0.3.0 inserts confirmation between Plan and execution
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class Plan(BaseModel):
    """The LLM's decision about how to handle a user intent.

    Two valid shapes:

    1. needs_tool=False — pure conversation. `response` is the LLM's
       reply to show the user. tool_name and tool_args must be None.

    2. needs_tool=True — tool invocation. `tool_name` is the registered
       name, `tool_args` is the dict of args to pass. `reasoning` is
       a short explanation (shown in audit log; optional in user UI).
    """

    needs_tool: bool = Field(
        description="True if the user request requires tool invocation.",
    )
    tool_name: str | None = Field(
        default=None,
        description="Registered tool name (only when needs_tool=True).",
    )
    tool_args: dict[str, Any] | None = Field(
        default=None,
        description="Args to pass to the tool (only when needs_tool=True).",
    )
    response: str | None = Field(
        default=None,
        description="Direct response to the user (only when needs_tool=False).",
    )
    reasoning: str | None = Field(
        default=None,
        description="Brief explanation of why this action was chosen.",
    )

    @model_validator(mode="after")
    def _validate_shape(self) -> Plan:
        """Enforce mutual exclusivity of the two plan shapes."""
        if self.needs_tool:
            if not self.tool_name:
                raise ValueError("needs_tool=True requires tool_name to be set.")
            # tool_args may be {} (some tools take no args), but must be a dict
            if self.tool_args is None:
                # Coerce None to empty dict — tool may have all defaults
                object.__setattr__(self, "tool_args", {})
            if self.response is not None:
                raise ValueError(
                    "needs_tool=True cannot also have a 'response' field. "
                    "The tool's result will be the response."
                )
        else:
            if not self.response:
                raise ValueError("needs_tool=False requires 'response' to be a non-empty string.")
            if self.tool_name is not None or self.tool_args is not None:
                raise ValueError("needs_tool=False cannot have tool_name or tool_args.")
        return self


__all__ = ["Plan"]
