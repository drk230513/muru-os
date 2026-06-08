"""CLI implementation of ConfirmationProvider using Rich panels."""

from __future__ import annotations

import json
import time
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from muru.policy.confirmation import (
    ConfirmationOutcome,
    Decision,
    auto_approve,
)
from muru.policy.risk import RiskTier
from muru.utils.logging import get_logger

log = get_logger(__name__)

# How long to wait before Tier 4 confirmations are accepted, in seconds.
# Prevents fat-finger mistakes on irreversible actions.
CRITICAL_TIER_COOLDOWN_SECONDS = 5


class CliConfirmationProvider:
    """Asks the user for confirmation via the terminal."""

    def __init__(self, console: Console | None = None) -> None:
        """Construct a CLI provider.

        Args:
            console: A Rich Console. If None, a default one is created.
                Pass a custom one for testing.
        """
        self._console = console or Console()

    def confirm(
        self,
        tool_name: str,
        tool_description: str,
        tool_args: dict[str, Any],
        risk_tier: RiskTier,
        reasoning: str | None = None,
    ) -> ConfirmationOutcome:
        """Render the appropriate prompt for the tier and return the decision."""
        # Tier 0 and 1 auto-approve (no UI shown)
        if risk_tier.auto_execute:
            log.info(
                "confirmation_auto_approved",
                tool=tool_name,
                tier=int(risk_tier),
            )
            return auto_approve(tool_name, risk_tier)

        # Show the plan
        self._render_plan(tool_name, tool_description, tool_args, risk_tier, reasoning)

        # Tier-specific prompt
        if risk_tier == RiskTier.MEDIUM_RISK:
            approved = self._prompt_yes_no()
        elif risk_tier == RiskTier.HIGH_RISK:
            approved = self._prompt_typed("yes")
        elif risk_tier == RiskTier.CRITICAL:
            approved = self._prompt_typed_with_cooldown(tool_name)
        else:
            # Defensive fallback for unknown tiers
            approved = self._prompt_yes_no()

        decision = Decision.APPROVED if approved else Decision.REJECTED
        log.info(
            "confirmation_decision",
            tool=tool_name,
            tier=int(risk_tier),
            decision=decision.value,
        )

        return ConfirmationOutcome(
            decision=decision,
            reason=None if approved else "User declined.",
        )

    def _render_plan(
        self,
        tool_name: str,
        tool_description: str,
        tool_args: dict[str, Any],
        risk_tier: RiskTier,
        reasoning: str | None,
    ) -> None:
        """Show the plan in a Rich panel before prompting."""
        tier_color = {
            RiskTier.MEDIUM_RISK: "yellow",
            RiskTier.HIGH_RISK: "orange3",
            RiskTier.CRITICAL: "red",
        }.get(risk_tier, "yellow")

        args_table = Table.grid(padding=(0, 2))
        args_table.add_column(style="cyan", no_wrap=True)
        args_table.add_column()
        if tool_args:
            for k, v in tool_args.items():
                args_table.add_row(k, json.dumps(v, default=str))
        else:
            args_table.add_row("(no arguments)", "")

        body_lines = [
            f"[bold]Tool:[/bold] [cyan]{tool_name}[/cyan]",
            f"[bold]Risk:[/bold] [{tier_color}]{risk_tier.display_name}[/{tier_color}]",
            "",
            f"[dim]{tool_description}[/dim]",
            "",
            "[bold]Arguments:[/bold]",
        ]
        if reasoning:
            body_lines.extend(
                [
                    "",
                    f"[bold]Why:[/bold] [dim]{reasoning}[/dim]",
                ]
            )

        self._console.print(
            Panel(
                "\n".join(body_lines),
                title="Confirmation required",
                border_style=tier_color,
            )
        )
        self._console.print(args_table)
        self._console.print()

    def _prompt_yes_no(self) -> bool:
        """Tier 2: simple y/n prompt."""
        try:
            response = (
                self._console.input("[bold]Approve?[/bold] [dim](y/n)[/dim] ").strip().lower()
            )
        except (EOFError, KeyboardInterrupt):
            self._console.print("[dim](cancelled)[/dim]")
            return False
        return response in {"y", "yes"}

    def _prompt_typed(self, expected: str) -> bool:
        """Tier 3: must type a specific word (default: 'yes')."""
        try:
            response = self._console.input(
                f"[bold]Type '[yellow]{expected}[/yellow]' to approve:[/bold] "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            self._console.print("[dim](cancelled)[/dim]")
            return False
        approved = response == expected
        if not approved and response:
            self._console.print(
                f"[dim](rejected - typed {response!r}, expected {expected!r})[/dim]"
            )
        return approved

    def _prompt_typed_with_cooldown(self, tool_name: str) -> bool:
        """Tier 4: must type the tool name AND wait for cooldown."""
        self._console.print(
            f"[red]This is an irreversible action.[/red] "
            f"[dim]Wait {CRITICAL_TIER_COOLDOWN_SECONDS}s, "
            f"then type the tool name.[/dim]"
        )
        time.sleep(CRITICAL_TIER_COOLDOWN_SECONDS)
        return self._prompt_typed(tool_name)


__all__ = ["CRITICAL_TIER_COOLDOWN_SECONDS", "CliConfirmationProvider"]
