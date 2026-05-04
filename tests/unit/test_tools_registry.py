"""Tests for muru.tools.registry — the central tool catalog."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from muru.tools.base import Tool, ToolNotFoundError, ToolResult
from muru.tools.registry import ToolRegistry


class _Args(BaseModel):
    pass


class _Result(ToolResult):
    pass


def _impl(args: _Args) -> _Result:
    return _Result(success=True, message="ok")


def _make_tool(name: str) -> Tool[_Args, _Result]:
    return Tool(
        name=name,
        description=f"Tool {name}",
        args_model=_Args,
        result_model=_Result,
        implementation=_impl,
    )


def test_register_and_get() -> None:
    reg = ToolRegistry()
    tool = _make_tool("alpha")
    reg.register(tool)
    assert reg.get("alpha") is tool


def test_register_duplicate_raises() -> None:
    reg = ToolRegistry()
    reg.register(_make_tool("alpha"))
    with pytest.raises(ValueError, match="already registered"):
        reg.register(_make_tool("alpha"))


def test_get_unknown_raises_not_found() -> None:
    reg = ToolRegistry()
    with pytest.raises(ToolNotFoundError, match="No tool named"):
        reg.get("nonexistent")


def test_list_names_returns_sorted() -> None:
    reg = ToolRegistry()
    reg.register(_make_tool("zebra"))
    reg.register(_make_tool("alpha"))
    reg.register(_make_tool("monkey"))
    assert reg.list_names() == ["alpha", "monkey", "zebra"]


def test_unregister_removes_tool() -> None:
    reg = ToolRegistry()
    reg.register(_make_tool("alpha"))
    reg.unregister("alpha")
    assert "alpha" not in reg.list_names()


def test_unregister_unknown_is_no_op() -> None:
    reg = ToolRegistry()
    reg.unregister("nope")  # Should not raise


def test_invoke_via_registry() -> None:
    reg = ToolRegistry()
    reg.register(_make_tool("alpha"))
    result = reg.invoke("alpha", {})
    assert result.success is True


def test_schemas_for_llm_returns_list() -> None:
    reg = ToolRegistry()
    reg.register(_make_tool("alpha"))
    reg.register(_make_tool("beta"))
    schemas = reg.schemas_for_llm()
    assert len(schemas) == 2
    assert {s["name"] for s in schemas} == {"alpha", "beta"}


def test_clear_removes_all() -> None:
    reg = ToolRegistry()
    reg.register(_make_tool("alpha"))
    reg.register(_make_tool("beta"))
    reg.clear()
    assert reg.list_names() == []
