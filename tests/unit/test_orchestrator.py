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


# ============================================
# Confirmation provider integration (v0.3.0)
# ============================================


def test_handle_calls_confirmation_provider_for_tool_plans(
    mock_llm: MagicMock, mock_planner: MagicMock, registry: ToolRegistry
) -> None:
    """Orchestrator should call confirmation_provider.confirm() before running a tool."""
    from muru.policy.confirmation import ConfirmationOutcome, Decision

    mock_planner.plan.return_value = Plan(needs_tool=True, tool_name="ok_tool", tool_args={})
    mock_llm.chat.return_value = "summary"

    mock_provider = MagicMock()
    mock_provider.confirm.return_value = ConfirmationOutcome(decision=Decision.APPROVED)

    orch = Orchestrator(
        llm=mock_llm,
        planner=mock_planner,
        registry=registry,
        confirmation_provider=mock_provider,
    )
    orch.handle("do thing")

    mock_provider.confirm.assert_called_once()
    # Confirm the args include tool name and tier
    call_kwargs = mock_provider.confirm.call_args[1]
    assert call_kwargs["tool_name"] == "ok_tool"
    # ok_tool was registered with default tier (READ_ONLY)
    from muru.policy.risk import RiskTier

    assert call_kwargs["risk_tier"] == RiskTier.READ_ONLY


def test_handle_returns_decline_when_confirmation_rejected(
    mock_llm: MagicMock, mock_planner: MagicMock, registry: ToolRegistry
) -> None:
    """If confirmation provider says REJECTED, tool must not run."""
    from muru.policy.confirmation import ConfirmationOutcome, Decision

    mock_planner.plan.return_value = Plan(needs_tool=True, tool_name="ok_tool", tool_args={})

    mock_provider = MagicMock()
    mock_provider.confirm.return_value = ConfirmationOutcome(
        decision=Decision.REJECTED, reason="User said no"
    )

    orch = Orchestrator(
        llm=mock_llm,
        planner=mock_planner,
        registry=registry,
        confirmation_provider=mock_provider,
    )
    result = orch.handle("do thing")

    assert result.tool_result is None
    assert (
        "will not" in result.final_response.lower()
        or "won't" in result.final_response.lower()
        or "not run" in result.final_response.lower()
    )
    # The LLM summarizer should NOT have been called
    mock_llm.chat.assert_not_called()


def test_handle_works_without_confirmation_provider(
    mock_llm: MagicMock, mock_planner: MagicMock, registry: ToolRegistry
) -> None:
    """When confirmation_provider is None (default), tools auto-execute."""
    mock_planner.plan.return_value = Plan(needs_tool=True, tool_name="ok_tool", tool_args={})
    mock_llm.chat.return_value = "summary"

    # No confirmation_provider argument - should auto-execute
    orch = Orchestrator(llm=mock_llm, planner=mock_planner, registry=registry)
    result = orch.handle("do thing")

    assert result.tool_result is not None
    assert result.tool_result["success"] is True


# ============================================
# Conversation history (v0.3.0)
# ============================================


def test_handle_passes_history_to_planner(
    mock_llm: MagicMock, mock_planner: MagicMock, registry: ToolRegistry
) -> None:
    """When history is provided, it should reach the planner."""
    mock_planner.plan.return_value = Plan(needs_tool=False, response="ok")

    history = [
        {"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": "earlier answer"},
    ]

    orch = Orchestrator(llm=mock_llm, planner=mock_planner, registry=registry)
    orch.handle("follow-up question", history=history)

    mock_planner.plan.assert_called_once()
    # Check that history was passed as keyword arg
    _, kwargs = mock_planner.plan.call_args
    assert kwargs.get("history") == history


def test_handle_works_without_history(
    mock_llm: MagicMock, mock_planner: MagicMock, registry: ToolRegistry
) -> None:
    """When history is None or omitted, planner gets None."""
    mock_planner.plan.return_value = Plan(needs_tool=False, response="ok")

    orch = Orchestrator(llm=mock_llm, planner=mock_planner, registry=registry)
    orch.handle("hello")

    _, kwargs = mock_planner.plan.call_args
    assert kwargs.get("history") is None
