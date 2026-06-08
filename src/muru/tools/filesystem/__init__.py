"""Filesystem tools for Muru.

Importing this package auto-registers all filesystem tools with the
default registry.
"""

from __future__ import annotations

from typing import Any

from muru.tools.base import Tool
from muru.tools.filesystem.get_file_info import get_file_info_tool
from muru.tools.filesystem.list_directory import list_directory_tool
from muru.tools.filesystem.read_file import read_file_tool
from muru.tools.filesystem.search_files import search_files_tool
from muru.tools.filesystem.write_file import write_file_tool
from muru.tools.registry import registry

# Register every filesystem tool with the default registry.
# When new tools are added, append them here.
_FILESYSTEM_TOOLS: list[Tool[Any, Any]] = [
    list_directory_tool,
    read_file_tool,
    get_file_info_tool,
    search_files_tool,
    write_file_tool,
]

for _tool in _FILESYSTEM_TOOLS:
    if _tool.name not in registry.list_names():
        registry.register(_tool)


__all__ = [
    "get_file_info_tool",
    "list_directory_tool",
    "read_file_tool",
    "search_files_tool",
    "write_file_tool",
]
