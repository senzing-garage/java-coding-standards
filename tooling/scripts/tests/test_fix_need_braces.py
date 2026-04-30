"""Tests for fix_need_braces.py.

Covers the three tiers of brace handling for `if` / `else`:

- Tier 1: standalone short-circuit `if (cond) statement;` collapses
  to one line when it fits.
- Tier 2: standalone `if` with non-short-circuit body always gets
  braces (assignments and method calls don't get the single-line
  form even if they fit).
- Tier 3: `if`/`else` pairs always brace both branches.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import fix_need_braces
from conftest import fixture_cases


@pytest.mark.parametrize(
    "case",
    fixture_cases("need_braces"),
    ids=lambda c: c.name,
)
def test_fixture(case: Path, tmp_path: Path) -> None:
    """Run process_file on input.java; assert output matches expected.java."""
    input_text = (case / "input.java").read_text(encoding="utf-8")
    expected_text = (case / "expected.java").read_text(encoding="utf-8")

    target = tmp_path / "Source.java"
    target.write_text(input_text, encoding="utf-8")

    fix_need_braces.process_file(target)

    actual = target.read_text(encoding="utf-8")
    assert actual == expected_text, (
        f"\n--- expected ---\n{expected_text}\n"
        f"--- actual ---\n{actual}\n"
    )


def test_returns_tuple(tmp_path: Path) -> None:
    """process_file in fix_need_braces returns (changed, fixes_count)."""
    target = tmp_path / "Source.java"
    target.write_text(
        "public class Foo\n{\n    public void m()\n    {\n"
        "        if (x == null)\n            return;\n"
        "    }\n}\n",
        encoding="utf-8",
    )
    result = fix_need_braces.process_file(target)
    assert isinstance(result, tuple)
    assert len(result) == 2
    changed, fixes = result
    assert changed is True
    assert fixes >= 1
