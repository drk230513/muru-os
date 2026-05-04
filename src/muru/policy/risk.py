"""Risk tier classification for tools.

Every tool in Muru declares a risk tier (0-4). The orchestrator and
confirmation engine use the tier to decide what UX to show the user
before invoking the tool.
"""

from __future__ import annotations

from enum import IntEnum


class RiskTier(IntEnum):
    """Risk tier for tool invocations. Higher = more friction required."""

    READ_ONLY = 0
    LOW_RISK = 1
    MEDIUM_RISK = 2
    HIGH_RISK = 3
    CRITICAL = 4

    @property
    def display_name(self) -> str:
        """Human-readable name for this tier."""
        names = {
            RiskTier.READ_ONLY: "Read-only",
            RiskTier.LOW_RISK: "Low risk",
            RiskTier.MEDIUM_RISK: "Medium risk",
            RiskTier.HIGH_RISK: "High risk",
            RiskTier.CRITICAL: "Critical",
        }
        return names[self]

    @property
    def auto_execute(self) -> bool:
        """Whether tools at this tier should run without user confirmation.

        Tier 0 and Tier 1 auto-execute (Tier 1 still gets logged).
        Tier 2+ requires explicit user confirmation.
        """
        return self <= RiskTier.LOW_RISK


__all__ = ["RiskTier"]
