"""Shared CLI parsing + file iteration for the bulk-format scripts.

Each `fix_*.py` script imports `parse_args` and `iter_target_files` from
this module so the five scripts share a single, consistent CLI surface.

Default behavior (no args): walk `src/main/java`, `src/test/java`, and
`src/demo/java` if they exist, processing every `*.java` file. With
positional path arguments: process exactly those files (single-file mode,
used by the `format_file.py` orchestrator and by VSCode keybindings).

Exclude globs are gitignore-style and matched against the full posix-form
path of each candidate file, so patterns like `**/GeneratedFoo.java`
or `target/**` work as expected.

Used by: fix_allman_braces.py, fix_javadoc_reflow.py,
fix_javadoc_inline_tags.py, fix_javadoc_tags.py, fix_need_braces.py,
format_file.py.
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path
from typing import Iterator

DEFAULT_SRC_DIRS: tuple[str, ...] = (
    "src/main/java",
    "src/test/java",
    "src/demo/java",
)

# Always-applied excludes. Fixtures must stay deliberately
# non-compliant; auto-format hooks running format_file.py would
# corrupt them otherwise. target/** is build output.
BASELINE_EXCLUDES: tuple[str, ...] = (
    "**/tooling/scripts/tests/fixtures/**",
    "**/target/**",
)


def build_parser(prog: str, description: str) -> argparse.ArgumentParser:
    """Build the standard argument parser shared across all bulk scripts.

    The `fix_*.py` scripts call `parse_args()`, which delegates here.
    The orchestrator calls this directly so it can use
    `parse_known_args()` (to tolerate flags meant for the underlying
    scripts) without duplicating the argument definitions here.
    """
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help=(
            "specific .java files (or directories) to process. When given, "
            "--src-dirs is ignored. Used by the orchestrator and "
            "VSCode keybindings for single-file reformatting."
        ),
    )
    parser.add_argument(
        "--src-dirs",
        nargs="+",
        default=list(DEFAULT_SRC_DIRS),
        metavar="DIR",
        help=(
            "directories to recursively scan for .java files when no "
            "positional paths are given. Default: %(default)s "
            "(directories that don't exist are silently skipped)."
        ),
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help=(
            "skip files matching this gitignore-style glob; repeatable. "
            "Patterns are matched against the posix-form path of each "
            "candidate file (e.g. '**/Generated*.java', 'target/**')."
        ),
    )
    parser.add_argument(
        "--exclude-from",
        type=Path,
        default=None,
        metavar="FILE",
        help=(
            "read additional --exclude patterns from this file, one per "
            "line. Lines starting with '#' and blank lines are ignored. "
            "Used to consume the project-local "
            ".java-coding-standards-excludes file."
        ),
    )
    return parser


def parse_args(prog: str, description: str) -> argparse.Namespace:
    """Build the parser and parse sys.argv. Wrapper around build_parser()
    for the fix_*.py scripts."""
    return build_parser(prog, description).parse_args()


def _excluded(path: Path, patterns: list[str]) -> bool:
    """Approximates gitignore semantics: leading `**/` is also tried
    stripped, so `**/foo/**` matches `foo/...` (which fnmatch alone
    rejects). Middle-`**` (e.g. `foo/**/bar`) is not special-cased —
    switch to `pathspec` if that becomes needed.
    """
    posix = path.as_posix()
    for pat in patterns:
        if fnmatch.fnmatch(posix, pat):
            return True
        if pat.startswith("**/") and fnmatch.fnmatch(posix, pat[3:]):
            return True
    return False


def _load_exclude_file(path: Path) -> list[str]:
    if not path.is_file():
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def iter_target_files(args: argparse.Namespace) -> Iterator[Path]:
    """Yield Java files to process, applying exclusion rules.

    The BASELINE_EXCLUDES patterns are always applied first so test
    fixtures and build outputs are never silently rewritten.
    Caller-supplied --exclude / --exclude-from patterns layer on top.
    """
    excludes = list(BASELINE_EXCLUDES)
    excludes.extend(args.exclude)
    if args.exclude_from is not None:
        excludes.extend(_load_exclude_file(args.exclude_from))

    if args.paths:
        # Single-file (or explicit-list) mode: process exactly what was
        # passed, but still honor excludes so the orchestrator and IDE
        # callers can't accidentally reformat a generated file.
        for p in args.paths:
            if p.is_file() and p.suffix == ".java":
                if not _excluded(p, excludes):
                    yield p
            elif p.is_dir():
                for jf in sorted(p.rglob("*.java")):
                    if not _excluded(jf, excludes):
                        yield jf
            else:
                print(
                    f"WARNING: skipping non-existent or non-Java path: {p}",
                    file=sys.stderr,
                )
        return

    # Default mode: walk the configured src dirs.
    src_dirs = [Path(d) for d in args.src_dirs]
    found = [d for d in src_dirs if d.is_dir()]
    if not found:
        print(
            "ERROR: No src dirs found. Run from project root, "
            "or pass --src-dirs / positional paths.",
            file=sys.stderr,
        )
        sys.exit(1)
    for d in found:
        for jf in sorted(d.rglob("*.java")):
            if not _excluded(jf, excludes):
                yield jf
