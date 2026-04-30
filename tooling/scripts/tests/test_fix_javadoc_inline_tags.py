"""Tests for fix_javadoc_inline_tags.py.

Catches the prose-paragraph-with-inline-tags cases that
fix_javadoc_reflow.py intentionally skips.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import fix_javadoc_inline_tags  # noqa: E402
from conftest import fixture_cases


@pytest.mark.parametrize(
    "case",
    fixture_cases("javadoc_inline_tags"),
    ids=lambda c: c.name,
)
def test_fixture(case: Path, tmp_path: Path) -> None:
    input_text = (case / "input.java").read_text(encoding="utf-8")
    expected_text = (case / "expected.java").read_text(encoding="utf-8")

    target = tmp_path / "Source.java"
    target.write_text(input_text, encoding="utf-8")

    fix_javadoc_inline_tags.process_file(target)

    actual = target.read_text(encoding="utf-8")
    assert actual == expected_text, (
        f"\n--- expected ---\n{expected_text}\n"
        f"--- actual ---\n{actual}\n"
    )
