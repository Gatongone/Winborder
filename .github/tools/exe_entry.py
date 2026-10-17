"""Entry point for the built executable."""

from __future__ import annotations

import multiprocessing
import sys

from winborder.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
