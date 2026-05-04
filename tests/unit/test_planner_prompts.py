"""Tests for muru.planner.prompts."""

from __future__ import annotations

from muru.planner.prompts import (
    build_correction_message,
    build_planner_system_prompt,
    format_tool_for_prompt,
)


def test_format_tool_includes_name_and_description() -> None:
    schema = {
        "name": "demo",
        "description": "A demo tool.",
        "parameters": {"properties": {}, "required": []},
    }
    formatted = format_tool_for_prompt(schema)
    assert "demo" in formatted
    assert "demo tool" in formatted


def test_format_tool_marks_required_args() -> None:
    schema = {
        "name": "demo",
        "description": "x",
        "parameters": {
            "properties": {
                "path": {"type": "string", "description": "the path"},
            },
            "required": ["path"],
        },
    }
    formatted = format_tool_for_prompt(schema)
    assert "path" in formatted
    assert "(required)" in formatted


def test_format_tool_marks_optional_args() -> None:
    schema = {
        "name": "demo",
        "description": "x",
        "parameters": {
            "properties": {
                "verbose": {
                    "type": "boolean",
                    "description": "be verbose",
                    "default": False,
                },
            },
            "required": [],
        },
    }
    formatted = format_tool_for_prompt(schema)
    assert "(optional)" in formatted
    assert "default" in formatted.lower()


def test_format_tool_handles_no_args() -> None:
    schema = {
        "name": "demo",
        "description": "x",
        "parameters": {"properties": {}, "required": []},
    }
    formatted = format_tool_for_prompt(schema)
    assert "no arguments" in formatted.lower()


def test_build_planner_system_prompt_with_tools() -> None:
    schemas = [
        {
            "name": "alpha",
            "description": "A tool.",
            "parameters": {"properties": {}, "required": []},
        },
        {
            "name": "beta",
            "description": "Another tool.",
            "parameters": {"properties": {}, "required": []},
        },
    ]
    prompt = build_planner_system_prompt(schemas)
    assert "alpha" in prompt
    assert "beta" in prompt
    assert "JSON" in prompt


def test_build_planner_system_prompt_with_no_tools() -> None:
    prompt = build_planner_system_prompt([])
    assert "no tools" in prompt.lower()


def test_correction_message_includes_error() -> None:
    msg = build_correction_message("missing field 'foo'", "{}")
    assert "missing field 'foo'" in msg
    assert "JSON" in msg


def test_correction_message_truncates_long_response() -> None:
    long = "x" * 5000
    msg = build_correction_message("err", long)
    assert "(truncated)" in msg
