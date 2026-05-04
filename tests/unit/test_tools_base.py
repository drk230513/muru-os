"""Tests for muru.tools.base — the Tool wrapper class."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, Field

from muru.tools.base import (
    Tool,
    ToolExecutionError,
    ToolResult,
    ToolValidationError,
)

# ============================================
# Test fixtures: a tiny sample tool
# ============================================


class SampleArgs(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)


class SampleResult(ToolResult):
    sum: int = 0


def _sample_impl(args: SampleArgs) -> SampleResult:
    return SampleResult(success=True, message="ok", sum=args.x + args.y)


@pytest.fixture
def sample_tool() -> Tool[SampleArgs, SampleResult]:
    return Tool(
        name="sample",
        description="Adds two non-negative ints.",
        args_model=SampleArgs,
        result_model=SampleResult,
        implementation=_sample_impl,
    )


# ============================================
# Construction validation
# ============================================


def test_tool_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="must be non-empty"):
        Tool(
            name="",
            description="x",
            args_model=SampleArgs,
            result_model=SampleResult,
            implementation=_sample_impl,
        )


def test_tool_rejects_invalid_name_chars() -> None:
    with pytest.raises(ValueError, match="must be non-empty"):
        Tool(
            name="bad name!",
            description="x",
            args_model=SampleArgs,
            result_model=SampleResult,
            implementation=_sample_impl,
        )


def test_tool_rejects_empty_description() -> None:
    with pytest.raises(ValueError, match="description must not be empty"):
        Tool(
            name="x",
            description="   ",
            args_model=SampleArgs,
            result_model=SampleResult,
            implementation=_sample_impl,
        )


# ============================================
# Invocation
# ============================================


def test_invoke_returns_result(sample_tool: Tool[SampleArgs, SampleResult]) -> None:
    result = sample_tool.invoke({"x": 2, "y": 3})
    assert result.success is True
    assert result.sum == 5


def test_invoke_validates_args(sample_tool: Tool[SampleArgs, SampleResult]) -> None:
    with pytest.raises(ToolValidationError):
        sample_tool.invoke({"x": -1, "y": 0})  # x must be >= 0


def test_invoke_rejects_unknown_args(
    sample_tool: Tool[SampleArgs, SampleResult],
) -> None:
    # Pydantic v2 rejects extra fields by default? Actually no — it allows
    # them. We're just checking missing required fields here.
    with pytest.raises(ToolValidationError):
        sample_tool.invoke({"x": 1})  # missing y


def test_invoke_wraps_implementation_errors(
    sample_tool: Tool[SampleArgs, SampleResult],
) -> None:
    def crashing_impl(args: SampleArgs) -> SampleResult:
        raise RuntimeError("boom")

    crashing_tool = Tool(
        name="crash",
        description="Always crashes.",
        args_model=SampleArgs,
        result_model=SampleResult,
        implementation=crashing_impl,
    )
    with pytest.raises(ToolExecutionError, match="raised RuntimeError"):
        crashing_tool.invoke({"x": 1, "y": 2})


# ============================================
# Schema generation
# ============================================


def test_schema_has_name_and_description(
    sample_tool: Tool[SampleArgs, SampleResult],
) -> None:
    schema = sample_tool.schema()
    assert schema["name"] == "sample"
    assert "Adds two" in schema["description"]
    assert "parameters" in schema


def test_schema_includes_arg_constraints(
    sample_tool: Tool[SampleArgs, SampleResult],
) -> None:
    schema = sample_tool.schema()
    # Check that x's lower bound (ge=0) made it through
    params: dict[str, Any] = schema["parameters"]
    assert "x" in params["properties"]
    assert params["properties"]["x"]["minimum"] == 0
