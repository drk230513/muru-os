"""Filesystem tools for Muru.

Importing this package auto-registers all filesystem tools with the
default registry. Individual tools can also be imported and used
directly without going through the registry.
"""

from __future__ import annotations

from muru.tools.filesystem.list_directory import list_directory_tool
from muru.tools.registry import registry

# Register every filesystem tool with the default registry.
# When new tools are added, append them here.
_FILESYSTEM_TOOLS = [
    list_directory_tool,
]

for _tool in _FILESYSTEM_TOOLS:
    if _tool.name not in registry.list_names():
        registry.register(_tool)


__all__ = ["list_directory_tool"]
