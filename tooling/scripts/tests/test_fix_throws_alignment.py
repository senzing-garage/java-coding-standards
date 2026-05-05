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


def test_preserves_no_trailing_newline(tmp_path: Path) -> None:
    """A file that does not end with a newline must not gain one when
    the script rewrites a throws clause inside it.

    `_emit_clause` always appends exactly one `\\n` to its output;
    `process_file` must strip that trailing newline back off when the
    original block did not have one, so the script remains a no-op
    on EOF state. Realistically only matters for torn-mid-write or
    deliberately-newline-stripped inputs, but documenting the
    invariant here protects against accidental regression.
    """
    target = tmp_path / "Source.java"
    # Throws clause is the last thing in the file; the very last
    # character is `e` of `Three` — no trailing newline. The
    # multi-line throws should still get re-shaped, but the file
    # must end without a newline as it started.
    content = (
        "public class Foo\n{\n    void m()\n"
        "        throws AReallyLongExceptionTypeNameOne, "
        "AReallyLongExceptionTypeNameTwo,\n"
        "        AReallyLongExceptionTypeNameThree"
    )
    target.write_text(content, encoding="utf-8")
    fix_throws_alignment.process_file(target)
    actual = target.read_text(encoding="utf-8")
    assert not actual.endswith("\n"), (
        "process_file must preserve absence of trailing newline. "
        f"Got: {actual!r}"
    )
    # Also confirm the rewrite still happened — the three exceptions
    # should now be column-aligned (one per line) in the output.
    assert "        throws AReallyLongExceptionTypeNameOne,\n" in actual
    assert "               AReallyLongExceptionTypeNameTwo,\n" in actual
    assert actual.endswith("AReallyLongExceptionTypeNameThree")
