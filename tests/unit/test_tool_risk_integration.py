"""Tests that Tool wrappers correctly carry and expose RiskTier."""

from __future__ import annotations

from pydantic import BaseModel

from muru.policy.risk import RiskTier
from muru.tools.base import Tool, ToolResult


class _Args(BaseModel):
    pass


class _Result(ToolResult):
    pass


def _impl(args: _Args) -> _Result:
    return _Result(success=True, message="ok")


def test_default_risk_tier_is_read_only() -> None:
    """Tools that don't specify a tier default to READ_ONLY for safety."""
    tool = Tool(
        name="t",
        description="d",
        args_model=_Args,
        result_model=_Result,
        implementation=_impl,
    )
    assert tool.risk_tier == RiskTier.READ_ONLY


def test_explicit_tier_is_stored() -> None:
    tool = Tool(
        name="t",
        description="d",
        args_model=_Args,
        result_model=_Result,
        implementation=_impl,
        risk_tier=RiskTier.HIGH_RISK,
    )
    assert tool.risk_tier == RiskTier.HIGH_RISK


def test_schema_includes_tier_int() -> None:
    tool = Tool(
        name="t",
        description="d",
        args_model=_Args,
        result_model=_Result,
        implementation=_impl,
        risk_tier=RiskTier.MEDIUM_RISK,
    )
    schema = tool.schema()
    assert schema["risk_tier"] == 2


def test_schema_includes_tier_label() -> None:
    tool = Tool(
        name="t",
        description="d",
        args_model=_Args,
        result_model=_Result,
        implementation=_impl,
        risk_tier=RiskTier.CRITICAL,
    )
    schema = tool.schema()
    assert schema["risk_tier_label"] == "Critical"


def test_existing_filesystem_tools_are_all_tier_0() -> None:
    """Sanity check: all 4 existing read-only tools must declare Tier 0.

    If a future change accidentally bumps one without updating its tier,
    this test catches it.
    """
    from muru.tools import filesystem  # noqa: F401
    from muru.tools.registry import registry

    expected = {"list_directory", "read_file", "get_file_info", "search_files"}
    for tool in registry.list_tools():
        if tool.name in expected:
            assert tool.risk_tier == RiskTier.READ_ONLY, (
                f"Tool {tool.name} should be Tier 0 (read-only)"
            )
