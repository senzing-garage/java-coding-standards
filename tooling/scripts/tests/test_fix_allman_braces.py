"""Tests for fix_allman_braces.py.

Each fixture under fixtures/allman_braces/ is a directory containing:
- input.java: source the script will be run against
- expected.java: the desired output

The test parametrizes over these directories so adding a new case is
just dropping in a new fixture directory.

The fixture-driven tests exercise the script's full process_file
behavior end-to-end. Direct unit tests for individual helpers
(find_wrap_opener_indent, is_control_flow_or_special, etc.) live in
test_helpers.py.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import fix_allman_braces  # noqa: E402  (path injected by conftest)
from conftest import fixture_cases


@pytest.mark.parametrize(
    "case",
    fixture_cases("allman_braces"),
    ids=lambda c: c.name,
)
def test_fixture(case: Path, tmp_path: Path) -> None:
    """Run process_file on input.java; assert output matches expected.java."""
    input_text = (case / "input.java").read_text(encoding="utf-8")
    expected_text = (case / "expected.java").read_text(encoding="utf-8")

    target = tmp_path / "Source.java"
    target.write_text(input_text, encoding="utf-8")

    fix_allman_braces.process_file(target)

    actual = target.read_text(encoding="utf-8")
    assert actual == expected_text, (
        f"\n--- expected ---\n{expected_text}\n"
        f"--- actual ---\n{actual}\n"
    )


def test_returns_false_when_no_change(tmp_path: Path) -> None:
    """process_file should return False when nothing changes."""
    target = tmp_path / "Source.java"
    target.write_text(
        "public class A\n{\n    public void foo()\n    {\n    }\n}\n",
        encoding="utf-8",
    )
    before = target.read_text(encoding="utf-8")
    result = fix_allman_braces.process_file(target)
    assert result is False
    assert target.read_text(encoding="utf-8") == before


def test_returns_true_when_changed(tmp_path: Path) -> None:
    """process_file should return True when it modifies the file."""
    target = tmp_path / "Source.java"
    target.write_text(
        "public class A {\n    public void foo() {\n    }\n}\n",
        encoding="utf-8",
    )
    result = fix_allman_braces.process_file(target)
    assert result is True


def test_does_not_modify_when_only_control_flow(tmp_path: Path) -> None:
    """Same-line braces on if/for/while/etc must be preserved."""
    src = (
        "public class A\n{\n"
        "    public void foo()\n    {\n"
        "        if (a == b) {\n"
        "            doSomething();\n"
        "        }\n"
        "        for (int i = 0; i < 10; i++) {\n"
        "            doIt();\n"
        "        }\n"
        "        while (cond) {\n"
        "            spin();\n"
        "        }\n"
        "    }\n}\n"
    )
    target = tmp_path / "Source.java"
    target.write_text(src, encoding="utf-8")
    fix_allman_braces.process_file(target)
    assert target.read_text(encoding="utf-8") == src
