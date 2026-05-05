"""Tests for fix_throws_alignment.py — post-JDT throws-clause shaper."""

from __future__ import annotations

from pathlib import Path

import pytest

import fix_throws_alignment
from conftest import fixture_cases


@pytest.mark.parametrize(
    "case",
    fixture_cases("throws_alignment"),
    ids=lambda c: c.name,
)
def test_fixture(case: Path, tmp_path: Path) -> None:
    """Run process_file on input.java; assert output matches expected.java."""
    input_text = (case / "input.java").read_text(encoding="utf-8")
    expected_text = (case / "expected.java").read_text(encoding="utf-8")

    target = tmp_path / "Source.java"
    target.write_text(input_text, encoding="utf-8")

    fix_throws_alignment.process_file(target)

    actual = target.read_text(encoding="utf-8")
    assert actual == expected_text, (
        f"\n--- expected ---\n{expected_text}\n"
        f"--- actual ---\n{actual}\n"
    )


def test_returns_tuple(tmp_path: Path) -> None:
    """process_file returns (changed, fixes_count)."""
    target = tmp_path / "Source.java"
    target.write_text(
        "public class Foo\n{\n    void m()\n"
        "        throws AReallyLongExceptionTypeNameOne, "
        "AReallyLongExceptionTypeNameTwo,\n"
        "        AReallyLongExceptionTypeNameThree\n"
        "    {\n    }\n}\n",
        encoding="utf-8",
    )
    result = fix_throws_alignment.process_file(target)
    assert isinstance(result, tuple)
    assert len(result) == 2
    changed, fixes = result
    assert changed is True
    assert fixes == 1
