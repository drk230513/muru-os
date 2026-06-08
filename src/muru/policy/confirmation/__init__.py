"""Confirmation engine: decides whether tool plans should execute.

The confirmation engine is the place where Muru pauses before doing
something potentially risky. It owns the decision; the orchestrator
just asks "may I run this?" and respects the answer.

Architecture:

    ConfirmationProvider (Protocol) - the interface
        |
        +-- CliConfirmationProvider - Rich-based terminal UI (this version)
        +-- (Phase 2) GuiConfirmationProvider - Tauri webview
        +-- (Phase 3) VoiceConfirmationProvider - Whisper + spoken yes/no

Decisions:
    APPROVED  user said yes; orchestrator runs the tool
    REJECTED  user said no; orchestrator returns a friendly decline
    MODIFIED  user wants to change args; orchestrator re-plans
              (stubbed in v0.3.0; UX lands in Phase 2)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from muru.policy.risk import RiskTier


class Decision(StrEnum):
    """The result of a confirmation prompt."""

    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"


@dataclass(frozen=True)
class ConfirmationOutcome:
    """A confirmation decision plus optional context.

    modified_args is populated only when decision == MODIFIED.
    Phase 2's GUI will use it; v0.3.0's CLI never returns MODIFIED.
    """

    decision: Decision
    modified_args: dict[str, Any] | None = None
    reason: str | None = None


@runtime_checkable
class ConfirmationProvider(Protocol):
    """Anything that can answer 'should this tool run?' qualifies."""

    def confirm(
        self,
        tool_name: str,
        tool_description: str,
        tool_args: dict[str, Any],
        risk_tier: RiskTier,
        reasoning: str | None = None,
    ) -> ConfirmationOutcome:
        """Return a decision for the proposed tool invocation.

        Args:
            tool_name: The tool that wants to run.
            tool_description: Human-readable description of the tool.
            tool_args: The arguments the tool will be invoked with.
            risk_tier: The tool's risk classification.
            reasoning: Optional explanation from the planner about
                why this tool was chosen.

        Returns:
            ConfirmationOutcome with the user's decision.
        """
        ...


def auto_approve(
    tool_name: str,
    risk_tier: RiskTier,
) -> ConfirmationOutcome:
    """Return an APPROVED outcome with no UI interaction.

    Used internally by providers when the tier is low enough that
    no user prompt is needed. Centralized here so the auto-approval
    reasoning is consistent across providers.
    """
    return ConfirmationOutcome(
        decision=Decision.APPROVED,
        reason=f"Auto-approved: {tool_name!r} is {risk_tier.display_name}",
    )


__all__ = [
    "ConfirmationOutcome",
    "ConfirmationProvider",
    "Decision",
    "auto_approve",
]
