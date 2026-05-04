"""Smoke tests for the muru package.

These tests verify that the package and its main subpackages can be
imported. If any of these fail, something is fundamentally broken
with the project setup.
"""

import importlib


def test_can_import_muru() -> None:
    """The top-level muru package must be importable."""
    import muru

    assert muru is not None


def test_all_subpackages_importable() -> None:
    """Every subpackage in the planned architecture must be importable.

    This catches missing __init__.py files and broken package structure.
    """
    subpackages = [
        "muru.core",
        "muru.llm",
        "muru.planner",
        "muru.tools",
        "muru.tools.filesystem",
        "muru.tools.shell",
        "muru.tools.web",
        "muru.tools.apps",
        "muru.policy",
        "muru.policy.confirmation",
        "muru.policy.risk",
        "muru.policy.audit",
        "muru.memory",
        "muru.ui",
        "muru.ui.cli",
        "muru.utils",
    ]

    for name in subpackages:
        module = importlib.import_module(name)
        assert module is not None, f"Failed to import {name}"


def test_python_version() -> None:
    """Muru requires Python 3.11+."""
    import sys

    assert sys.version_info >= (3, 11), (
        f"Python 3.11+ required, got {sys.version_info}"
    )
