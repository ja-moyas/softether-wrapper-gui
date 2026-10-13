"""Entry point for ``python -m softether_wrapper`` and the console script."""

from __future__ import annotations

import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main())
