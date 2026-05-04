"""Tests for muru.policy.risk."""

from __future__ import annotations

from muru.policy.risk import RiskTier


def test_tiers_are_ordered() -> None:
    assert RiskTier.READ_ONLY < RiskTier.LOW_RISK
    assert RiskTier.LOW_RISK < RiskTier.MEDIUM_RISK
    assert RiskTier.MEDIUM_RISK < RiskTier.HIGH_RISK
    assert RiskTier.HIGH_RISK < RiskTier.CRITICAL


def test_int_values_match_tier_meaning() -> None:
    assert int(RiskTier.READ_ONLY) == 0
    assert int(RiskTier.LOW_RISK) == 1
    assert int(RiskTier.MEDIUM_RISK) == 2
    assert int(RiskTier.HIGH_RISK) == 3
    assert int(RiskTier.CRITICAL) == 4


def test_display_names_are_human_friendly() -> None:
    assert RiskTier.READ_ONLY.display_name == "Read-only"
    assert RiskTier.CRITICAL.display_name == "Critical"


def test_auto_execute_is_true_for_tier_0() -> None:
    assert RiskTier.READ_ONLY.auto_execute is True


def test_auto_execute_is_true_for_tier_1() -> None:
    """Tier 1 also auto-executes (just logged). This is policy."""
    assert RiskTier.LOW_RISK.auto_execute is True


def test_auto_execute_is_false_for_tier_2_and_above() -> None:
    assert RiskTier.MEDIUM_RISK.auto_execute is False
    assert RiskTier.HIGH_RISK.auto_execute is False
    assert RiskTier.CRITICAL.auto_execute is False
