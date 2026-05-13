"""Canonical Java formatter for the senzing-garage standards.

This module is the AST-based replacement for the JDT+six-script
pipeline that shipped through 0.2.x. It parses each Java source file
to a tree-sitter-java CST and (eventually) emits spec-compliant text
directly per the rules in `docs/java-coding-standards.md`.

Status (Phase 2c — minimal class declarations):
    - tree-sitter-java is loaded and a Parser is wired up.
    - File parsing works and the resulting tree can be inspected.
    - `Emitter` provides the token-stream output buffer used by
      the recursive emit walk. Tracks current column, indent
      level, and strips trailing whitespace per the spec's
      "Trailing Whitespace and End-of-File Newline" rule.
    - Leaf-node emitters are wired up for literals (integer,
      floating-point, character, string, null), boolean keywords,
      `this` / `super`, `identifier` / `type_identifier`, and
      primitive types (`integral_type`, `floating_point_type`,
      `boolean_type`, `void_type`).
    - Structural emitters cover `program`, `class_declaration`
      (no type parameters / extends-implements yet),
      `class_body`, `field_declaration`, `variable_declarator`,
      and `modifiers` (keyword-only — annotations refuse).
    - `format_source()` is functional for the supported subset:
      a single top-level class with optional keyword modifiers
      (no annotations), no type parameters, no extends /
      implements, whose body contains primitive- or named-typed
      field declarations with optional keyword modifiers and
      optional literal initializers. Anything outside the
      subset raises `NotImplementedError` from the dispatcher
      (the explicit "not yet supported" signal during
      incremental rollout).
    - The end-user entry point `format_file.py` still routes
      through the legacy JDT-plus-six-script pipeline; activation
      of this module as the active formatter comes in the phase
      that removes JDT.

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
# Node emitters
# ---------------------------------------------------------------------------


# Signature every node emitter must satisfy.
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
        # Indented contexts (e.g. a field initializer inside a
        # class body) need the developer's source-side indent
        # stripped from each content line and the formatter's
        # indent re-applied per the "Text Blocks" spec section's
        # "Closing `\"\"\"` placement" subsection. That logic
        # doesn't yet exist; refuse to emit rather than produce a
        # text block whose content lines sit at column 0
        # regardless of surrounding indent.
        if emitter.indent_level > 0:
            raise NotImplementedError(
                f"Multi-line {node.type!r} inside an indented "
                "context is not yet supported — indent-aware "
                "text-block emission lands in a later phase."
            )
        emitter.write_raw_lines(text)
    else:
        emitter.write(text)


# ---------------------------------------------------------------------------
# Structural emitters
# ---------------------------------------------------------------------------


def _emit_program(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Top-level emitter — the parse-tree root for any Java file.

    Phase 2c handles a single top-level type declaration. Multiple
    top-level declarations and `package` / `import` headers will
    be added in subsequent phases. An empty program (e.g. a
    whitespace-only file) emits nothing — `finish()` then produces
    `b""` per its empty-buffer rule.
    """
    for child in node.named_children:
        _emit_node(emitter, source, child)


