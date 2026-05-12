"""Canonical Java formatter for the senzing-garage standards.

This module is the AST-based replacement for the JDT+six-script
pipeline that shipped through 0.2.x. It parses each Java source file
to a tree-sitter-java CST and (eventually) emits spec-compliant text
directly per the rules in `docs/java-coding-standards.md`.

Status (Phase 2a — scaffolding only):
    - tree-sitter-java is loaded and a Parser is wired up.
    - File parsing works and the resulting tree can be inspected.
    - Emission logic is NOT yet implemented. Calls to
      `format_source()` raise `NotImplementedError`. The end-user
      entry point `format_file.py` still routes through the
      legacy JDT-plus-six-script pipeline; this module will be
      activated and the legacy pipeline removed atomically in a
      later phase.

The grammar and Python-binding versions are pinned in
`tooling/scripts/requirements.txt`; `GRAMMAR_VERSION` below records
the same pins as in-source constants for runtime validation and
diagnostics.

"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Final

import tree_sitter_java
from tree_sitter import Language, Parser, Tree


__version__: Final[str] = "0.3.0-dev"

# Tree-sitter Python binding + tree-sitter-java grammar versions
# this formatter is calibrated against. Kept in sync with the pins
# in tooling/scripts/requirements.txt. Bumping requires a
# calibration-gate re-run; the emitter dispatches on grammar node
# names that can drift between grammar releases.
GRAMMAR_VERSION: Final[dict[str, str]] = {
    "tree-sitter": "0.25.2",
    "tree-sitter-java": "0.23.5",
}


def _load_java_language() -> Language:
    """Build a tree-sitter `Language` for Java.

    The `tree_sitter_java.language()` entry point returns the raw
    grammar pointer; wrapping it in `Language` is what the
    `Parser.language` setter expects.
    """
    return Language(tree_sitter_java.language())


# Module-level singletons. The Parser is reusable across files;
# constructing it is cheap but happens once at import time so
# downstream code can call `parse_source` without setup ceremony.
# Note: tree_sitter.Parser is NOT documented as safe to share
# across threads — today's tests run in-process and sequentially,
# which is fine. When emitter tests start using pytest-xdist or
# any parallel scheme, either construct the parser per-thread or
# guard this singleton.
JAVA_LANGUAGE: Final[Language] = _load_java_language()
_PARSER: Final[Parser] = Parser(JAVA_LANGUAGE)


def parse_source(source: bytes | bytearray) -> Tree:
    """Parse a Java source byte string and return the tree-sitter Tree.

    Input must be `bytes` or `bytearray` — tree-sitter parses on a
    raw byte buffer. To parse from a Python `str`, encode it first
    via `source.encode("utf-8")`.
    """
    if not isinstance(source, (bytes, bytearray)):
        raise TypeError(
            "parse_source() requires bytes; got "
            f"{type(source).__name__}. Encode strings via "
            "`source.encode('utf-8')` before calling."
        )
    # tree-sitter accepts both bytes and bytearray, so pass through
    # the original buffer rather than copying.
    return _PARSER.parse(source)


def parse_file(path: Path) -> Tree:
    """Parse a Java source file from disk and return the Tree."""
    return parse_source(path.read_bytes())


def has_parse_errors(tree: Tree) -> bool:
    """Return True if the parse tree contains ERROR nodes.

    Used by the formatter to refuse to emit output for syntactically
    invalid input; emitting against an ERROR tree could produce
    garbled output that silently overwrites the file. Note that
    tree-sitter also represents some recovery situations via
    `is_missing` nodes that may not flip `has_error`; when the
    emitter lands, this check should likely expand to also reject
    trees with MISSING descendants.
    """
    return tree.root_node.has_error


def format_source(source: bytes) -> bytes:
    """Format a Java source byte string per the project standards.

    Not yet implemented. Construction of the per-node emitters is
    incremental — see the project plan. Until those land,
    `format_file.py` continues to route through the legacy
    JDT-plus-six-script pipeline.
    """
    raise NotImplementedError(
        "format_source() is not yet implemented. Phase 2a is "
        "scaffolding only; emitter dispatch lands in subsequent "
        "phases."
    )


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="format_java.py",
        description=(
            "Canonical AST-based Java formatter for the "
            "senzing-garage standards (Phase 2a — scaffolding)."
        ),
    )
    parser.add_argument(
        "--check-grammar",
        action="store_true",
        help=(
            "Verify the tree-sitter-java grammar loads and parses a "
            "trivial Java input. Exits 0 on success, non-zero if "
            "the grammar can't be loaded or the trivial parse fails."
        ),
    )
    parser.add_argument(
        "--parse",
        metavar="FILE",
        type=Path,
        help=(
            "Parse FILE and print a one-line diagnostic. Useful "
            "for sanity-checking that the formatter's parser can "
            "load a given source file."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=(
            f"format_java {__version__} "
            f"(tree-sitter {GRAMMAR_VERSION['tree-sitter']}, "
            f"tree-sitter-java {GRAMMAR_VERSION['tree-sitter-java']})"
        ),
    )
    args = parser.parse_args(argv)

    if args.check_grammar:
        sample = b"public class _GrammarCheck {}\n"
        tree = parse_source(sample)
        if has_parse_errors(tree):
            print(
                "format_java.py: ERROR: trivial parse produced an "
                "ERROR node — grammar load is broken.",
                file=sys.stderr,
            )
            return 2
        print(
            "format_java.py: grammar OK "
            f"(tree-sitter {GRAMMAR_VERSION['tree-sitter']}, "
            f"tree-sitter-java {GRAMMAR_VERSION['tree-sitter-java']})"
        )
        return 0

    if args.parse is not None:
        path: Path = args.parse
        if not path.is_file():
            print(
                f"format_java.py: ERROR: no such file: {path}",
                file=sys.stderr,
            )
            return 2
        tree = parse_file(path)
        errored = has_parse_errors(tree)
        diagnostic = (
            f"format_java.py: parsed {path} "
            f"(root={tree.root_node.type}, "
            f"children={len(tree.root_node.children)}, "
            f"{'errors' if errored else 'clean'})"
        )
        # Errors go to stderr so CI greps work; success goes to
        # stdout so the diagnostic can be redirected/piped.
        print(diagnostic, file=sys.stderr if errored else sys.stdout)
        return 1 if errored else 0

    # No action flag supplied. Phase 2a does not yet format files;
    # format_file.py is the entry point that today still routes to
    # the legacy JDT pipeline.
    print(
        "format_java.py: emitter is not yet implemented (Phase 2a "
        "is scaffolding). Use --check-grammar to verify the parser "
        "loads, or --parse FILE to inspect a parse result. The "
        "end-user formatter entry point is `format_file.py`.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(_main())
