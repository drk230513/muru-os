"""Shell tools for Muru.

Importing this package auto-registers all shell tools with the
default registry. Same pattern as muru.tools.filesystem.
"""

from __future__ import annotations

from typing import Any

from muru.tools.base import Tool
from muru.tools.registry import registry
from muru.tools.shell.run_shell import run_shell_tool

_SHELL_TOOLS: list[Tool[Any, Any]] = [
    run_shell_tool,
]

for _tool in _SHELL_TOOLS:
    if _tool.name not in registry.list_names():
        registry.register(_tool)

__all__ = ["run_shell_tool"]
