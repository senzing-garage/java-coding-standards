"""Tests for format_file.py — the orchestrator."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import format_file


SCRIPTS_DIR = Path(__file__).resolve().parent.parent


def test_canonical_script_order() -> None:
    """The orchestrator must invoke scripts in canonical Tier order.

    Tier 1: Allman braces (structural).
    Tier 2-4: javadoc reflow (prose).
    Tier 5: short-circuit / brace insertion (depends on prior reflow).
    """
    assert format_file.SCRIPT_ORDER == (
        "fix_allman_braces.py",
        "fix_javadoc_reflow.py",
        "fix_javadoc_inline_tags.py",
        "fix_javadoc_tags.py",
        "fix_need_braces.py",
    )


def test_runs_all_scripts_against_single_file(tmp_path: Path) -> None:
    """Single-file mode: orchestrator forwards path to each script."""
    target = tmp_path / "Source.java"
    # Same-line braces, a collapsible short-circuit if, and a javadoc
    # paragraph with an orphan continuation that should reflow.
    target.write_text(
        "/**\n"
        " * The number of milliseconds to sleep between checks on the\n"
        " * locks required for\n"
        " * tasks that have been postponed.\n"
        " */\n"
        "public class Foo {\n"
        "    public void m() {\n"
        "        if (x == null)\n"
        "            return;\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "format_file.py"), str(target)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    output = target.read_text(encoding="utf-8")
    # All three transformations should have been applied:
    # 1. Allman split for class + method
    # 2. javadoc reflow merged orphan continuation
    # 3. short-circuit if collapsed to one line
    assert "public class Foo\n{" in output
    assert "public void m()\n    {" in output
    assert "if (x == null) return;" in output
    # Reflow merged the three short prose lines into two:
    assert "checks on the locks required" in output


def test_exits_zero_on_no_changes(tmp_path: Path) -> None:
    """Already-compliant file: orchestrator exits 0 with no modifications."""
    target = tmp_path / "Source.java"
    target.write_text(
        "public class Foo\n{\n    public void m()\n    {\n"
        "        if (x == null) return;\n"
        "    }\n}\n",
        encoding="utf-8",
    )
    before = target.read_text(encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "format_file.py"), str(target)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert target.read_text(encoding="utf-8") == before


def test_forwards_flags_to_every_script(tmp_path: Path) -> None:
    """`--help` is forwarded to every sub-script.

    Each sub-script's argparse handles `--help` by printing its usage
    and calling sys.exit(0). Because format_file.py runs each script
    as a separate subprocess (not via direct import), a SystemExit in
    one script does not terminate the orchestrator — it sees only the
    subprocess's exit code, which is 0, and continues to the next.
    The combined stdout therefore contains usage output from ALL five
    scripts, not just the first.

    If format_file.py is ever refactored to use direct imports, this
    test correctly catches the regression: the first script's
    sys.exit(0) would terminate the orchestrator, and subsequent
    scripts' usage strings would be missing from stdout.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "format_file.py"), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    # Each script's prog= is its filename minus extension; verify all
    # five appear in the combined help output.
    for script in format_file.SCRIPT_ORDER:
        prog = script.removesuffix(".py")
        assert prog in result.stdout, (
            f"Expected '{prog}' usage in help output but it was missing. "
            f"This usually means format_file.py stopped before reaching "
            f"all five scripts.\nstdout:\n{result.stdout}"
        )


def test_baseline_excludes_protect_fixtures(tmp_path: Path) -> None:
    """The baseline excludes protect fixtures from being processed even
    when an explicit path is passed. (Required for the PostToolUse hook
    not to silently corrupt fixture inputs.)"""
    fixture_like = (
        tmp_path / "tooling" / "scripts" / "tests" / "fixtures" / "x"
    )
    fixture_like.mkdir(parents=True)
    target = fixture_like / "input.java"
    # A non-compliant input — script would normally rewrite this.
    deliberately_buggy = "public class Foo {\n}\n"
    target.write_text(deliberately_buggy, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "format_file.py"), str(target)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    # File must be untouched — baseline excludes skipped it.
    assert target.read_text(encoding="utf-8") == deliberately_buggy