def _emit_class_declaration(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit a class declaration with Allman brace placement.

    Currently handles the form
    `[modifiers] class Name { [members...] }` — optional keyword
    modifiers (no annotations yet), no type parameters, no
    `extends` / `implements` / `permits`. Those omitted clauses
    (and the more complex priority-by-line-length wrapping in
    the spec's "Class Headers" section) are added in subsequent
    phases. If a node carries one of those unsupported clauses,
    this function raises `NotImplementedError` — the explicit
    "not yet supported" signal.
    """
    # Inspect direct named children: capture the optional
    # `modifiers` block; refuse the not-yet-supported clauses.
    # Those clauses have their own priority-by-line-length
    # wrapping in the "Class Headers" spec section that the
    # current emitter doesn't yet handle.
    modifiers_node: Node | None = None
    for child in node.named_children:
        if child.type in (
            "type_parameters",
            "superclass",
            "super_interfaces",
            "permits",
        ):
            raise NotImplementedError(
                f"class_declaration child {child.type!r} is not "
                "yet supported; that construct comes in a later "
                "phase."
            )
        if child.type == "modifiers":
            modifiers_node = child

    name = node.child_by_field_name("name")
    body = node.child_by_field_name("body")

    if modifiers_node is not None:
        _emit_node(emitter, source, modifiers_node)
        emitter.write(" ")
    emitter.write("class ")
    if name is not None:
        _emit_node(emitter, source, name)
    emitter.newline()
    emitter.write("{")
    emitter.newline()
    if body is not None:
        _emit_class_body_members(emitter, source, body)
    emitter.write("}")
    emitter.newline()


def _emit_class_body_members(
    emitter: Emitter, source: bytes, body_node: Node
) -> None:
    """Emit the members of a class body, indented one level.

    The opening `{` and closing `}` are emitted by the caller
    (`_emit_class_declaration`); this function emits only the
    interior. Per the spec's "Blank-Line Rules Between Class
    Members" section, fields without javadoc pack together (no
    blank line between them); Phase 2c doesn't yet support
    javadoc, so all fields are packed. No blank line is left
    between the last member and the closing brace (the spec's
    "Right before class closing }" row).

    Caller contract: enter at column 0 on a fresh line (the line
    after the opening `{`); leave at column 0 on a fresh line
    (the line on which the caller will write `}`).
    """
    members = list(body_node.named_children)
    if not members:
        return
    emitter.push_indent()
    for member in members:
        emitter.write_indent()
        _emit_node(emitter, source, member)
        emitter.newline()
    emitter.pop_indent()


def _emit_field_declaration(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit a field declaration: `TYPE NAME [= VALUE][, ...] ;`.

    Phase 2c handles primitive types and named type references
    (e.g. `String`) with optional literal initializers. Modifiers
    and annotations on the field are refused here; they come in
    later phases.
    """
    modifiers_node: Node | None = None
    for child in node.named_children:
        if child.type == "modifiers":
            modifiers_node = child
            break

    if modifiers_node is not None:
        _emit_node(emitter, source, modifiers_node)
        emitter.write(" ")

    type_node = node.child_by_field_name("type")
    if type_node is None:
        raise NotImplementedError(
            "field_declaration missing 'type' field — grammar "
            "shape unexpected."
        )
    _emit_node(emitter, source, type_node)
    emitter.write(" ")

    # Multiple variable_declarators are separated by ", ". The
    # grammar exposes all declarator children with the same
    # field name 'declarator', so iterate by name not by field
    # accessor (which returns only the first).
    declarators = [
        c for c in node.children if c.type == "variable_declarator"
    ]
    for index, declarator in enumerate(declarators):
        if index > 0:
            emitter.write(", ")
        _emit_node(emitter, source, declarator)
    emitter.write(";")


def _emit_modifiers(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit a list of modifiers, space-separated.

    Phase 2d handles keyword-only modifiers (`public`,
    `private`, `protected`, `static`, `final`, `abstract`,
    `volatile`, `synchronized`, `native`, `strictfp`,
    `transient`, `default`). Annotations within a `modifiers`
    node (`marker_annotation`, `annotation`, etc.) are refused
    with `NotImplementedError` — those land in a later phase
    with their own per-annotation wrapping rules from the
    "Annotations" spec section.

    Modifier order is preserved from the source. The JLS
    conventional order
    (`public protected private abstract static final transient
    volatile synchronized native strictfp default`) is a coding
    convention enforced by checkstyle, not by this formatter.
    """
    parts: list[str] = []
    for child in node.children:
        if child.is_named:
            # Named modifier children are annotations
            # (marker_annotation, annotation, etc.). Phase 2d
            # doesn't yet handle them; refuse to emit rather
            # than drop the annotation silently.
            raise NotImplementedError(
                f"Annotation in modifiers ({child.type!r}) is "
                "not yet supported; annotation emission lands "
                "in a later phase."
            )
        parts.append(child.type)
    if not parts:
        # Defensive: the grammar should never produce an empty
        # `modifiers` node, but if it did, the caller's
        # "write a trailing space" wouldn't make sense after
        # an empty emission. Refuse to emit a stray separator.
        return
    emitter.write(" ".join(parts))


def _emit_variable_declarator(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `NAME` or `NAME = VALUE`.

    Spaces around `=` are spec-required (the
    "Whitespace and Operator Spacing" section's row for
    assignment operators).
    """
    name = node.child_by_field_name("name")
    value = node.child_by_field_name("value")
    if name is None:
        raise NotImplementedError(
            "variable_declarator missing 'name' field — grammar "
            "shape unexpected."
        )
    _emit_node(emitter, source, name)
    if value is not None:
        emitter.write(" = ")
        _emit_node(emitter, source, value)


# Maps tree-sitter-java node type to its emitter. Adding a new
# emitter is purely a matter of registering it here. The
# dispatcher's `NotImplementedError` on an unknown type is the
# formatter's way of saying "this construct isn't yet supported"
# — that's preferable to silently passing source text through
# (which would propagate non-spec-compliant input).
_NODE_EMITTERS: Final[dict[str, EmitterFn]] = {
    # --- Leaf tokens (Phase 2b) ---
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
    # byte-for-byte per the "Text Blocks / Content preservation"
    # spec section.
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
    # Primitive type nodes wrap a single anonymous keyword child
    # (e.g. `int`, `double`); their source span is the keyword
    # text and emits verbatim with no special handling.
    "integral_type": _emit_verbatim,
    "floating_point_type": _emit_verbatim,
    "boolean_type": _emit_verbatim,
    "void_type": _emit_verbatim,
    # --- Structural emitters ---
    "program": _emit_program,
    "class_declaration": _emit_class_declaration,
    "field_declaration": _emit_field_declaration,
    "variable_declarator": _emit_variable_declarator,
    "modifiers": _emit_modifiers,
}

def _emit_node(emitter: Emitter, source: bytes, node: Node) -> None:
    """Dispatch a single node to its registered emitter.

    Raises `NotImplementedError` for node types not yet handled,
    which is the explicit "this construct isn't supported yet"
    signal during incremental rollout.
    """
    handler = _NODE_EMITTERS.get(node.type)
    if handler is None:
        raise NotImplementedError(
            f"No emitter registered for node type {node.type!r}"
        )
    handler(emitter, source, node)


def format_source(source: bytes) -> bytes:
    """Format a Java source byte string per the project standards.

    Phase 2c: handles a top-level class declaration with no
    modifiers / type parameters / extends / implements, whose body
    contains primitive-typed or named-typed field declarations
    with optional literal initializers. Anything outside that
    subset raises `NotImplementedError` from the dispatcher (the
    explicit "this construct isn't supported yet" signal).

    The `format_file.py` orchestrator still routes end-user
    formatting through the legacy JDT-plus-six-script pipeline;
    activation of this path comes in the phase that removes JDT.
    """
    tree = parse_source(source)
    if has_parse_errors(tree):
        raise ValueError(
            "format_source() refuses to emit output for input "
            "with parse errors — the resulting text could be "
            "garbled. Fix the syntax error in the input first."
        )
    emitter = Emitter()
    _emit_node(emitter, source, tree.root_node)
    return emitter.finish()


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="format_java.py",
        description=(
            "Canonical AST-based Java formatter for the "
            "senzing-garage standards (incremental rollout — "
            "see the module docstring for the currently-supported "
            "Java subset)."
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

    # No action flag supplied. format_java.py is not the end-user
    # entry point — format_file.py is, and it today still routes
    # through the legacy JDT pipeline. The supported subset of
    # format_source() is documented in the module docstring and
    # is currently limited to minimal class declarations; running
    # this script with no flags is therefore deliberately a hard
    # error so callers don't accidentally invoke an early-rollout
    # formatter as if it were the production entry point.
    print(
        "format_java.py: this script is not the end-user "
        "formatter entry point — use `format_file.py` instead. "
        "Pass --check-grammar to verify the parser loads, or "
        "--parse FILE to inspect a parse result.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(_main())
