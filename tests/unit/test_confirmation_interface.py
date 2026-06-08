"""Tests for muru.policy.confirmation (interface and helpers)."""

from __future__ import annotations

from muru.policy.confirmation import (
    ConfirmationOutcome,
    Decision,
    auto_approve,
)
from muru.policy.risk import RiskTier


def test_decision_values() -> None:
    assert Decision.APPROVED.value == "approved"
    assert Decision.REJECTED.value == "rejected"
    assert Decision.MODIFIED.value == "modified"


def test_confirmation_outcome_is_immutable() -> None:
    outcome = ConfirmationOutcome(decision=Decision.APPROVED)
    try:
        outcome.decision = Decision.REJECTED  # type: ignore[misc]
    except (AttributeError, Exception):
        return
    raise AssertionError("ConfirmationOutcome should be frozen")


def test_outcome_defaults() -> None:
    outcome = ConfirmationOutcome(decision=Decision.APPROVED)
    assert outcome.modified_args is None
    assert outcome.reason is None


def test_auto_approve_returns_approved() -> None:
    outcome = auto_approve("list_directory", RiskTier.READ_ONLY)
    assert outcome.decision == Decision.APPROVED


def test_auto_approve_reason_mentions_tier_and_tool() -> None:
    outcome = auto_approve("list_directory", RiskTier.READ_ONLY)
    assert outcome.reason is not None
    assert "list_directory" in outcome.reason
    assert "Read-only" in outcome.reason
