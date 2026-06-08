"""Tests for the CLI confirmation provider."""

from __future__ import annotations

import io
from unittest.mock import patch

from rich.console import Console

from muru.policy.confirmation import Decision
from muru.policy.confirmation.cli import CliConfirmationProvider
from muru.policy.risk import RiskTier


def _make_console() -> Console:
    """Make a Rich Console that writes to a buffer (so tests don't print)."""
    buf = io.StringIO()
    return Console(file=buf, width=80, force_terminal=False, color_system=None)


# ----- Tier 0 / 1: auto-approve -----


def test_tier_0_auto_approves_without_prompt() -> None:
    provider = CliConfirmationProvider(console=_make_console())
    outcome = provider.confirm(
        tool_name="t",
        tool_description="d",
        tool_args={},
        risk_tier=RiskTier.READ_ONLY,
    )
    assert outcome.decision == Decision.APPROVED
    assert outcome.reason is not None
    assert "Auto-approved" in outcome.reason


def test_tier_1_auto_approves_without_prompt() -> None:
    provider = CliConfirmationProvider(console=_make_console())
    outcome = provider.confirm(
        tool_name="t",
        tool_description="d",
        tool_args={},
        risk_tier=RiskTier.LOW_RISK,
    )
    assert outcome.decision == Decision.APPROVED


# ----- Tier 2: y/n -----


def test_tier_2_approves_on_y() -> None:
    console = _make_console()
    with patch.object(console, "input", return_value="y"):
        provider = CliConfirmationProvider(console=console)
        outcome = provider.confirm(
            tool_name="t",
            tool_description="d",
            tool_args={"x": 1},
            risk_tier=RiskTier.MEDIUM_RISK,
        )
    assert outcome.decision == Decision.APPROVED


def test_tier_2_approves_on_yes() -> None:
    console = _make_console()
    with patch.object(console, "input", return_value="yes"):
        provider = CliConfirmationProvider(console=console)
        outcome = provider.confirm(
            tool_name="t",
            tool_description="d",
            tool_args={},
            risk_tier=RiskTier.MEDIUM_RISK,
        )
    assert outcome.decision == Decision.APPROVED


def test_tier_2_approves_case_insensitive() -> None:
    console = _make_console()
    with patch.object(console, "input", return_value="Y"):
        provider = CliConfirmationProvider(console=console)
        outcome = provider.confirm(
            tool_name="t",
            tool_description="d",
            tool_args={},
            risk_tier=RiskTier.MEDIUM_RISK,
        )
    assert outcome.decision == Decision.APPROVED


def test_tier_2_rejects_on_n() -> None:
    console = _make_console()
    with patch.object(console, "input", return_value="n"):
        provider = CliConfirmationProvider(console=console)
        outcome = provider.confirm(
            tool_name="t",
            tool_description="d",
            tool_args={},
            risk_tier=RiskTier.MEDIUM_RISK,
        )
    assert outcome.decision == Decision.REJECTED


def test_tier_2_rejects_on_anything_else() -> None:
    console = _make_console()
    with patch.object(console, "input", return_value="banana"):
        provider = CliConfirmationProvider(console=console)
        outcome = provider.confirm(
            tool_name="t",
            tool_description="d",
            tool_args={},
            risk_tier=RiskTier.MEDIUM_RISK,
        )
    assert outcome.decision == Decision.REJECTED


# ----- Tier 3: type 'yes' -----


def test_tier_3_approves_only_on_exact_yes() -> None:
    console = _make_console()
    with patch.object(console, "input", return_value="yes"):
        provider = CliConfirmationProvider(console=console)
        outcome = provider.confirm(
            tool_name="t",
            tool_description="d",
            tool_args={},
            risk_tier=RiskTier.HIGH_RISK,
        )
    assert outcome.decision == Decision.APPROVED


def test_tier_3_rejects_on_y_alone() -> None:
    """Tier 3 needs the full word, not just 'y'."""
    console = _make_console()
    with patch.object(console, "input", return_value="y"):
        provider = CliConfirmationProvider(console=console)
        outcome = provider.confirm(
            tool_name="t",
            tool_description="d",
            tool_args={},
            risk_tier=RiskTier.HIGH_RISK,
        )
    assert outcome.decision == Decision.REJECTED


def test_tier_3_rejects_on_typo() -> None:
    console = _make_console()
    with patch.object(console, "input", return_value="yse"):
        provider = CliConfirmationProvider(console=console)
        outcome = provider.confirm(
            tool_name="t",
            tool_description="d",
            tool_args={},
            risk_tier=RiskTier.HIGH_RISK,
        )
    assert outcome.decision == Decision.REJECTED


# ----- Tier 4: type tool name + cooldown -----


def test_tier_4_approves_when_tool_name_typed_after_cooldown() -> None:
    console = _make_console()
    with (
        patch.object(console, "input", return_value="dangerous_tool"),
        patch("muru.policy.confirmation.cli.time.sleep") as mock_sleep,
    ):
        provider = CliConfirmationProvider(console=console)
        outcome = provider.confirm(
            tool_name="dangerous_tool",
            tool_description="d",
            tool_args={},
            risk_tier=RiskTier.CRITICAL,
        )
    assert outcome.decision == Decision.APPROVED
    mock_sleep.assert_called_once()
    wait_seconds = mock_sleep.call_args[0][0]
    assert wait_seconds >= 1


def test_tier_4_rejects_when_wrong_name_typed() -> None:
    console = _make_console()
    with (
        patch.object(console, "input", return_value="not_the_tool"),
        patch("muru.policy.confirmation.cli.time.sleep"),
    ):
        provider = CliConfirmationProvider(console=console)
        outcome = provider.confirm(
            tool_name="dangerous_tool",
            tool_description="d",
            tool_args={},
            risk_tier=RiskTier.CRITICAL,
        )
    assert outcome.decision == Decision.REJECTED


# ----- EOF / Ctrl-C handling -----


def test_tier_2_returns_rejected_on_eof() -> None:
    console = _make_console()
    with patch.object(console, "input", side_effect=EOFError()):
        provider = CliConfirmationProvider(console=console)
        outcome = provider.confirm(
            tool_name="t",
            tool_description="d",
            tool_args={},
            risk_tier=RiskTier.MEDIUM_RISK,
        )
    assert outcome.decision == Decision.REJECTED


def test_tier_3_returns_rejected_on_keyboard_interrupt() -> None:
    console = _make_console()
    with patch.object(console, "input", side_effect=KeyboardInterrupt()):
        provider = CliConfirmationProvider(console=console)
        outcome = provider.confirm(
            tool_name="t",
            tool_description="d",
            tool_args={},
            risk_tier=RiskTier.HIGH_RISK,
        )
    assert outcome.decision == Decision.REJECTED


# ----- Plan rendering -----


def test_plan_rendering_shows_tool_name_and_tier_label() -> None:
    buf = io.StringIO()
    console = Console(file=buf, width=80, force_terminal=False, color_system=None)
    with patch.object(console, "input", return_value="n"):
        provider = CliConfirmationProvider(console=console)
        provider.confirm(
            tool_name="my_special_tool",
            tool_description="It does a thing.",
            tool_args={"path": "/x"},
            risk_tier=RiskTier.MEDIUM_RISK,
        )
    output = buf.getvalue()
    assert "my_special_tool" in output
    assert "Medium risk" in output
