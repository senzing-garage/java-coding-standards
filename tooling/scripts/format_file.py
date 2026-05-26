#!/usr/bin/env python3
"""Format Java files using the canonical AST-based formatter.

For every target file resolved from the command-line arguments
(positional paths + `--src-dirs` fallback + `--exclude` /
`--exclude-from` filtering, all delegated to `_cli`), this script
invokes `format_java.format_source()` on the file's bytes and
writes the formatted output back when it differs from the
original.

This is the end-user formatter entry point. Used by:

- VSCode `Format Java file to Senzing standards` task.
- VSCode `emeraldwalk.runonsave` extension (format-on-save).
- Claude Code `PostToolUse` hook (auto-format every Edit/Write).
- CLI / pre-commit / CI.

The 0.3.0 release replaced the previous JDT-plus-six-script
pipeline (`fix_allman_braces.py`, `fix_javadoc_reflow.py`,
`fix_javadoc_inline_tags.py`, `fix_javadoc_tags.py`,
`fix_need_braces.py`, `fix_throws_alignment.py`, and the
Eclipse JDT formatter shim under `tooling/jdt-formatter/`)
with a single in-process tree-sitter-based formatter at
`format_java.py`. Same input → same output, regardless of
caller.

Mtime preservation: when the formatter's output is bit-
identical to the input, the original `mtime` is restored.
This keeps IDE reloads, Maven/Gradle build caches, and `make`
timestamp tracking quiet on idempotent runs — important
because every save invokes the formatter via the file-watcher
or `PostToolUse` hook.

Exit code: 0 on success (all files processed cleanly,
regardless of whether any were modified), non-zero on errors.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path


def _sha256(path: Path) -> str:
    """Stream the file through SHA-256 so very large sources don't
    pin the whole content in memory just for the snapshot.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_snapshot(
    path: Path,
) -> tuple[int, str, int, int] | None:
    """Return `(size, sha256-hex, atime_ns, mtime_ns)` for `path`,
    or `None` if missing. Used to decide whether to restore mtime
    after the formatter runs.
    """
    try:
        st = path.stat()
        return (
            st.st_size,
            _sha256(path),
            st.st_atime_ns,
            st.st_mtime_ns,
        )
    except FileNotFoundError:
        return None


def _restore_mtime(
    path: Path, atime_ns: int, mtime_ns: int
) -> None:
    """Best-effort restore of `path`'s atime + mtime to the saved
    values. Warns on `OSError` and continues; the mtime restore
    is cosmetic (IDE / build-cache hygiene) and must never fail
    the run.
    """
    try:
        os.utime(path, ns=(atime_ns, mtime_ns))
    except OSError as exc:
        print(
            f"WARNING: could not restore mtime on {path}: {exc}",
            file=sys.stderr,
        )


def _format_one(
    path: Path,
    format_source,
) -> str:
    """Format `path` in place. Returns one of:

        - `"unchanged"` — output equals input; mtime restored.
        - `"changed"` — output differs; written; mtime advanced.
        - `"refused"` — formatter raised NotImplementedError (the
          file has a construct the current emitter doesn't
          support).
        - `"parse-error"` — input contains a syntax error.
        - `"error"` — unexpected internal exception (formatter
          bug).

    Diagnostics are printed to stderr; the return value lets the
    caller aggregate counts.
    """
    pre = _file_snapshot(path)
    if pre is None:
        print(f"ERROR: no such file: {path}", file=sys.stderr)
        return "error"
    try:
        source = path.read_bytes()
    except OSError as exc:
        print(
            f"ERROR: could not read {path}: {exc}",
            file=sys.stderr,
        )
        return "error"
    try:
        formatted = format_source(source)
    except NotImplementedError as exc:
        print(
            f"REFUSED: {path}: {exc}",
            file=sys.stderr,
        )
        return "refused"
    except ValueError as exc:
        print(
            f"PARSE ERROR: {path}: {exc}",
            file=sys.stderr,
        )
        return "parse-error"
    except Exception as exc:  # noqa: BLE001
        print(
            f"ERROR: {path}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return "error"
    if formatted == source:
        # Bit-identical; restore mtime for IDE / build-cache
        # hygiene.
        _restore_mtime(path, pre[2], pre[3])
        return "unchanged"
    try:
        path.write_bytes(formatted)
    except OSError as exc:
        print(
            f"ERROR: could not write {path}: {exc}",
            file=sys.stderr,
        )
        return "error"
    return "changed"


def _resolve_target_paths(
    forwarded_args: list[str],
) -> list[Path]:
    """Path resolution via `_cli`. Mirrors the underlying
    formatter's CLI surface so positional paths, `--src-dirs`,
    `--exclude`, and `--exclude-from` all behave the same way the
    user expects.
    """
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import _cli  # type: ignore[import-not-found]

    parser = _cli.build_parser(
        prog="format_file", description=""
    )
    args, _ = parser.parse_known_args(forwarded_args)
    return list(_cli.iter_target_files(args))


def main() -> int:
    forwarded_args = sys.argv[1:]

    # Import the formatter once up front so import-time errors
    # surface BEFORE we start trying to format files.
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        from format_java import format_source  # type: ignore[import-not-found]
    except ImportError as exc:
        print(
            f"ERROR: could not import format_java: {exc}\n"
            "Install the formatter's runtime dependencies with:\n"
            "    pip install -r tooling/scripts/requirements.txt",
            file=sys.stderr,
        )
        return 2

    try:
        target_paths = _resolve_target_paths(forwarded_args)
    except SystemExit as exc:
        # argparse exits with 0 on `--help`; treat as clean
        # passthrough (the help text has already been printed).
        if exc.code in (0, None):
            return 0
        return int(exc.code) if isinstance(exc.code, int) else 2

    if not target_paths:
        # No targets resolved. Match the prior pipeline's
        # behavior: silent success (handy for `--help` and
        # selective `--exclude` runs that filter out every
        # candidate).
        return 0

    counts = {
        "unchanged": 0,
        "changed": 0,
        "refused": 0,
        "parse-error": 0,
        "error": 0,
    }
    for path in target_paths:
        outcome = _format_one(path, format_source)
        counts[outcome] += 1

    total = sum(counts.values())
    modified = counts["changed"]
    print(
        f"\nFormatter: {total} files processed, "
        f"{modified} modified."
    )
    refused = counts["refused"]
    parse_errs = counts["parse-error"]
    errors = counts["error"]
    if refused or parse_errs or errors:
        print(
            f"  refused: {refused}, "
            f"parse errors: {parse_errs}, "
            f"other errors: {errors}",
            file=sys.stderr,
        )
        # Refusals are not failures (the formatter cleanly
        # declines a construct it doesn't support yet); parse
        # errors and other errors ARE failures.
        if parse_errs or errors:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
