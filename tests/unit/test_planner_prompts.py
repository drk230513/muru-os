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


# ============================================
# v0.3.1 prompt-tuning guarantees
# ============================================


def test_prompt_includes_recursive_guidance() -> None:
    """The planner must guide LLMs toward recursive=true for project folders.

    Regression guard for v0.3.0's bug where Llama 3.1 8B defaulted
    recursive=False on 'files in my X folder' queries.
    """
    from muru.planner.prompts import PLANNER_SYSTEM_TEMPLATE

    assert "recursive=true" in PLANNER_SYSTEM_TEMPLATE
    assert "Top-level-only" in PLANNER_SYSTEM_TEMPLATE


def test_prompt_includes_tilde_slash_guidance() -> None:
    """The planner must guide LLMs to use '~/' not '~name'.

    Regression guard for v0.3.0 where Llama produced '~muru-os'
    (no slash), which caused 'Could not determine home directory' errors.
    """
    from muru.planner.prompts import PLANNER_SYSTEM_TEMPLATE

    assert '"~/" with a slash' in PLANNER_SYSTEM_TEMPLATE
    assert '"~muru-os"' in PLANNER_SYSTEM_TEMPLATE  # the wrong form, called out as bad


def test_prompt_includes_history_first_section() -> None:
    """The prompt must instruct the LLM to use conversation history before re-running tools.

    Without this, every follow-up question runs a fresh tool call.
    """
    from muru.planner.prompts import PLANNER_SYSTEM_TEMPLATE

    assert "USING CONVERSATION HISTORY" in PLANNER_SYSTEM_TEMPLATE
    assert "DO NOT call a tool again" in PLANNER_SYSTEM_TEMPLATE


def test_prompt_includes_recursive_example() -> None:
    """Concrete example of when to use recursive=true must be present.

    Examples teach better than prose. The 'count python files in muru-os'
    example shows Llama the right shape to copy.
    """
    from muru.planner.prompts import PLANNER_SYSTEM_TEMPLATE

    assert "count python files" in PLANNER_SYSTEM_TEMPLATE
    assert '"recursive": true' in PLANNER_SYSTEM_TEMPLATE
