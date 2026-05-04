"""Tests for muru.planner.plan."""

from __future__ import annotations

import pytest

from muru.planner.plan import Plan


def test_pure_response_plan_valid() -> None:
    p = Plan(needs_tool=False, response="hello")
    assert p.response == "hello"
    assert p.tool_name is None


def test_tool_plan_valid() -> None:
    p = Plan(needs_tool=True, tool_name="list_directory", tool_args={"path": "~"})
    assert p.tool_name == "list_directory"
    assert p.tool_args == {"path": "~"}


def test_tool_plan_with_no_args_coerces_to_empty_dict() -> None:
    p = Plan(needs_tool=True, tool_name="some_tool")
    assert p.tool_args == {}


def test_response_plan_without_response_invalid() -> None:
    with pytest.raises(ValueError, match=r"response.*non-empty"):
        Plan(needs_tool=False)


def test_response_plan_with_empty_response_invalid() -> None:
    with pytest.raises(ValueError, match=r"response.*non-empty"):
        Plan(needs_tool=False, response="")


def test_tool_plan_without_tool_name_invalid() -> None:
    with pytest.raises(ValueError, match=r"tool_name to be set"):
        Plan(needs_tool=True)


def test_response_plan_with_tool_name_invalid() -> None:
    with pytest.raises(ValueError, match=r"cannot have tool_name"):
        Plan(needs_tool=False, response="hi", tool_name="x")


def test_tool_plan_with_response_invalid() -> None:
    with pytest.raises(ValueError, match=r"cannot also have a 'response'"):
        Plan(needs_tool=True, tool_name="x", response="hi")
