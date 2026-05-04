"""Central catalog of all available Muru tools.

Tools register themselves with the registry at import time (or via
explicit registration). The registry provides:
    - lookup by name
    - listing all tools
    - generating a combined schema for the LLM
    - validated invocation

Usage:
    from muru.tools.registry import registry
    from muru.tools.filesystem.list_directory import list_directory_tool

    registry.register(list_directory_tool)

    # Later, from anywhere:
    result = registry.invoke("list_directory", {"path": "/home/me"})
"""

from __future__ import annotations

from typing import Any

from muru.tools.base import Tool, ToolNotFoundError
from muru.utils.logging import get_logger

log = get_logger(__name__)


class ToolRegistry:
    """In-memory catalog of tools.

    Singleton-by-convention: the module-level `registry` instance is
    used throughout Muru. Tests can construct their own ToolRegistry
    instances for isolation.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool[Any, Any]] = {}

    def register(self, tool: Tool[Any, Any]) -> None:
        """Register a tool. Raises ValueError if the name is already taken."""
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name!r} already registered. Tool names must be unique.")
        self._tools[tool.name] = tool
        log.debug("tool_registered", tool=tool.name)

    def unregister(self, name: str) -> None:
        """Remove a tool by name. Useful in tests; rare in production."""
        if name in self._tools:
            del self._tools[name]
            log.debug("tool_unregistered", tool=name)

    def get(self, name: str) -> Tool[Any, Any]:
        """Look up a tool by name.

        Raises:
            ToolNotFoundError: If no tool with that name is registered.
        """
        if name not in self._tools:
            raise ToolNotFoundError(
                f"No tool named {name!r}. Available: {sorted(self._tools.keys())}"
            )
        return self._tools[name]

    def list_names(self) -> list[str]:
        """Return all registered tool names, sorted."""
        return sorted(self._tools.keys())

    def list_tools(self) -> list[Tool[Any, Any]]:
        """Return all registered tools, sorted by name."""
        return [self._tools[name] for name in self.list_names()]

    def schemas_for_llm(self) -> list[dict[str, Any]]:
        """Return JSON schemas for all tools, suitable for inclusion in an LLM prompt."""
        return [t.schema() for t in self.list_tools()]

    def invoke(self, name: str, raw_args: dict[str, Any]) -> Any:
        """Invoke a tool by name with the given arguments.

        This is the public entry point; goes through validation and
        error handling.
        """
        tool = self.get(name)
        return tool.invoke(raw_args)

    def clear(self) -> None:
        """Remove all registered tools. Test-only."""
        self._tools.clear()


# The default global registry. Tools register themselves here at import time.
# In tests, you can construct a fresh ToolRegistry() for isolation.
registry = ToolRegistry()


__all__ = ["ToolRegistry", "registry"]
