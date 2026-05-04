"""CLI entry point for Muru.

This module exists so pyproject.toml's [project.scripts] entry point
('muru = muru.ui.cli.main:main') has a clean function to call.

When the user runs:
    muru          (after pip install)
    python -m muru
both paths converge here.
"""

from __future__ import annotations

import sys


def main() -> int:
    """Run Muru's CLI. Returns the process exit code."""
    from muru.ui.cli.repl import main_repl_loop

    return main_repl_loop()


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["main"]
