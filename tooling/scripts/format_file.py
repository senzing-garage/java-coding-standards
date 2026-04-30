#!/usr/bin/env python3
"""Orchestrator: run all five bulk-format scripts against a single file (or
a small set of files) in canonical order.

Used by:
- VSCode `Format Java file to Senzing standards` task (single-file reformat
  on a keybinding).
- Claude Code `PostToolUse` hook (auto-format every Edit/Write/MultiEdit).
- `emeraldwalk.runonsave` extension (format-on-save).

Each underlying script supports the same `--src-dirs` / `--exclude` /
positional-paths CLI surface (see `_cli.py`). This orchestrator forwards
positional paths and exclusion args; if no paths are passed, each script
falls back to its bulk-pass default (walk src/main/java, src/test/java,
src/demo/java) — i.e. running `format_file.py` with no args is equivalent
to running each fix_*.py with no args, in order.

Exit code: 0 on success, non-zero if any underlying script failed.
"""

from __future__ import annotations

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


def main() -> int:
    here = Path(__file__).resolve().parent
    forwarded_args = sys.argv[1:]

    failures: list[tuple[str, int]] = []
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
