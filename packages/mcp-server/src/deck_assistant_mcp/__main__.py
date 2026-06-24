"""Module entrypoint: ``python -m deck_assistant_mcp serve``."""

from __future__ import annotations

import sys

from deck_assistant_mcp.server import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
