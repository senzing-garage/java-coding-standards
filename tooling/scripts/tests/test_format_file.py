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
    Tier 6: throws-clause column alignment (post-JDT cleanup; runs
    last so it sees the final layout from earlier passes).
    """
    assert format_file.SCRIPT_ORDER == (
        "fix_allman_braces.py",
        "fix_javadoc_reflow.py",
        "fix_javadoc_inline_tags.py",
        "fix_javadoc_tags.py",
        "fix_need_braces.py",
        "fix_throws_alignment.py",
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


def test_jdt_summary_emits_on_modified_file(tmp_path: Path) -> None:
    """When JDT rewrites the input, the orchestrator must print a
    summary line so the user can see the JDT-stage modification count.

    Without this, an orchestrator run can end with six "modified 0"
    rows from the override scripts even when JDT rewrote dozens of
    files in the same pass — masking the real change set.
    """
    target = tmp_path / "Source.java"
    # Same-line braces; JDT's Allman-for-types config will rewrite
    # this to `public class Foo\n{\n...`.
    target.write_text(
        "public class Foo {\n}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "format_file.py"), str(target)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "JDT pass: 1 files processed, 1 modified." in result.stdout, (
        f"Expected JDT summary line in stdout. Got:\n{result.stdout}"
    )


def test_jdt_summary_zero_modified_on_compliant_file(tmp_path: Path) -> None:
    """Already-compliant input: JDT pass is idempotent, summary should
    report 0 modified — proving the count is real, not a constant.

    The hand-crafted input below depends on JDT being byte-perfect
    idempotent against this exact content. The same content is used
    by `test_exits_zero_on_no_changes` above (with the same byte-
    equality assertion); that test has served as the canonicalization
    canary since 0.2.4. If JDT changes its canonicalization rules,
    that test fails first and pinpoints the underlying issue, and
    this test fails as a downstream consequence.
    """
    target = tmp_path / "Source.java"
    target.write_text(
        "public class Foo\n{\n    public void m()\n    {\n"
        "        if (x == null) return;\n"
        "    }\n}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "format_file.py"), str(target)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "JDT pass: 1 files processed, 0 modified." in result.stdout, (
        f"Expected '0 modified' summary line. Got:\n{result.stdout}"
    )


def test_file_signature_returns_none_for_missing(tmp_path: Path) -> None:
    """`_file_signature` must return None for a missing file rather
    than raising. The modified-count call site relies on
    `None != prior_signature` to count a deleted file as modified
    without a special case.
    """
    nonexistent = tmp_path / "Missing.java"
    assert not nonexistent.exists()
    assert format_file._file_signature(nonexistent) is None


def test_jdt_summary_prints_when_jdt_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """The summary line must still print when the JDT subprocess exits
    non-zero. The modified count up to the failure point is more
    useful than silence, and downstream tooling that greps for
    `JDT pass:` should still see it on a partial-failure run.

    Patches `format_file.run_jdt_pass` to return a non-zero code
    without actually invoking the JDT subprocess; runs `format_file.main`
    in-process; asserts the summary line appears in stdout.
    """
    target = tmp_path / "Source.java"
    target.write_text("public class Foo {\n}\n", encoding="utf-8")

    monkeypatch.setattr(
        format_file, "run_jdt_pass", lambda paths: 1
    )
    # Also stub the override-script subprocess loop so we don't run
    # the rest of the pipeline; we only need to observe the JDT
    # summary line and the main() return value.
    monkeypatch.setattr(
        format_file.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(args=[], returncode=0),
    )
    monkeypatch.setattr(sys, "argv", ["format_file.py", str(target)])

    rc = format_file.main()
    captured = capsys.readouterr()

    # Tight assertion — both the path-count (1) and the modified
    # count (0, since the mocked run_jdt_pass doesn't touch the
    # file) must appear, so a buggy "0 files processed, 0 modified"
    # variant doesn't slip through.
    assert "JDT pass: 1 files processed, 0 modified." in captured.out, (
        f"Summary line must print even when JDT fails. Got:\n{captured.out}"
    )
    assert rc != 0, (
        "main() must propagate the non-zero JDT exit code; "
        f"got {rc}"
    )


def test_jdt_summary_skipped_on_empty_targets(tmp_path: Path) -> None:
    """When the path list resolves to empty (e.g. `--help` passthrough,
    or a forwarded-args block with no real .java paths), the JDT pass
    is skipped — the summary line must NOT print, since no files were
    processed and a `processed 0, modified 0` line would be confusing
    output noise.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "format_file.py"), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "JDT pass:" not in result.stdout, (
        "Summary line must not print when no targets resolved. "
        f"Got:\n{result.stdout}"
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
