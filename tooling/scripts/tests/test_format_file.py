"""Tests for the new format_file.py — the single-file orchestrator
that delegates to format_java.format_source() and rewrites each
target file in place.

The previous JDT-plus-six-script pipeline tested separate
behaviors (canonical script order, JDT failure handling, batch
sizing). After the 0.3.0 atomic switch, those behaviors are gone;
the orchestrator's contract is now:

- Resolve target paths via `_cli.iter_target_files`.
- For each path: read, format, write-back when changed, restore
  mtime when unchanged.
- Exit 0 on success (regardless of how many files were modified)
  or on refusals (formatter declined the construct); exit 1 on
  parse errors or unexpected internal exceptions.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import format_file


SCRIPTS_DIR = Path(__file__).resolve().parent.parent


def _run_format_file(*args: str) -> subprocess.CompletedProcess:
    """Invoke format_file.py as a subprocess so we exercise the
    full `main()` path including argparse + import resolution.
    """
    cmd = [sys.executable, str(SCRIPTS_DIR / "format_file.py"), *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_unchanged_file_preserves_mtime(tmp_path: Path) -> None:
    # A file already in spec-compliant form is detected as
    # unchanged and gets its mtime preserved.
    java = tmp_path / "Foo.java"
    java.write_text(
        "package com.foo;\n\n"
        "public class Foo\n"
        "{\n"
        "    int x = 1;\n"
        "}\n"
    )
    # Set a known mtime in the past so we can check restoration.
    past = time.time() - 3600
    os.utime(java, (past, past))
    before = java.stat().st_mtime_ns

    result = _run_format_file(str(java))
    assert result.returncode == 0, result.stderr

    after = java.stat().st_mtime_ns
    # Same mtime when content didn't change.
    assert after == before
    # Summary line on stdout.
    assert "0 modified" in result.stdout


def test_changed_file_rewritten(tmp_path: Path) -> None:
    # A file that needs reformatting is rewritten in place.
    java = tmp_path / "Foo.java"
    # Source has same-line `{` after class header; formatter
    # rewrites to Allman.
    java.write_text(
        "package com.foo;\n\n"
        "public class Foo {\n"
        "    int x = 1;\n"
        "}\n"
    )

    result = _run_format_file(str(java))
    assert result.returncode == 0, result.stderr

    after = java.read_text()
    assert "public class Foo\n{\n" in after
    assert "1 modified" in result.stdout


def test_refused_file_exits_zero(tmp_path: Path) -> None:
    # A file containing a construct the formatter doesn't yet
    # support (e.g. a module declaration) prints REFUSED on
    # stderr but exits 0 — refusal is not a pipeline failure.
    java = tmp_path / "module-info.java"
    java.write_text(
        "module com.foo {\n"
        "    requires java.base;\n"
        "}\n"
    )

    result = _run_format_file(str(java))
    assert result.returncode == 0, result.stderr
    assert "REFUSED" in result.stderr
    assert "refused: 1" in result.stderr


def test_parse_error_exits_nonzero(tmp_path: Path) -> None:
    # Genuine Java syntax errors fail the run (exit 1) so CI
    # surfaces them rather than silently overwriting source.
    java = tmp_path / "Broken.java"
    java.write_text("public class Broken { ; ; ; nope")

    result = _run_format_file(str(java))
    assert result.returncode == 1


def test_multiple_files_aggregated(tmp_path: Path) -> None:
    # Run against multiple files; check the summary count.
    for i in range(3):
        (tmp_path / f"F{i}.java").write_text(
            f"package com.foo;\n\n"
            f"public class F{i}\n"
            f"{{\n"
            f"    int x = {i};\n"
            f"}}\n"
        )

    result = _run_format_file(str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert "3 files processed" in result.stdout
    assert "0 modified" in result.stdout


def test_help_flag_exits_zero(tmp_path: Path) -> None:
    # `--help` should print help text and exit 0 without
    # processing any files.
    result = _run_format_file("--help")
    assert result.returncode == 0


def test_file_snapshot_returns_none_for_missing(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "does-not-exist.java"
    assert format_file._file_snapshot(missing) is None


def test_restore_mtime_warns_on_oserror(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # When os.utime fails (e.g. read-only fs), the helper warns
    # but doesn't crash.
    java = tmp_path / "Foo.java"
    java.write_text("class A {}\n")

    def boom(*args: object, **kwargs: object) -> None:
        raise PermissionError("read-only")

    monkeypatch.setattr(os, "utime", boom)
    format_file._restore_mtime(java, 0, 0)
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "could not restore mtime" in err


def test_format_one_changed(tmp_path: Path) -> None:
    # Unit-test the helper directly for the CHANGED path.
    sys.path.insert(0, str(SCRIPTS_DIR))
    from format_java import format_source  # type: ignore

    java = tmp_path / "Foo.java"
    java.write_text(
        "public class Foo {\n"
        "    int x = 1;\n"
        "}\n"
    )
    outcome = format_file._format_one(java, format_source)
    assert outcome == "changed"
    after = java.read_text()
    assert "public class Foo\n{\n" in after


def test_format_one_unchanged_restores_mtime(
    tmp_path: Path,
) -> None:
    sys.path.insert(0, str(SCRIPTS_DIR))
    from format_java import format_source  # type: ignore

    java = tmp_path / "Foo.java"
    java.write_text(
        "public class Foo\n"
        "{\n"
        "    int x = 1;\n"
        "}\n"
    )
    past = time.time() - 7200
    os.utime(java, (past, past))
    before = java.stat().st_mtime_ns

    outcome = format_file._format_one(java, format_source)
    assert outcome == "unchanged"
    after = java.stat().st_mtime_ns
    assert after == before
