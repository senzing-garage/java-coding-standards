"""Tests for fix_javadoc_reflow.py.

Each fixture under fixtures/javadoc_reflow/ exercises a specific
case of plain-prose Javadoc paragraph reflow. The script intentionally
skips paragraphs that begin with inline tags ({@link}, <code>, etc.) —
those are handled by fix_javadoc_inline_tags.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import fix_javadoc_reflow  # noqa: E402  (path injected by conftest)
from conftest import fixture_cases


@pytest.mark.parametrize(
    "case",
    fixture_cases("javadoc_reflow"),
    ids=lambda c: c.name,
)
def test_fixture(case: Path, tmp_path: Path) -> None:
    input_text = (case / "input.java").read_text(encoding="utf-8")
    expected_text = (case / "expected.java").read_text(encoding="utf-8")

    target = tmp_path / "Source.java"
    target.write_text(input_text, encoding="utf-8")

    fix_javadoc_reflow.process_file(target)

    actual = target.read_text(encoding="utf-8")
    assert actual == expected_text, (
        f"\n--- expected ---\n{expected_text}\n"
        f"--- actual ---\n{actual}\n"
    )


def test_returns_false_when_no_change(tmp_path: Path) -> None:
    target = tmp_path / "Source.java"
    target.write_text(
        "/** Single-line javadoc. */\npublic class Foo {}\n",
        encoding="utf-8",
    )
    assert fix_javadoc_reflow.process_file(target) is False
