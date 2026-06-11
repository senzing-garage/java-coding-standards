"""Focused unit tests for the `_cli` module's exclusion helpers.

The deletion of the old `fix_*.py` scripts removed `test_helpers.py`
(which exercised `_excluded`, `_load_exclude_file`, and the
`BASELINE_EXCLUDES` fixture-protection behavior). Those helpers are
still production code — they're called by `iter_target_files`
which the orchestrator and IDE keybindings invoke on every save.

This file restores direct coverage. The BASELINE_EXCLUDES safety
property — fixtures and `target/` build output are never silently
rewritten by the formatter — is the most important behavior to
keep tested: a regression there would corrupt the fixture corpus
on the next bulk-format run.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import _cli


def test_baseline_excludes_includes_fixtures_and_target() -> None:
    # The fixture path is what gets corrupted if the
    # auto-format hook ever escapes its exclude rule on save —
    # locking the pattern in a test keeps that from regressing.
    assert "**/tooling/scripts/tests/fixtures/**" in _cli.BASELINE_EXCLUDES
    assert "**/target/**" in _cli.BASELINE_EXCLUDES


def test_excluded_matches_fixture_path() -> None:
    fixture = Path(
        "tooling/scripts/tests/fixtures/allman_braces/01/input.java"
    )
    assert _cli._excluded(fixture, list(_cli.BASELINE_EXCLUDES))


def test_excluded_matches_target_path() -> None:
    target = Path("target/classes/Foo.class")
    assert _cli._excluded(target, list(_cli.BASELINE_EXCLUDES))


def test_excluded_passes_through_non_matching_path() -> None:
    src = Path("src/main/java/com/foo/Bar.java")
    assert not _cli._excluded(src, list(_cli.BASELINE_EXCLUDES))


def test_excluded_handles_double_star_prefix_strip() -> None:
    # `**/foo/**` should match `foo/...` even when there's no
    # leading directory; fnmatch alone doesn't, so `_excluded`
    # tries the pattern stripped of its leading `**/`.
    path = Path("foo/bar.java")
    assert _cli._excluded(path, ["**/foo/**"])


def test_excluded_returns_false_when_no_patterns() -> None:
    assert not _cli._excluded(Path("src/Foo.java"), [])


def test_load_exclude_file_skips_blanks_and_comments(
    tmp_path: Path,
) -> None:
    excludes_file = tmp_path / "excludes.txt"
    excludes_file.write_text(
        "# this is a comment\n"
        "\n"
        "**/Generated*.java\n"
        "  # indented comment, also filtered after strip\n"
        "src/legacy/**\n"
        "\n",
        encoding="utf-8",
    )
    patterns = _cli._load_exclude_file(excludes_file)
    # Comment lines (including those with leading whitespace, since
    # the helper strips before testing the `#` prefix) and blank
    # lines are filtered; real patterns survive in source order.
    assert patterns == [
        "**/Generated*.java",
        "src/legacy/**",
    ]


def test_load_exclude_file_returns_empty_for_missing_file(
    tmp_path: Path,
) -> None:
    assert _cli._load_exclude_file(tmp_path / "no-such-file") == []


def test_iter_target_files_honors_baseline_excludes_for_fixtures(
    tmp_path: Path,
) -> None:
    # End-to-end safety check: even when a fixture path is
    # passed explicitly, iter_target_files refuses to yield it.
    # This is the failsafe protecting the fixture corpus from
    # accidental reformatting.
    fixture_root = (
        tmp_path
        / "tooling"
        / "scripts"
        / "tests"
        / "fixtures"
        / "allman_braces"
    )
    fixture_root.mkdir(parents=True)
    fixture = fixture_root / "input.java"
    fixture.write_text("class A {}\n", encoding="utf-8")

    args = argparse.Namespace(
        paths=[fixture],
        src_dirs=[],
        exclude=[],
        exclude_from=None,
    )
    yielded = list(_cli.iter_target_files(args))
    assert yielded == []


def test_iter_target_files_yields_real_source(tmp_path: Path) -> None:
    # The complement: a normal source file under src/main/java is
    # NOT excluded and IS yielded.
    src_root = tmp_path / "src" / "main" / "java" / "com" / "foo"
    src_root.mkdir(parents=True)
    src = src_root / "Bar.java"
    src.write_text("class Bar {}\n", encoding="utf-8")

    args = argparse.Namespace(
        paths=[src],
        src_dirs=[],
        exclude=[],
        exclude_from=None,
    )
    yielded = list(_cli.iter_target_files(args))
    assert yielded == [src]
