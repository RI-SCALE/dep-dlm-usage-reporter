"""Composition root and CLI entry point."""

from __future__ import annotations

import sys


def main() -> int:
    """Run one reporting cycle. Exit codes: 0 ok, 1 config, 2 warnings, 3 failed, 4 aborted."""
    print("usage-reporter: not implemented yet", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
