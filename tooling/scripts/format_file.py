#!/usr/bin/env python3
"""Orchestrator: run JDT formatter then the five Python override scripts
in canonical order against one or more Java files.

The pipeline:

    JDT formatter (general-purpose Java formatting)
        ↓
    fix_allman_braces.py  — Allman brace placement override
    fix_javadoc_reflow.py
    fix_javadoc_inline_tags.py
    fix_javadoc_tags.py
    fix_need_braces.py    — short-circuit if rules

JDT handles the bulk of the standard (indent, line wrap, alignment,
continuation-indent, ternary tiers, operator-on-continuation). The
five Python scripts override the rules JDT can't express in a single
profile (Allman braces for type/method but same-line for control flow),
plus rules our standards add beyond what JDT or checkstyle catch
(no-orphan-words javadoc reflow, short-circuit if collapse, etc.).

Used by:
- VSCode `Format Java file to Senzing standards` task.
- VSCode `emeraldwalk.runonsave` extension (format-on-save).
- Claude Code `PostToolUse` hook (auto-format every Edit/Write).
- CLI / pre-commit / CI.

Same input → same output, regardless of caller.

Exit code: 0 on success, non-zero if any pass failed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_ORDER: tuple[str, ...] = (
    "fix_allman_braces.py",
    "fix_javadoc_reflow.py",
    "fix_javadoc_inline_tags.py",
    "fix_javadoc_tags.py",
    "fix_need_braces.py",
)

# Path to the JDT formatter shim, relative to the standards-repo root.
# format_file.py lives at tooling/scripts/; the JAR + profile sit two
# directories up.
_STANDARDS_ROOT = Path(__file__).resolve().parent.parent.parent
_JDT_JAR = _STANDARDS_ROOT / "tooling" / "jdt-formatter" / "jdt-formatter.jar"
_JDT_PROFILE = _STANDARDS_ROOT / "tooling" / "ide" / "java-formatter.xml"


def _resolve_target_paths(forwarded_args: list[str]) -> list[Path]:
    """Same path resolution the underlying scripts use, but extracted
    here so we can call JDT against the file list directly. Mirrors
    `_cli.iter_target_files` semantics (positional paths + --src-dirs
    fallback + --exclude / --exclude-from filtering).

    Reuses `_cli.build_parser` so the parser definition stays in one
    place — adding a flag in _cli.py picks up here automatically.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _cli

    parser = _cli.build_parser(prog="format_file", description="")
    # Tolerate unknown flags (e.g. --help) so they pass through cleanly
    # to the per-script invocations later.
    args, _ = parser.parse_known_args(forwarded_args)
    return list(_cli.iter_target_files(args))


# Cap on paths-per-JVM-invocation. With paths averaging ~80 chars,
# 500 leaves ~80 KB on the command line — well under the typical
# Linux ARG_MAX (~2 MB) and macOS (~256 KB) limits, with comfortable
# headroom for the env block. Bulk passes against very large
# codebases will run JDT in multiple JVM invocations; each cold
# start is ~1 s amortized over 500 files.
_JDT_BATCH_SIZE = 500


def run_jdt_pass(paths: list[Path]) -> int:
    """Run the Eclipse JDT formatter against `paths`. Returns 0 on
    success or the first non-zero exit code if any batch fails. The
    path list is chunked at `_JDT_BATCH_SIZE` to keep each JVM
    invocation's command line well under typical OS ARG_MAX limits.
    """
    if not paths:
        return 0
    if not _JDT_JAR.is_file():
        print(
            f"ERROR: JDT formatter JAR not found at {_JDT_JAR}",
            file=sys.stderr,
        )
        return 2
    if not _JDT_PROFILE.is_file():
        print(
            f"ERROR: JDT formatter profile not found at {_JDT_PROFILE}",
            file=sys.stderr,
        )
        return 2
    if shutil.which("java") is None:
        print(
            "ERROR: 'java' not found on PATH; required to run the JDT "
            "formatter pass. Install JDK 17+ or remove this script "
            "invocation from your hooks.",
            file=sys.stderr,
        )
        return 2

    first_failure = 0
    for i in range(0, len(paths), _JDT_BATCH_SIZE):
        batch = paths[i:i + _JDT_BATCH_SIZE]
        cmd = [
            "java",
            "-jar",
            str(_JDT_JAR),
            str(_JDT_PROFILE),
            *(str(p) for p in batch),
        ]
        result = subprocess.run(cmd)
        if result.returncode != 0 and first_failure == 0:
            first_failure = result.returncode
    return first_failure


def main() -> int:
    here = Path(__file__).resolve().parent
    forwarded_args = sys.argv[1:]

    # Stage 1: JDT pass against resolved paths.
    # We resolve paths Python-side so JDT only sees real .java files
    # (and so we honor BASELINE_EXCLUDES, --exclude, etc. before
    # invoking the JVM). For pure --help passthrough or non-path args
    # the path list will be empty and the JDT call is a no-op.
    try:
        target_paths = _resolve_target_paths(forwarded_args)
    except SystemExit:
        # argparse may sys.exit on certain inputs; let the underlying
        # script handle whatever the user passed and report.
        target_paths = []

    failures: list[tuple[str, int]] = []
    if target_paths:
        rc = run_jdt_pass(target_paths)
        if rc != 0:
            failures.append(("jdt-formatter", rc))

    # Stage 2: existing Python override scripts in canonical order.
    for script in SCRIPT_ORDER:
        script_path = here / script
        if not script_path.is_file():
            print(
                f"ERROR: missing script {script_path}",
                file=sys.stderr,
            )
            return 2

        cmd = [sys.executable, str(script_path), *forwarded_args]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            failures.append((script, result.returncode))

    if failures:
        print("\nFailures:", file=sys.stderr)
        for name, rc in failures:
            print(f"  {name}: exit {rc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
