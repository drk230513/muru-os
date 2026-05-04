"""Tests for muru.orchestrator.orchestrator.Orchestrator."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from muru.orchestrator.orchestrator import Orchestrator
from muru.planner.plan import Plan
from muru.planner.planner import PlannerError
from muru.tools.base import Tool, ToolResult
from muru.tools.registry import ToolRegistry


class _Args(BaseModel):
    pass


class _Result(ToolResult):
    extra: str = "default"


def _ok_impl(args: _Args) -> _Result:
    return _Result(success=True, message="tool worked", extra="some data")


def _fail_impl(args: _Args) -> _Result:
    return _Result(success=False, message="file not found", extra="")


def _crash_impl(args: _Args) -> _Result:
    raise RuntimeError("boom")


def _make_tool(name: str, impl: object) -> Tool[_Args, _Result]:
    return Tool(
        name=name,
        description=f"{name} for tests",
        args_model=_Args,
        result_model=_Result,
        implementation=impl,  # type: ignore[arg-type]
    )


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(_make_tool("ok_tool", _ok_impl))
    reg.register(_make_tool("fail_tool", _fail_impl))
    reg.register(_make_tool("crash_tool", _crash_impl))
    return reg


@pytest.fixture
def mock_llm() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_planner() -> MagicMock:
    return MagicMock()


def test_handle_returns_response_for_conversational_plan(
    mock_llm: MagicMock, mock_planner: MagicMock, registry: ToolRegistry
) -> None:
    mock_planner.plan.return_value = Plan(needs_tool=False, response="hello!")
    orch = Orchestrator(llm=mock_llm, planner=mock_planner, registry=registry)

    result = orch.handle("hi")

    assert result.final_response == "hello!"
    assert result.plan is not None
    assert result.plan.needs_tool is False
    assert result.tool_result is None
    assert result.error is None
    mock_llm.chat.assert_not_called()


def test_handle_invokes_tool_and_summarizes(
    mock_llm: MagicMock, mock_planner: MagicMock, registry: ToolRegistry
) -> None:
    mock_planner.plan.return_value = Plan(needs_tool=True, tool_name="ok_tool", tool_args={})
    mock_llm.chat.return_value = "Friendly summary of the result."

    orch = Orchestrator(llm=mock_llm, planner=mock_planner, registry=registry)
    result = orch.handle("do thing")

    assert result.final_response == "Friendly summary of the result."
    assert result.tool_result is not None
    assert result.tool_result["success"] is True
    assert result.tool_result["extra"] == "some data"
    assert result.error is None


def test_handle_with_tool_returning_failure(
    mock_llm: MagicMock, mock_planner: MagicMock, registry: ToolRegistry
) -> None:
    """Tool returns success=False — orchestrator still summarizes (no error)."""
    mock_planner.plan.return_value = Plan(needs_tool=True, tool_name="fail_tool", tool_args={})
    mock_llm.chat.return_value = "I couldn't find that file."

    orch = Orchestrator(llm=mock_llm, planner=mock_planner, registry=registry)
    result = orch.handle("read something")

    assert result.final_response == "I couldn't find that file."
    assert result.tool_result is not None
    assert result.tool_result["success"] is False
    assert result.error is None


def test_handle_when_planner_raises(
    mock_llm: MagicMock, mock_planner: MagicMock, registry: ToolRegistry
) -> None:
    mock_planner.plan.side_effect = PlannerError("could not parse")
    orch = Orchestrator(llm=mock_llm, planner=mock_planner, registry=registry)

    result = orch.handle("anything")

    assert result.error is not None
    assert "PlannerError" in result.error
    assert result.plan is None
    assert "rephrase" in result.final_response.lower()


def test_handle_when_tool_crashes(
    mock_llm: MagicMock, mock_planner: MagicMock, registry: ToolRegistry
) -> None:
    """Tool raises an exception — orchestrator catches and explains."""
    mock_planner.plan.return_value = Plan(needs_tool=True, tool_name="crash_tool", tool_args={})
    mock_llm.chat.return_value = "Something went wrong with the tool."

    orch = Orchestrator(llm=mock_llm, planner=mock_planner, registry=registry)
    result = orch.handle("crash please")

    assert result.error is not None
    assert "ToolError" in result.error or "crash" in result.error.lower()
    assert result.tool_result is None
    assert result.final_response == "Something went wrong with the tool."


def test_handle_when_summarizer_fails_falls_back(
    mock_llm: MagicMock, mock_planner: MagicMock, registry: ToolRegistry
) -> None:
    """Summarizer LLM call fails — orchestrator falls back to tool's message."""
    mock_planner.plan.return_value = Plan(needs_tool=True, tool_name="ok_tool", tool_args={})
    mock_llm.chat.side_effect = RuntimeError("LLM is down")

    orch = Orchestrator(llm=mock_llm, planner=mock_planner, registry=registry)
    result = orch.handle("do thing")

    assert result.final_response == "tool worked"
    assert result.error is not None
    assert "SummarizerError" in result.error


def test_handle_passes_tool_args_to_registry(
    mock_llm: MagicMock, mock_planner: MagicMock, registry: ToolRegistry
) -> None:
    mock_planner.plan.return_value = Plan(needs_tool=True, tool_name="ok_tool", tool_args={})
    mock_llm.chat.return_value = "summary"

    orch = Orchestrator(llm=mock_llm, planner=mock_planner, registry=registry)
    orch.handle("do thing")

    assert mock_llm.chat.called
    sent_messages = mock_llm.chat.call_args[0][0]
    user_msg = sent_messages[1]["content"]
    assert "ok_tool" in user_msg
