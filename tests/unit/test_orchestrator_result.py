"""Tests for muru.orchestrator.result.OrchestratorResult."""

from __future__ import annotations

from muru.orchestrator.result import OrchestratorResult
from muru.planner.plan import Plan


def test_minimal_result_with_just_response() -> None:
    r = OrchestratorResult(
        intent="hi",
        final_response="hello there",
    )
    assert r.intent == "hi"
    assert r.final_response == "hello there"
    assert r.plan is None
    assert r.tool_result is None
    assert r.error is None


def test_result_with_plan() -> None:
    plan = Plan(needs_tool=False, response="hi")
    r = OrchestratorResult(intent="hi", final_response="hi", plan=plan)
    assert r.plan is plan


def test_result_with_tool() -> None:
    plan = Plan(needs_tool=True, tool_name="x", tool_args={})
    r = OrchestratorResult(
        intent="do x",
        final_response="ok",
        plan=plan,
        tool_result={"success": True, "message": "did it"},
    )
    assert r.tool_result is not None
    assert r.tool_result["success"] is True


def test_result_with_error() -> None:
    r = OrchestratorResult(
        intent="bad",
        final_response="something went wrong",
        error="PlannerError: bad",
    )
    assert r.error == "PlannerError: bad"
