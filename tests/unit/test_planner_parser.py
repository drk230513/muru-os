"""Tests for muru.planner.parser."""

from __future__ import annotations

import pytest

from muru.planner.parser import PlanParseError, parse_plan


def test_parses_clean_json() -> None:
    raw = '{"needs_tool": false, "response": "hi"}'
    plan = parse_plan(raw)
    assert plan.needs_tool is False
    assert plan.response == "hi"


def test_parses_json_in_markdown_code_block() -> None:
    raw = '```json\n{"needs_tool": false, "response": "hi"}\n```'
    plan = parse_plan(raw)
    assert plan.response == "hi"


def test_parses_json_in_unmarked_code_block() -> None:
    raw = '```\n{"needs_tool": false, "response": "hi"}\n```'
    plan = parse_plan(raw)
    assert plan.response == "hi"


def test_parses_json_with_chatter_before() -> None:
    raw = 'Sure! Here is the plan:\n{"needs_tool": false, "response": "hi"}'
    plan = parse_plan(raw)
    assert plan.response == "hi"


def test_parses_json_with_chatter_after() -> None:
    raw = '{"needs_tool": false, "response": "hi"}\nLet me know if you need more!'
    plan = parse_plan(raw)
    assert plan.response == "hi"


def test_parses_tool_plan() -> None:
    raw = (
        '{"needs_tool": true, "tool_name": "list_directory", '
        '"tool_args": {"path": "~", "pattern": "*.py"}}'
    )
    plan = parse_plan(raw)
    assert plan.needs_tool is True
    assert plan.tool_name == "list_directory"
    assert plan.tool_args == {"path": "~", "pattern": "*.py"}


def test_empty_response_raises() -> None:
    with pytest.raises(PlanParseError, match=r"Empty response"):
        parse_plan("")


def test_invalid_json_raises_with_helpful_error() -> None:
    with pytest.raises(PlanParseError, match=r"not valid JSON"):
        parse_plan("not json at all")


def test_non_object_top_level_raises() -> None:
    with pytest.raises(PlanParseError, match=r"must be an object"):
        parse_plan("[1, 2, 3]")


def test_validation_failure_includes_field() -> None:
    raw = '{"needs_tool": true}'
    with pytest.raises(PlanParseError, match=r"tool_name"):
        parse_plan(raw)


def test_handles_nested_braces_in_strings() -> None:
    raw = '{"needs_tool": false, "response": "Use {curly} braces in code"}'
    plan = parse_plan(raw)
    assert plan.response == "Use {curly} braces in code"
