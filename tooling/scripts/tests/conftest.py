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

import os
import sys
from pathlib import Path

# Tests live at tooling/scripts/tests/; scripts at tooling/scripts/.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def resolve_java_corpus() -> Path | None:
    """Locate a Java corpus to fuzz / perf-gate against.

    Precedence:
        1. `SENZING_JAVA_FUZZ_CORPUS` env var (must exist and
           point at a directory).
        2. `<consumer>/src/` — the consumer project's source
           tree, used by default during development.

    The submodule lives at `<consumer>/.java-coding-standards/`;
    this `conftest.py` is at
    `<consumer>/.java-coding-standards/tooling/scripts/tests/`,
    so `parents[4]` is the consumer root.

    Returns `None` when no corpus can be located — callers
    `pytest.skip` cleanly so a stripped-down checkout doesn't
    fail CI.
    """
    env = os.environ.get("SENZING_JAVA_FUZZ_CORPUS")
    if env:
        p = Path(env)
        return p if p.is_dir() else None
    consumer_root = Path(__file__).resolve().parents[4]
    src = consumer_root / "src"
    return src if src.is_dir() else None


def fixtures_dir(category: str) -> Path:
    """Return the path to a fixture category (e.g. 'allman_braces')."""
    return Path(__file__).resolve().parent / "fixtures" / category


def fixture_cases(category: str) -> list[Path]:
    """Return each fixture-case directory under the given category.

    A fixture case is a directory containing `input.java` and
    `expected.java` files. Sorted so test ids are stable across runs.
    Hidden directories (e.g. `.pytest_cache` that pytest may create
    here) are skipped.
    """
    base = fixtures_dir(category)
    if not base.is_dir():
        return []
    return sorted(
        d for d in base.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )
