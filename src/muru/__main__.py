"""Entry point for `python -m muru`.

This file gets executed when the user runs `python -m muru` from the
command line. It just delegates to muru.ui.cli.main:main.
"""

from __future__ import annotations

import sys

from muru.ui.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
