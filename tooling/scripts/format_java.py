"""Canonical Java formatter for the senzing-garage standards.

This module is the AST-based replacement for the JDT+six-script
pipeline that shipped through 0.2.x. It parses each Java source file
to a tree-sitter-java CST and (eventually) emits spec-compliant text
directly per the rules in `docs/java-coding-standards.md`.

Status (Phase 2b — token-level emission):
    - tree-sitter-java is loaded and a Parser is wired up.
    - File parsing works and the resulting tree can be inspected.
    - `Emitter` provides the token-stream output buffer used by
      the recursive emit walk. Tracks current column and strips
      trailing whitespace per the spec's A5 rule.
    - Leaf-node emitters are wired up for literals (integer,
      floating-point, character, string, null), boolean keywords,
      `this` / `super`, and `identifier` / `type_identifier`.
    - Structural emitters (statements, declarations, expressions)
      are NOT yet implemented. `format_source()` raises
      `NotImplementedError` until the recursive walk lands. The
      end-user entry point `format_file.py` still routes through
      the legacy JDT-plus-six-script pipeline; this module will be
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
from typing import Callable, Final

import tree_sitter_java
from tree_sitter import Language, Node, Parser, Tree


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


# ---------------------------------------------------------------------------
# Token-stream output buffer
# ---------------------------------------------------------------------------


class Emitter:
    """Append-only output buffer with column tracking.

    The recursive emit walk pushes tokens left-to-right onto an
    `Emitter` instance. Each call to `write()` appends a string
    fragment to the current line; `newline()` finalizes the current
    line and starts a new one. The current column is tracked so
    wrapping-priority logic can ask "would this fit?" before
    committing to a particular layout.

    Trailing whitespace is stripped per the spec's
    "Trailing Whitespace and End-of-File Newline" section: any
    spaces at the end of a line are dropped when the line is
    finalized (via `newline()` or `finish()`). The final byte of
    output is always exactly one `\\n` — `finish()` enforces that.

    Note: `column` is a CHARACTER count, not a display-width count.
    The project standard forbids tab characters in Java source
    (Indentation section), so formatter-emitted output never
    contains tabs — character count equals display column for the
    formatter's own emission. Developer content reproduced via
    `write_raw_lines` (text blocks) MAY contain tabs; the column
    value after such a block reflects characters, not visual
    width. The wrapping logic in later phases must keep this in
    mind if it ever measures width immediately after a verbatim
    block.
    """

    __slots__ = ("_lines", "_current", "_indent")

    def __init__(self) -> None:
        self._lines: list[str] = []
        self._current: str = ""
        self._indent: int = 0

    @property
    def column(self) -> int:
        """The 0-based column at the end of the current line."""
        return len(self._current)

    @property
    def line_count(self) -> int:
        """Lines finalized so far (excludes the in-progress line)."""
        return len(self._lines)

    @property
    def indent_level(self) -> int:
        """Current indent depth in 4-space units (informational)."""
        return self._indent

    def write(self, text: str) -> None:
        """Append `text` to the current line.

        `text` must not contain `\\n`. Callers that need a line
        break call `newline()` explicitly. This keeps newline
        accounting out of the leaf-emitter loop and gives the
        wrapping logic an exact column count it can trust.
        """
        if "\n" in text:
            raise ValueError(
                "Emitter.write() does not accept newlines; "
                "call newline() explicitly. Got: " + repr(text)
            )
        self._current += text

    def write_indent(self) -> None:
        """Emit the current indent prefix at the start of a line.

        Only valid at column 0. Emits `4 * indent_level` spaces.
        """
        if self._current:
            # Bound the diagnostic so a developer's long source
            # line doesn't blow up traceback formatting in CI.
            preview = self._current[:32]
            ellipsis = "..." if len(self._current) > 32 else ""
            raise ValueError(
                "write_indent() only valid at column 0; current "
                f"line has {len(self._current)} chars starting "
                f"with {preview!r}{ellipsis}"
            )
        self._current = " " * (4 * self._indent)

    def newline(self) -> None:
        """Finalize the current line and start a fresh one.

        Trailing spaces on the finalized line are stripped before
        commit so emitters need not pre-trim them.
        """
        self._lines.append(self._current.rstrip(" "))
        self._current = ""

    def write_raw_lines(self, text: str) -> None:
        """Append text that may contain newlines, preserved verbatim.

        Used by leaf emitters for content the formatter must
        reproduce byte-for-byte — text blocks ("Text Blocks /
        Content preservation" spec section) and eventually block
        comments. Newlines inside `text` finalize each intermediate
        line WITHOUT stripping trailing whitespace, since that
        whitespace is the developer's content (the spec's
        "Normalize spacing or alignment of content is a no-op"
        rule applies to text-block contents).

        The in-progress line at the END of `text` (the part after
        the last newline) is left open so subsequent `write()` /
        `newline()` calls continue normally. Note: trailing
        whitespace that the DEVELOPER wrote at the very end of a
        text block (after the final newline, before any
        formatter-emitted continuation) will be stripped by the
        eventual `newline()` / `finish()` — that case doesn't
        arise in well-formed Java source because every
        `string_literal` ends with a non-whitespace closing
        quote token, so the final segment passed here is never a
        bare-whitespace string. Future emitters that pass other
        kinds of verbatim multi-line content should guarantee the
        same invariant.
        """
        parts = text.split("\n")
        # First segment continues the current line.
        self._current += parts[0]
        for part in parts[1:]:
            # Each intermediate line is verbatim — NO strip.
            self._lines.append(self._current)
            self._current = part

    def push_indent(self) -> None:
        """Increase the indent level by one (4 spaces)."""
        self._indent += 1

    def pop_indent(self) -> None:
        """Decrease the indent level by one."""
        if self._indent <= 0:
            raise ValueError(
                "Emitter.pop_indent() called with indent_level=0"
            )
        self._indent -= 1

    def finish(self) -> bytes:
        """Finalize the output and return it as a UTF-8 byte string.

        Behavior:
            - Any in-progress (non-finalized) line is finalized
              with trailing whitespace stripped.
            - The output ends with exactly one `\\n` — empty
              trailing lines are NOT emitted.
            - Output consisting solely of blank lines (or a buffer
              with no `write()` calls at all) produces `b""`, not
              `b"\\n"`. The single trailing newline is reserved
              for files with at least one byte of real content.
        """
        if self._current:
            self._lines.append(self._current.rstrip(" "))
            self._current = ""
        if not self._lines:
            return b""
        # Drop any trailing all-empty lines to keep the EOF
        # contract exact (one newline at end, no trailing blanks).
        while self._lines and self._lines[-1] == "":
            self._lines.pop()
        if not self._lines:
            return b""
        return ("\n".join(self._lines) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Leaf-node emitters
# ---------------------------------------------------------------------------


# Signature every node emitter must satisfy. Phase 2c's structural
# emitters use the same shape.
EmitterFn = Callable[[Emitter, bytes, Node], None]


def _node_source_text(source: bytes, node: Node) -> str:
    """Return the source text for `node` as a UTF-8 string."""
    return source[node.start_byte:node.end_byte].decode("utf-8")


# Leaf nodes whose canonical formatted form is byte-for-byte
# identical to their source text. Literals never get rewritten —
# `42L` stays `42L`, `0xFFp-1` stays `0xFFp-1`, etc. — and named
# identifiers are likewise reproduced verbatim. Each handler
# receives `(emitter, source, node)` and writes the node's text
# to the emitter.
def _emit_verbatim(emitter: Emitter, source: bytes, node: Node) -> None:
    text = _node_source_text(source, node)
    # Most leaf tokens are single-line; the exception is
    # `string_literal` carrying a triple-quoted text block, whose
    # content the "Text Blocks / Content preservation" spec
    # section requires be preserved byte-for-byte (including any
    # embedded newlines).
    if "\n" in text:
        emitter.write_raw_lines(text)
    else:
        emitter.write(text)


# Maps tree-sitter-java node type to its emitter. Phase 2b covers
# leaf tokens only; structural node types (class_declaration,
# method_declaration, expression_statement, etc.) get added in
# subsequent phases. The dispatcher's KeyError on an unknown type
# is the formatter's way of saying "this construct isn't yet
# supported" — that's preferable to silently passing source text
# through (which would propagate non-spec-compliant input).
_LEAF_EMITTERS: Final[dict[str, EmitterFn]] = {
    # Numeric literals — formatted identical to source.
    "decimal_integer_literal": _emit_verbatim,
    "hex_integer_literal": _emit_verbatim,
    "octal_integer_literal": _emit_verbatim,
    "binary_integer_literal": _emit_verbatim,
    "decimal_floating_point_literal": _emit_verbatim,
    "hex_floating_point_literal": _emit_verbatim,
    # Character and string literals — content preserved verbatim.
    # string_literal has nested children (quote, fragment, quote);
    # for triple-quoted text blocks (Java 15+) the grammar still
    # uses `string_literal` with `multiline_string_fragment`
    # children. The full source span of the node is the canonical
    # form for both regular and text-block literals — preserved
    # byte-for-byte per the B4 spec section.
    "character_literal": _emit_verbatim,
    "string_literal": _emit_verbatim,
    # Keyword-valued nodes that the grammar exposes as named.
    "null_literal": _emit_verbatim,
    "true": _emit_verbatim,
    "false": _emit_verbatim,
    "this": _emit_verbatim,
    "super": _emit_verbatim,
    # Identifiers.
    "identifier": _emit_verbatim,
    "type_identifier": _emit_verbatim,
}


def _emit_node(emitter: Emitter, source: bytes, node: Node) -> None:
    """Dispatch a single node to its registered emitter.

    Raises `NotImplementedError` for node types not yet handled,
    which is the explicit "this construct isn't supported yet"
    signal during incremental rollout.
    """
    handler = _LEAF_EMITTERS.get(node.type)
    if handler is None:
        raise NotImplementedError(
            f"No emitter registered for node type {node.type!r}"
        )
    handler(emitter, source, node)


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
