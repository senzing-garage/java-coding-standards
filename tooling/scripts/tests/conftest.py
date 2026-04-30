"""Shared pytest configuration for the tooling/scripts test suite.

The tests under this directory exercise the bulk-format Python scripts
(`fix_*.py`, `format_file.py`, `_cli.py`) that live one directory up.
The scripts use plain top-level imports (`from _cli import ...`); to
make those importable from inside the tests, we prepend the parent
directory to sys.path.

This file is automatically discovered by pytest (any file named
`conftest.py` is loaded before tests in the same directory or any
sub-directory).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Tests live at tooling/scripts/tests/; scripts at tooling/scripts/.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def fixtures_dir(category: str) -> Path:
    """Return the path to a fixture category (e.g. 'allman_braces')."""
    return Path(__file__).resolve().parent / "fixtures" / category


def fixture_cases(category: str) -> list[Path]:
    """Yield each fixture-case directory under the given category.

    A fixture case is a directory containing `input.java` and
    `expected.java` files. Returned in sorted order so test ids
    are stable across runs. Hidden directories (e.g. `.pytest_cache`
    that pytest may create here) are skipped.
    """
    base = fixtures_dir(category)
    if not base.is_dir():
        return []
    return sorted(
        d for d in base.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )
