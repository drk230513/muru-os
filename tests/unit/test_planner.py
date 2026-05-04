"""Tests for muru.planner.planner.Planner."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from muru.planner.planner import Planner, PlannerError
from muru.tools.base import Tool, ToolResult
from muru.tools.registry import ToolRegistry


class _Args(BaseModel):
    pass


class _Result(ToolResult):
    pass


def _impl(args: _Args) -> _Result:
    return _Result(success=True, message="ok")


@pytest.fixture
def registry_with_one_tool() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        Tool(
            name="dummy",
            description="A dummy tool for testing.",
            args_model=_Args,
            result_model=_Result,
            implementation=_impl,
        )
    )
    return reg


@pytest.fixture
def empty_registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture
def mock_llm() -> MagicMock:
    return MagicMock()


def test_planner_returns_response_plan(
    mock_llm: MagicMock, registry_with_one_tool: ToolRegistry
) -> None:
    mock_llm.chat.return_value = '{"needs_tool": false, "response": "hi"}'
    planner = Planner(llm=mock_llm, registry=registry_with_one_tool)
    plan = planner.plan("hello")
    assert plan.needs_tool is False
    assert plan.response == "hi"


def test_planner_returns_tool_plan(
    mock_llm: MagicMock, registry_with_one_tool: ToolRegistry
) -> None:
    mock_llm.chat.return_value = '{"needs_tool": true, "tool_name": "dummy", "tool_args": {}}'
    planner = Planner(llm=mock_llm, registry=registry_with_one_tool)
    plan = planner.plan("do something")
    assert plan.needs_tool is True
    assert plan.tool_name == "dummy"


def test_planner_retries_on_bad_json(
    mock_llm: MagicMock, registry_with_one_tool: ToolRegistry
) -> None:
    mock_llm.chat.side_effect = [
        "this is not json",
        '{"needs_tool": false, "response": "hi"}',
    ]
    planner = Planner(llm=mock_llm, registry=registry_with_one_tool, max_retries=1)
    plan = planner.plan("hello")
    assert plan.response == "hi"
    assert mock_llm.chat.call_count == 2


def test_planner_gives_up_after_max_retries(
    mock_llm: MagicMock, registry_with_one_tool: ToolRegistry
) -> None:
    mock_llm.chat.return_value = "still not json"
    planner = Planner(llm=mock_llm, registry=registry_with_one_tool, max_retries=2)
    with pytest.raises(PlannerError, match=r"failed after"):
        planner.plan("hello")
    assert mock_llm.chat.call_count == 3


def test_planner_rejects_unknown_tool(
    mock_llm: MagicMock, registry_with_one_tool: ToolRegistry
) -> None:
    mock_llm.chat.side_effect = [
        '{"needs_tool": true, "tool_name": "unknown_tool", "tool_args": {}}',
        '{"needs_tool": false, "response": "ok then"}',
    ]
    planner = Planner(llm=mock_llm, registry=registry_with_one_tool, max_retries=1)
    plan = planner.plan("do thing")
    assert plan.needs_tool is False
    assert mock_llm.chat.call_count == 2


def test_planner_rejects_empty_intent(
    mock_llm: MagicMock, registry_with_one_tool: ToolRegistry
) -> None:
    planner = Planner(llm=mock_llm, registry=registry_with_one_tool)
    with pytest.raises(PlannerError, match=r"non-empty"):
        planner.plan("")


def test_planner_works_with_empty_registry(
    mock_llm: MagicMock, empty_registry: ToolRegistry
) -> None:
    mock_llm.chat.return_value = '{"needs_tool": false, "response": "no tools yet"}'
    planner = Planner(llm=mock_llm, registry=empty_registry)
    plan = planner.plan("hi")
    assert plan.needs_tool is False


def test_planner_passes_system_prompt_with_tools(
    mock_llm: MagicMock, registry_with_one_tool: ToolRegistry
) -> None:
    mock_llm.chat.return_value = '{"needs_tool": false, "response": "hi"}'
    planner = Planner(llm=mock_llm, registry=registry_with_one_tool)
    planner.plan("hello")

    call_args = mock_llm.chat.call_args
    messages = call_args[0][0]
    system = messages[0]
    assert system["role"] == "system"
    assert "dummy" in system["content"]
