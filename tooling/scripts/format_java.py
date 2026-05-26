"""Canonical Java formatter for the senzing-garage standards.

This module is the AST-based replacement for the JDT+six-script
pipeline that shipped through 0.2.x. It parses each Java source file
to a tree-sitter-java CST and (eventually) emits spec-compliant text
directly per the rules in `docs/java-coding-standards.md`.

Status (Phase 2z — enum constants with anonymous bodies):
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
      `modifiers` (keyword-only — annotations refuse),
      `method_declaration` (now with statement bodies; throws
      clauses, type parameters, and abstract / interface
      methods still refuse), `formal_parameters` (single-line),
      `formal_parameter`, and `array_type` (for `Type[]`
      parameter types).
    - Statement emitters cover `return_statement` (with or
      without a value), `expression_statement` (assignment-as-
      statement, method-call statement, update statement),
      `local_variable_declaration` (shared emitter with
      `field_declaration` — both have identical grammar
      shape), `assignment_expression` (with space-space
      around any assignment operator), `block` (same-line
      brace for control-flow constructs), `if_statement`
      (with cuddled `} else {` and else-if chains;
      brace-less Tier 1 short-circuit form refuses),
      `for_statement` (classic three-part header and empty
      `for (;;)`), `enhanced_for_statement` (for-each form
      with `:` separator), `while_statement`,
      `do_statement` (with cuddled `} while (cond);`), and
      `try_statement` with `catch_clause` (cuddled
      `} catch (...) {`), `finally_clause` (cuddled
      `} finally {`), `catch_formal_parameter`, and
      `catch_type` (with multi-catch `TYPE | TYPE | ...`
      single-line form, space-space around `|` per spec B7).
      `throw_statement`, `break_statement` and
      `continue_statement` (each with optional label per
      spec C7), and `labeled_statement` (label on its own
      line, statement on the next at the same indent per
      spec C7). `try_with_resources_statement` covers both
      single-resource (same-line brace) and multi-resource
      (one resource per line, paren-aligned with the first,
      Allman brace) forms per spec B8; the break-on-`=`
      wrap for a resource that overflows its own line lands
      with the wrap-priority phase. Remaining control-flow
      constructs (`switch`, `synchronized`) refuse until
      subsequent phases.
    - Expression emitters cover `binary_expression`,
      `unary_expression`, `update_expression`,
      `parenthesized_expression`, `field_access`,
      `instanceof_expression` (non-pattern form),
      `cast_expression`, `method_invocation` (single-line
      only — wrap rules deferred), and `argument_list`.
      Operator spacing follows the "Whitespace and Operator
      Spacing" spec section throughout.
    - `format_source()` is functional for the supported subset:
      a single top-level class with optional keyword modifiers
      (no annotations), no type parameters, no extends /
      implements, whose body contains primitive- or named-typed
      field declarations with optional keyword modifiers and
      optional initializers. Initializers can be literal
      values, identifiers, binary / unary / update /
      parenthesized expressions, field accesses, casts,
      non-pattern instanceof, or method invocations whose
      single-line form fits within reasonable bounds. Anything
      outside the subset raises `NotImplementedError` from the
      dispatcher (the explicit "not yet supported" signal
      during incremental rollout).
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

    def snapshot(self) -> tuple[int, str, int]:
        """Capture the emitter state for speculative emission.

        Returns a tuple `(lines_count, current, indent)`
        suitable for `restore()`. The wrap-priority engines use
        the pattern:

            saved = emitter.snapshot()
            <try emitting in some shape>
            if overflowed:
                emitter.restore(saved)
                <emit in the next-priority shape>

        Cheap because the lines list is immutable from the
        perspective of restore (we capture its length, not its
        contents).
        """
        return (len(self._lines), self._current, self._indent)

    def restore(
        self, snap: tuple[int, str, int]
    ) -> None:
        """Restore a previously-captured state from `snapshot()`.

        Truncates the lines list back to its captured length
        and resets the current line + indent. Any text emitted
        after the snapshot is discarded.
        """
        lines_count, current, indent = snap
        del self._lines[lines_count:]
        self._current = current
        self._indent = indent

    def last_lines_max_width(self, since: int) -> int:
        """Return the maximum width across all lines finalized
        after the snapshot at `since` (the `lines_count` value
        returned by `snapshot()`) plus the in-progress line.

        Used by wrap-priority engines to detect overflow after
        a speculative emit: if `last_lines_max_width(saved[0])`
        exceeds 80, the speculation overflowed and needs
        backtracking.
        """
        m = 0
        for line in self._lines[since:]:
            if len(line) > m:
                m = len(line)
        if len(self._current) > m:
            m = len(self._current)
        return m

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


def _node_spans_multiple_rows(node: Node) -> bool:
    """Return True when `node`'s source span crosses multiple
    lines (start_row != end_row).

    Used by wrap-priority emitters to detect developer-authored
    multi-line headers (`while (cond_spanning_two_lines)`,
    `method(p1,\\n p2)`, etc.) so the formatter can switch the
    associated brace placement from same-line to Allman per the
    spec's "Brace Placement / Exception: Multi-Line Conditions"
    rule.
    """
    return node.start_point[0] != node.end_point[0]


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

    Emits each top-level declaration with appropriate separator
    blanks per spec A1 ("Import Organization") and the general
    A2 blank-line rules between top-level constructs:

        - `package_declaration` followed by a blank line.
        - `import_declaration`s pack together (no blank between
          consecutive imports); a blank line separates the last
          import from the following type declaration.
        - Each top-level type declaration (class / interface /
          enum / record) starts on its own line, separated by a
          blank from whatever precedes it.

    The full spec A1 import-grouping/sorting (java/javax static
    first, then non-static, with blanks between non-empty
    groups) lands in a later phase — for now the formatter
    preserves the source order of imports.

    An empty program (e.g. a whitespace-only file) emits
    nothing; `finish()` produces `b""` per its empty-buffer
    rule.
    """
    children = list(node.named_children)
    prev: Node | None = None
    for child in children:
        if prev is not None:
            # Insert a separator newline (or blank line) based on
            # the prev/this combination. Each top-level emitter
            # ends mid-line (no trailing newline); `_emit_program`
            # adds the line terminator and any blank.
            emitter.newline()
            blank_between = _program_blank_between(prev, child)
            if blank_between:
                emitter.newline()
        _emit_node(emitter, source, child)
        prev = child


def _program_blank_between(prev: Node, this: Node) -> bool:
    """Decide whether to emit a blank line between two top-level
    declarations. See `_emit_program` for the spec-anchored
    rules.
    """
    if prev.type == "package_declaration":
        # Blank between package and whatever follows (imports
        # OR type declaration).
        return True
    if prev.type == "import_declaration":
        # No blank between consecutive imports; blank before a
        # following type declaration.
        return this.type != "import_declaration"
    if prev.type in ("block_comment", "line_comment"):
        # A leading javadoc / comment attaches to the next
        # declaration per spec A1 ("Class-level javadoc
        # placement" — directly above the type declaration with
        # no blank between). Source-preserve: emit a blank only
        # when the source had a blank between the comment and
        # the next item.
        return this.start_point[0] - prev.end_point[0] > 1
    # Between two top-level type declarations — blank.
    return True


def _emit_package_declaration(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `package X.Y.Z;`. Grammar: a `scoped_identifier`
    child holding the dotted name.
    """
    name = None
    for c in node.named_children:
        if c.type in ("scoped_identifier", "identifier"):
            name = c
            break
    if name is None:
        raise NotImplementedError(
            "package_declaration missing scoped name child — "
            "grammar shape unexpected."
        )
    emitter.write("package ")
    _emit_node(emitter, source, name)
    emitter.write(";")


def _emit_import_declaration(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `import [static] X.Y.Z;`. Grammar: optional
    anonymous `static` keyword child followed by a
    scoped_identifier holding the dotted name. The wildcard
    form (`import java.util.*;`) is exposed via an anonymous
    `*` token sibling — emit by inspecting all children.
    """
    is_static = False
    name = None
    has_wildcard = False
    for c in node.children:
        if c.is_named and c.type in (
            "scoped_identifier", "identifier"
        ):
            name = c
        elif c.is_named and c.type == "asterisk":
            # tree-sitter-java exposes the wildcard as a named
            # `asterisk` child (NOT an anonymous `*` token).
            has_wildcard = True
        elif not c.is_named and c.type == "static":
            is_static = True
    if name is None:
        raise NotImplementedError(
            "import_declaration missing scoped name child — "
            "grammar shape unexpected."
        )
    emitter.write("import ")
    if is_static:
        emitter.write("static ")
    _emit_node(emitter, source, name)
    if has_wildcard:
        emitter.write(".*")
    emitter.write(";")


def _emit_scoped_identifier(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit a dotted name (`com.foo.Bar`) verbatim from source.
    Used for package names, import names, and qualified type
    references. tree-sitter-java surfaces dotted names as
    nested `scoped_identifier`/`identifier` trees; the source
    span is the canonical form.
    """
    emitter.write(_node_source_text(source, node))


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
    # `modifiers` block, `type_parameters`, `superclass`,
    # `super_interfaces`. `permits` (sealed types) still
    # refuses — wrap-priority for permits lands later.
    modifiers_node: Node | None = None
    type_parameters_node: Node | None = None
    superclass_node: Node | None = None
    super_interfaces_node: Node | None = None
    for child in node.named_children:
        if child.type == "permits":
            raise NotImplementedError(
                f"class_declaration child {child.type!r} is not "
                "yet supported; that construct comes in a later "
                "phase."
            )
        if child.type == "modifiers":
            modifiers_node = child
        elif child.type == "type_parameters":
            type_parameters_node = child
        elif child.type == "superclass":
            superclass_node = child
        elif child.type == "super_interfaces":
            super_interfaces_node = child

    name = node.child_by_field_name("name")
    body = node.child_by_field_name("body")

    # Capture the class declaration's start column for the
    # type-parameter-wrap continuation indent (single-indent
    # past the class start = start_col + 4).
    start_col = emitter.column

    if modifiers_node is not None:
        # `_emit_modifiers` emits its own trailing space (for
        # keyword modifiers) or its own trailing newline +
        # indent (for annotation-only modifiers), so the
        # caller does not write a separator here.
        _emit_node(emitter, source, modifiers_node)
    emitter.write("class ")
    if name is not None:
        _emit_node(emitter, source, name)

    # Try-emit the single-line class header. If overflow,
    # backtrack and emit with type-parameter wrap.
    saved = emitter.snapshot()
    if type_parameters_node is not None:
        # Per spec B11: `<...>` comes immediately after the
        # class name with no intervening space.
        _emit_node(emitter, source, type_parameters_node)
    if superclass_node is not None:
        emitter.write(" ")
        _emit_node(emitter, source, superclass_node)
    if super_interfaces_node is not None:
        emitter.write(" ")
        _emit_node(emitter, source, super_interfaces_node)
    if emitter.column > _MAX_LINE:
        # Overflow — backtrack and rewrap.
        emitter.restore(saved)
        _emit_class_header_wrapped(
            emitter,
            source,
            type_parameters_node,
            superclass_node,
            super_interfaces_node,
            start_col,
        )

    emitter.newline()
    emitter.write_indent()
    emitter.write("{")
    emitter.newline()
    if body is not None:
        _emit_class_body_members(emitter, source, body)
    emitter.write_indent()
    emitter.write("}")


def _emit_class_header_wrapped(
    emitter: Emitter,
    source: bytes,
    type_parameters_node: Node | None,
    superclass_node: Node | None,
    super_interfaces_node: Node | None,
    start_col: int,
) -> None:
    """Emit the type-parameter / extends / implements portion of a
    class declaration in wrapped form. Caller has already emitted
    `[modifiers] class NAME`; this function appends the type-
    parameter list (with wrap) and the extends / implements
    clauses.

    The wrap shape: the first type-parameter stays on the class
    declaration line (right after `<`). Subsequent type-parameters
    each go on their own continuation line at `start_col + 4`
    (single-indent past the class start). The closing `>` ends
    the last type-parameter's line, followed by ` extends X` and
    ` implements Y, Z` (which stay on that same line if they fit).
    """
    cont_indent = " " * (start_col + 4)
    if type_parameters_node is not None:
        params = [
            c for c in type_parameters_node.named_children
            if c.type == "type_parameter"
        ]
        emitter.write("<")
        for index, p in enumerate(params):
            if index > 0:
                emitter.write(",")
                emitter.newline()
                emitter.write(cont_indent)
            _emit_node(emitter, source, p)
        emitter.write(">")
    if superclass_node is not None:
        emitter.write(" ")
        _emit_node(emitter, source, superclass_node)
    if super_interfaces_node is not None:
        emitter.write(" ")
        _emit_node(emitter, source, super_interfaces_node)


def _emit_class_body_members(
    emitter: Emitter, source: bytes, body_node: Node
) -> None:
    """Emit the members of a class body, indented one level.

    The opening `{` and closing `}` are emitted by the caller
    (`_emit_class_declaration`); this function emits only the
    interior.

    Per spec A2 "Blank-Line Rules Between Class Members": a
    blank line appears between most consecutive members
    (method ↔ method, method ↔ inner class, around static
    initializers, last field ↔ first non-field, javadoc'd
    members, etc.); consecutive fields without javadoc pack
    together with no blank between.

    Implementation: source-preservation. When the source has
    a blank line between two consecutive members (detected
    via `prev.end_point[0] + 1 < next.start_point[0]`), emit
    a blank line in output. This handles spec A2 implicitly
    because real consumer code already follows the rules.
    Multiple consecutive blank lines collapse to a single one
    per spec A2's normalization rule.

    Caller contract: enter at column 0 on a fresh line (the line
    after the opening `{`); leave at column 0 on a fresh line
    (the line on which the caller will write `}`).
    """
    members = list(body_node.named_children)
    if not members:
        return
    emitter.push_indent()
    prev: Node | None = None
    for member in members:
        if prev is not None:
            # If the source had at least one blank line between
            # prev's last row and this member's first row,
            # emit a single blank line.
            if member.start_point[0] - prev.end_point[0] > 1:
                emitter.newline()
        emitter.write_indent()
        _emit_node(emitter, source, member)
        emitter.newline()
        prev = member
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
        # `_emit_modifiers` emits its own trailing space (for
        # keyword modifiers) or its own trailing newline +
        # indent (for annotation-only modifiers), so the
        # caller does not write a separator here.
        _emit_node(emitter, source, modifiers_node)

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


def _emit_binary_expression(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `LEFT OP RIGHT` with a single space on each side of OP.

    Per the "Whitespace and Operator Spacing" spec section, every
    binary operator gets exactly one space on each side. The
    grammar exposes the binary operator as an anonymous keyword
    child between the two named operand children. Supported
    operators are whatever tree-sitter-java exposes as a
    `binary_expression`: `+`, `-`, `*`, `/`, `%`, `==`, `!=`,
    `<`, `>`, `<=`, `>=`, `&`, `|`, `^`, `<<`, `>>`, `>>>`,
    `&&`, `||`. `instanceof` is its own `instanceof_expression`
    node type in the grammar and is not handled here.

    When the single-line emission would push the line past 80
    chars, the emitter speculates the single-line shape and, on
    overflow, backtracks and re-emits with a break BEFORE the
    leftmost binary operator in the chain (per spec
    "Line Continuation / break before binary operators"). The
    leftmost operand lands on its own line; the operator plus
    the remainder of the chain wraps to a continuation line
    at +4 indent (cumulative per spec C3).
    """
    children = node.children
    if len(children) != 3:
        raise NotImplementedError(
            f"binary_expression with {len(children)} children — "
            "expected exactly 3 (left, operator, right)."
        )
    saved = emitter.snapshot()
    left, op, right = children
    _emit_node(emitter, source, left)
    emitter.write(" ")
    emitter.write(op.type)
    emitter.write(" ")
    _emit_node(emitter, source, right)
    if emitter.last_lines_max_width(saved[0]) <= _MAX_LINE:
        return
    # Overflow — backtrack and emit with a break before the
    # LEFTMOST binary operator in the chain. The grammar's
    # left-associative parse makes `a + b + c + d` look like
    # `BinExpr(BinExpr(BinExpr(a, +, b), +, c), +, d)`, so the
    # leftmost operator from a reader's perspective is the one
    # owned by the deepest left-descendant `binary_expression`.
    emitter.restore(saved)
    # Walk down the left chain to find the leftmost binary_-
    # expression in the same operator-spacing family.
    leftmost = node
    while True:
        candidate = leftmost.children[0]
        if candidate.type == "binary_expression":
            leftmost = candidate
        else:
            break
    leftmost_operand = leftmost.children[0]
    leftmost_op = leftmost.children[1]
    # Build the "after the leftmost operator" continuation by
    # emitting the leftmost operand, then a newline + +4
    # indent, then the operator, a space, and the rest of the
    # chain. For the "rest of the chain", we use the source
    # text from the byte right after the leftmost operator's
    # end through the outermost node's end — this captures
    # everything except the leftmost operand and operator and
    # preserves any nested formatting (string literals,
    # parentheses, etc.).
    _emit_node(emitter, source, leftmost_operand)
    emitter.newline()
    emitter.push_indent()
    emitter.write_indent()
    emitter.write(leftmost_op.type)
    emitter.write(" ")
    # Skip whitespace between leftmost_op.end_byte and the next
    # named child.
    rest_start = leftmost_op.end_byte
    rest_text = source[rest_start : node.end_byte].decode(
        "utf-8"
    ).lstrip()
    # `rest_text` may contain internal spaces around operators
    # from source. Use write_raw_lines to safely emit any
    # embedded newlines (the source may already have wrap that
    # the formatter preserves verbatim).
    if "\n" in rest_text:
        emitter.write_raw_lines(rest_text)
    else:
        emitter.write(rest_text)
    emitter.pop_indent()


def _emit_unary_expression(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `OP OPERAND` with no space between operator and operand.

    Per the "Whitespace and Operator Spacing" spec section, unary
    operators (`!`, `-`, `+`, `~`) are emitted with no space
    between the operator and the operand. The grammar exposes
    `unary_expression` with two children: the anonymous operator
    keyword followed by the named operand.
    """
    children = node.children
    if len(children) != 2:
        raise NotImplementedError(
            f"unary_expression with {len(children)} children — "
            "expected exactly 2 (operator, operand)."
        )
    op, operand = children
    emitter.write(op.type)
    _emit_node(emitter, source, operand)


def _emit_update_expression(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `++X` / `X++` / `--X` / `X--` with no space.

    The grammar exposes both prefix and postfix forms as
    `update_expression`. The order of children is:
        prefix:  [`++` | `--`, operand]
        postfix: [operand, `++` | `--`]
    No space between operator and operand in either form
    (per the "Whitespace and Operator Spacing" spec).
    """
    children = node.children
    if len(children) != 2:
        raise NotImplementedError(
            f"update_expression with {len(children)} children — "
            "expected exactly 2 (operator + operand)."
        )
    for child in children:
        if child.is_named:
            _emit_node(emitter, source, child)
        else:
            emitter.write(child.type)


def _emit_parenthesized_expression(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `(EXPR)` — no spaces inside the parens.

    Per the "Whitespace and Operator Spacing" spec row "Inside
    parentheses: No leading/trailing space." The grammar exposes
    three children: `(`, the inner named expression, and `)`.
    """
    inner: Node | None = None
    for child in node.children:
        if child.is_named:
            inner = child
            break
    if inner is None:
        raise NotImplementedError(
            "parenthesized_expression has no named inner child — "
            "grammar shape unexpected."
        )
    emitter.write("(")
    _emit_node(emitter, source, inner)
    emitter.write(")")


def _emit_method_declaration(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit a method declaration with Allman brace placement.

    Handles `[modifiers] TYPE NAME(formal_parameters)` on the
    signature line, Allman opening `{` on its own line at the
    same indent as the declaration (per the "Brace Placement /
    Allman Style" spec section), the body's statements
    indented one level deeper, and the closing `}` on its own
    line at the same indent as the declaration.

    Refuses:
        - `throws` clauses (later phase: throws-clause wrapping
          per the "Method and Constructor Declarations / Throws
          Clause" spec subsection)
        - Methods with no body field (abstract / interface
          methods) — interface bodies and abstract methods land
          in later phases
        - Methods carrying type parameters
          (`<T> void m()`) — generic-types phase

    Statement emission inside the body dispatches per the usual
    `_emit_node` rules; statement node types that aren't yet
    registered raise the standard "no emitter registered"
    NotImplementedError.

    Caller contract: the emitter ends mid-line at the closing
    `}` (column = current indent + 1). The caller appends the
    trailing newline that separates this member from whatever
    follows.
    """
    # Locate the optional modifiers, type_parameters, and
    # throws children.
    modifiers_node: Node | None = None
    type_parameters_node: Node | None = None
    throws_node: Node | None = None
    for child in node.named_children:
        if child.type == "modifiers":
            modifiers_node = child
        elif child.type == "type_parameters":
            type_parameters_node = child
        elif child.type == "throws":
            throws_node = child

    body = node.child_by_field_name("body")
    type_node = node.child_by_field_name("type")
    name_node = node.child_by_field_name("name")
    parameters_node = node.child_by_field_name("parameters")
    if type_node is None or name_node is None or parameters_node is None:
        raise NotImplementedError(
            "method_declaration missing 'type' / 'name' / "
            "'parameters' — grammar shape unexpected."
        )

    if modifiers_node is not None:
        # `_emit_modifiers` emits its own trailing space (for
        # keyword modifiers) or its own trailing newline +
        # indent (for annotation-only modifiers), so the
        # caller does not write a separator here.
        _emit_node(emitter, source, modifiers_node)
    if type_parameters_node is not None:
        # Per spec B11: `<T>` comes BEFORE the return type, with
        # a single space after the closing `>`.
        _emit_node(emitter, source, type_parameters_node)
        emitter.write(" ")
    _emit_node(emitter, source, type_node)
    emitter.write(" ")
    _emit_node(emitter, source, name_node)
    _emit_node(emitter, source, parameters_node)

    # Per "Method and Constructor Declarations / Throws
    # Clause", `throws` goes on its own line single-indented
    # (4 spaces from the method declaration). Single-line
    # form only — multi-line wrapping (the "one per line,
    # types left-aligned with a comma after all but the
    # last" priority-2 form from the same spec subsection)
    # lands with the wrap-priority phase.

    if body is None:
        # Abstract / interface method: signature [+ throws];
        # — no Allman braces, no body. The `;` terminates the
        # declaration (on the throws line if throws is
        # present, on the signature line otherwise).
        if throws_node is not None:
            emitter.newline()
            emitter.push_indent()
            emitter.write_indent()
            _emit_node(emitter, source, throws_node)
            emitter.pop_indent()
        emitter.write(";")
        return

    # Concrete method: Allman brace + body + closing `}`.
    emitter.newline()
    if throws_node is not None:
        emitter.push_indent()
        emitter.write_indent()
        _emit_node(emitter, source, throws_node)
        emitter.newline()
        emitter.pop_indent()
    emitter.write_indent()
    emitter.write("{")
    emitter.newline()

    statements = list(body.named_children)
    if statements:
        emitter.push_indent()
        prev_stmt: Node | None = None
        for stmt in statements:
            if prev_stmt is not None:
                if stmt.start_point[0] - prev_stmt.end_point[0] > 1:
                    emitter.newline()
            emitter.write_indent()
            _emit_node(emitter, source, stmt)
            emitter.newline()
            prev_stmt = stmt
        emitter.pop_indent()

    emitter.write_indent()
    emitter.write("}")
    # Caller appends the trailing newline.


def _emit_block(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit a control-flow block with same-line opening `{`.

    Per the "Brace Placement / Same-Line Style" spec section,
    blocks used by control-flow constructs (`if`, `else`, `for`,
    `while`, `do`, `try`, `catch`, `finally`, `switch`,
    `synchronized`) take the same-line opening-brace form. The
    caller is expected to have just emitted the preceding
    syntactic token (e.g. `"if (cond) "`) with a trailing space;
    this emitter then writes `"{"` continuing that line.

    Statements inside the block are emitted at one indent level
    deeper than the caller's current level. Closing `}` is
    emitted at the caller's level. The emitter ends mid-line at
    the closing `}` so the caller's `newline()` finalizes it.

    Per spec C6 ("Comment placement / End-of-line side
    comments"), a `line_comment` child whose source-row equals
    the opening `{`'s source-row is emitted INLINE on the `{`
    line — `{  // comment` — with exactly two spaces between
    the brace and `//`. Subsequent statements emit on their own
    lines as normal.

    Method-declaration bodies use the Allman form (opening `{`
    on its own line) and emit their body inline from
    `_emit_method_declaration` rather than dispatching here.
    """
    statements = list(node.named_children)
    brace_row = node.start_point[0]
    emitter.write("{")
    # Detect and emit any leading side-comment on the brace line.
    # Only consume children that share the brace's row AND are
    # comments — anything else (a statement on the same source
    # row, which is rare) emits normally below.
    consumed = 0
    while (
        consumed < len(statements)
        and statements[consumed].type
        in ("line_comment", "block_comment")
        and statements[consumed].start_point[0] == brace_row
    ):
        emitter.write("  ")
        _emit_node(emitter, source, statements[consumed])
        consumed += 1
    emitter.newline()
    # Preserve a developer-authored leading blank line between
    # the opening `{` and the first statement (source row of
    # the statement is `brace_row + 2` or more, meaning at
    # least one empty line sits between them). Per spec A2's
    # blank-line normalization, multiple consecutive blanks
    # condense to a single blank.
    emitter.push_indent()
    remaining = statements[consumed:]
    if remaining and remaining[0].start_point[0] - brace_row > 1:
        emitter.newline()
    prev_stmt: Node | None = None
    for stmt in remaining:
        if prev_stmt is not None:
            if stmt.start_point[0] - prev_stmt.end_point[0] > 1:
                emitter.newline()
        emitter.write_indent()
        _emit_node(emitter, source, stmt)
        emitter.newline()
        prev_stmt = stmt
    emitter.pop_indent()
    emitter.write_indent()
    emitter.write("}")


_SHORT_CIRCUIT_STATEMENT_TYPES: Final[frozenset[str]] = frozenset({
    "return_statement",
    "continue_statement",
    "break_statement",
    "throw_statement",
})


def _short_circuit_body(node: Node) -> Node | None:
    """Return the inner short-circuit statement if Tier 1 applies.

    Per the spec's "Short-Circuit Conditionals" section,
    Tier 1 (single-line braceless `if (x) STMT;`) applies
    only when the body is exactly one short-circuit
    statement (`return`, `continue`, `break`, `throw`). The
    body may be either bare (Tier 1 already in source) or a
    block containing exactly one short-circuit statement
    (`if (x) { return; }` — needs collapse). Returns the
    short-circuit statement node, or None when Tier 1
    doesn't apply.

    Tier 1 collapse from a source Tier 2 block is also
    inhibited when the developer authored a blank line
    inside the braces between `{` and the short-circuit
    statement, since the blank line is a deliberate visual-
    separation cue that single-line form would erase.
    """
    if node.type in _SHORT_CIRCUIT_STATEMENT_TYPES:
        return node
    if node.type == "block":
        stmts = list(node.named_children)
        if (
            len(stmts) == 1
            and stmts[0].type in _SHORT_CIRCUIT_STATEMENT_TYPES
        ):
            # Reject the collapse when the source has a blank
            # line between the opening `{` and the first
            # statement (start row diff > 1). Preserves
            # developer-authored visual separation.
            stmt = stmts[0]
            brace_row = node.start_point[0]
            if stmt.start_point[0] - brace_row > 1:
                return None
            return stmt
    return None


def _is_else_branch_if(node: Node) -> bool:
    """Return True when `node` is an if_statement serving as the
    `alternative` of a parent if_statement (i.e. an `else if`
    branch of a chain).

    Per spec "Short-Circuit Conditionals / `if`/`else` pairs
    always use braces": once any branch in an if/else chain
    has an `else`, every branch is braced — including
    intermediate `else if` branches whose own body would
    otherwise be Tier-1-eligible. This helper detects that
    chain-membership case so the caller can inhibit Tier 1
    collapse.
    """
    parent = node.parent
    if parent is None or parent.type != "if_statement":
        return False
    # Tree-sitter Node objects don't support `is` identity
    # (each accessor returns a fresh wrapper around the same
    # underlying node), so compare by `==` which the binding
    # implements as structural equality on the underlying
    # node id.
    return parent.child_by_field_name("alternative") == node


def _emit_branch_as_block(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit a branch body in same-line-brace block form.

    Used by `if_statement` (and the other control-flow
    emitters in subsequent phases) to ensure the body is in
    braced same-line-`{` form when Tier 1 collapse doesn't
    apply. If `node` is already a `block`, dispatches
    normally. Otherwise synthesizes braces around the
    statement: `{\\n<indent>STMT\\n}`.

    Per the spec's "Brace Placement / Same-Line Style" rule,
    the opening `{` sits on the same line as the preceding
    syntactic token (e.g. `if (cond) `). Per the spec's
    "`if`/`else` pairs always use braces" rule, when an
    `else` is present BOTH branches must be braced; this
    helper is the mechanism that wraps a bare-statement
    branch into block form.
    """
    if node.type == "block":
        _emit_node(emitter, source, node)
        return
    emitter.write("{")
    emitter.newline()
    emitter.push_indent()
    emitter.write_indent()
    _emit_node(emitter, source, node)
    emitter.newline()
    emitter.pop_indent()
    emitter.write_indent()
    emitter.write("}")


def _emit_if_statement(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `if (cond) { ... } [else if|else { ... }]`.

    Per the "Brace Placement / Same-Line Style" spec section,
    the opening `{` for the if-block sits on the same line as
    `if (cond)`. Per "Closing Brace Rules", `else` cuddles
    with the closing `}` of the preceding block (`} else {`
    or `} else if (...)`).

    **Tier 1 short-circuit collapse** (spec section
    "Short-Circuit Conditionals"): when the consequence is
    exactly one short-circuit statement (`return`,
    `continue`, `break`, `throw`) AND there is no
    alternative, the emitter collapses to single-line
    braceless form: `if (cond) STMT;`. This applies whether
    the source had Tier 1 form (`if (x) return;`) or Tier 2
    form (`if (x) { return; }`). Per the spec's
    "`if`/`else` pairs always use braces" rule, the
    presence of any `else` clause inhibits Tier 1.

    **Tier 2 brace synthesis**: when Tier 1 doesn't apply
    and the consequence is a bare statement (e.g.
    `if (x) y = 1;`), the emitter wraps the body via
    `_emit_branch_as_block` to produce the braced form.
    Same wrap applies to bare-statement `else` branches.

    Known limitations until wrap-priority logic lands:
        - The condition is always emitted on a single line.
          A long compound boolean condition that the
          developer authored multi-line may exceed 80
          characters; the spec's
          "Brace Placement / Exception: Multi-Line
          Conditions" rule (Allman `{` on its own line)
          will be enforced when the wrap-priority machinery
          lands.
        - The Tier-1 width check ("would the single-line
          form exceed 80 characters? → fall back to Tier 2")
          is not yet implemented; Tier 1 emits unconditionally
          when the structural conditions are met.

    Caller contract: the emitter ends mid-line at the final
    `}` (or trailing `;` of the Tier 1 body) so the caller's
    `newline()` finalizes the line.
    """
    condition = node.child_by_field_name("condition")
    consequence = node.child_by_field_name("consequence")
    alternative = node.child_by_field_name("alternative")
    if condition is None or consequence is None:
        raise NotImplementedError(
            "if_statement missing 'condition' or 'consequence' "
            "— grammar shape unexpected."
        )

    short_circuit = _short_circuit_body(consequence)
    if (
        alternative is None
        and short_circuit is not None
        and not _is_else_branch_if(node)
        and not _node_spans_multiple_rows(condition)
    ):
        # Tier 1 is structurally eligible. Measure the would-be
        # width: leading indent + `if ` + condition + ` ` +
        # short-circuit statement. If it overflows 80 chars,
        # fall through to Tier 2 (braced) per spec
        # "Short-Circuit Conditionals / Tier 2".
        start_col = emitter.column
        tier1_width = (
            start_col
            + len("if ")
            + len(_node_source_text(source, condition))
            + 1
            + len(_node_source_text(source, short_circuit))
        )
        if tier1_width <= _MAX_LINE:
            # Tier 1: `if (cond) STMT;`. The short-circuit
            # statement emitters (`return`/`continue`/`break`/
            # `throw`) write their own trailing `;`. Per the
            # spec's "`if`/`else` pairs always use braces"
            # rule, the presence of any `else` clause inhibits
            # Tier 1 — and that includes the case where THIS
            # if_statement is itself an `else if` branch of a
            # parent (the `_is_else_branch_if` check), since
            # "once any branch has an `else`, every branch is
            # braced".
            emitter.write("if ")
            _emit_node(emitter, source, condition)
            emitter.write(" ")
            _emit_node(emitter, source, short_circuit)
            return

    emitter.write("if ")
    _emit_node(emitter, source, condition)
    emitter.write(" ")
    _emit_branch_as_block(emitter, source, consequence)

    if alternative is not None:
        if alternative.type == "if_statement":
            # else-if chain: dispatch the nested if_statement;
            # its emitter writes "if (...) { ... }" starting
            # at the current column (right after "} else ").
            emitter.write(" else ")
            _emit_node(emitter, source, alternative)
        else:
            emitter.write(" else ")
            _emit_branch_as_block(emitter, source, alternative)


_MAX_LINE: Final[int] = 80

_JAVADOC_BLOCK_TOKENS: Final[tuple[str, ...]] = (
    "<p>", "<pre>", "</pre>", "<ul>", "</ul>", "<ol>", "</ol>",
    "<table>", "</table>", "<tr>", "</tr>", "<td>", "</td>",
    "<th>", "</th>",
)


def _javadoc_is_prose_line(content: str) -> bool:
    """Return True when `content` (the post-`* ` part of a javadoc
    interior line) is plain prose eligible for paragraph reflow.

    Excludes: `@tag` descriptions (their own handler runs),
    list items (`<li>`), block-level HTML openers / closers,
    `{@snippet ...}` fragments (the checkstyle ignorePattern
    excludes them from line-length checks), and CSOFF / CSON
    suppressors.
    """
    if not content:
        return False
    if content.startswith("@"):
        return False
    if content.startswith("<li>"):
        return False
    for tok in _JAVADOC_BLOCK_TOKENS:
        if content.startswith(tok) and len(content) <= len(tok) + 4:
            return False
    if content == "*/":
        return False
    if "{@snippet" in content or content.startswith('file="'):
        return False
    if content.startswith("CSOFF") or content.startswith("CSON"):
        return False
    return True


def _javadoc_reflow_words(
    words: list[str], prefix: str
) -> list[str]:
    """Greedy reflow: fill each line with as many space-separated
    words as fit under `_MAX_LINE - len(prefix)`. Returns a list of
    content strings (no prefix, no trailing newline)."""
    if not words:
        return []
    max_content = _MAX_LINE - len(prefix)
    result: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = current + " " + word
        if len(candidate) <= max_content:
            current = candidate
        else:
            result.append(current)
            current = word
    result.append(current)
    return result


def _emit_javadoc_sub_paragraph(
    emitter: Emitter, lines: list[str], prefix: str
) -> None:
    """Emit a contiguous run of plain prose lines (no `{@`/`<`
    starters) with the orphan-or-overlong reflow gate. Used by
    `_emit_javadoc_block` after splitting a paragraph at
    inline-tag / HTML-opener boundaries."""
    if not lines:
        return
    if _javadoc_needs_reflow(lines, prefix):
        words: list[str] = []
        for pl in lines:
            words.extend(pl.split())
        reflowed = _javadoc_reflow_words(words, prefix)
        for rl in reflowed:
            emitter.newline()
            emitter.write(prefix + rl)
    else:
        for pl in lines:
            emitter.newline()
            emitter.write(prefix + pl)


def _javadoc_needs_reflow(
    lines: list[str], prefix: str
) -> bool:
    """Return True when the paragraph (a list of pre-stripped
    content strings) needs reflow: any line exceeds 80 chars when
    prefixed, OR the paragraph has an orphan continuation (a short
    line whose successor's first word could fit on it).

    When False, the formatter should emit the source lines
    verbatim — leaving developer-authored linebreaks alone.
    """
    max_content = _MAX_LINE - len(prefix)
    # Any overlong line forces reflow.
    for line in lines:
        if len(line) > max_content:
            return True
    # Orphan-continuation check: any line whose successor's first
    # word would fit on it (with one space between) indicates an
    # awkward break that reflow would fix.
    for i in range(len(lines) - 1):
        next_words = lines[i + 1].split()
        if not next_words:
            continue
        first_word = next_words[0]
        if len(lines[i]) + 1 + len(first_word) <= max_content:
            return True
    return False


def _emit_javadoc_block(
    emitter: Emitter, source: bytes, node: Node, raw: str
) -> None:
    """Emit a `/** ... */` javadoc block with paragraph reflow,
    `@param` / `@return` / `@throws` continuation alignment, and
    preservation of `<pre>` blocks and `{@snippet}` directives.

    Ports the line-level text transforms from
    `fix_javadoc_reflow.py`, `fix_javadoc_inline_tags.py`, and
    `fix_javadoc_tags.py` onto a tree-sitter-identified comment
    range. Behaviors:

        - Plain prose paragraphs (consecutive `* TEXT` lines not
          starting with `@`/`<`/`{@`/`<li>`) are reflowed to fill
          lines near 80 chars when the paragraph contains either
          an awkward orphan continuation OR a line over 80 chars.
          Inline-tag-bearing prose (e.g. `{@link Foo}`) is
          reflowed under the same rule.

        - `@param NAME desc` / `@return desc` / `@throws Type desc`
          descriptions reflow with continuation lines aligned to
          the description start column (one space past `NAME` /
          `Type`, or one space past `@return`). Single-line tag
          descriptions that fit are kept on one line.

        - `<pre> ... </pre>` interior content is preserved
          verbatim — never reflowed (the spec explicitly carves
          out code examples).

        - `{@snippet ...}` directives and their continuation
          `file="..."` lines emit verbatim — the checkstyle
          `@snippet` ignorePattern grants them an 80-char
          exemption.

        - Comment delimiters (`/**`, `*/`), blank `*` separator
          lines, and standalone block HTML openers / closers
          (`<p>`, `<ul>`, etc.) emit verbatim.

    `raw` is the comment's verbatim source text (caller-provided
    to avoid re-extracting). The output is re-indented to the
    formatter's authoritative `emitter.indent_level` regardless
    of the source's leading indent.
    """
    # The caller wrote write_indent() before dispatching, so we
    # are at column = indent_level * 4. The first line of `raw`
    # is `/**` (or `/** content...`) — emit as-is. Subsequent
    # interior lines are reflowed; the closing `*/` line is
    # emitted as-is.
    indent = " " * (emitter.indent_level * 4)
    star_prefix = indent + " * "

    lines = raw.split("\n")
    if len(lines) == 1:
        # Single-line `/** ... */` form (rare in our corpus but
        # syntactically valid). Emit verbatim.
        emitter.write(lines[0])
        return

    # Strip leading whitespace and `*` from each interior line to
    # recover its content. Track per-line metadata for the
    # classifier loop.
    interior: list[str] = []
    for raw_line in lines[1:-1]:
        s = raw_line.strip()
        if s == "*":
            interior.append("")  # blank `*` separator
            continue
        if s.startswith("* "):
            interior.append(s[2:])
        elif s.startswith("*"):
            # `*foo` (unusual — no space after `*`); preserve.
            interior.append(s[1:])
        else:
            interior.append(s)
    # Closing line is `*/` or `... */`.
    closing = lines[-1].strip()

    emitter.write("/**")

    i = 0
    in_pre = False
    while i < len(interior):
        line = interior[i]

        # Inside <pre> ... </pre>: emit interior content verbatim
        # with the `* ` prefix.
        if in_pre:
            emitter.newline()
            if line == "":
                emitter.write(indent + " *")
            else:
                emitter.write(star_prefix + line)
            if "</pre>" in line:
                in_pre = False
            i += 1
            continue

        if "<pre>" in line and "</pre>" not in line:
            emitter.newline()
            emitter.write(star_prefix + line)
            in_pre = True
            i += 1
            continue

        # Blank line (paragraph separator): emit `*` and continue.
        if line == "":
            emitter.newline()
            emitter.write(indent + " *")
            i += 1
            continue

        # `@param NAME desc` / `@throws Type desc` — capture name +
        # description, then collect continuation lines (indented
        # past `* `, signaled by content starting with at least one
        # leading space because we stripped only `* `).
        tag_match = _javadoc_match_tag(line)
        if tag_match is not None:
            tag_prefix, first_desc = tag_match
            # Collect each description LINE (stripped of its
            # leading continuation whitespace). Track lines
            # separately so we can decide whether to reflow.
            desc_lines: list[str] = []
            if first_desc:
                desc_lines.append(first_desc)
            j = i + 1
            while j < len(interior):
                nxt = interior[j]
                if not nxt or not nxt[0].isspace():
                    break
                desc_lines.append(nxt.strip())
                j += 1
            cont_prefix = star_prefix + " " * len(tag_prefix)
            full_tag_col = len(star_prefix) + len(tag_prefix)
            # `@param NAME` with no description body — emit the
            # tag prefix alone (stripped of trailing space) and
            # advance.
            if not desc_lines:
                emitter.newline()
                emitter.write(star_prefix + tag_prefix.rstrip())
                i = j
                continue
            # Decide whether to reflow. First-line max accounts
            # for the `@tag NAME ` prefix; subsequent lines use
            # the continuation prefix. Reflow if any line
            # overflows OR there is an orphan continuation.
            needs = False
            if len(desc_lines) == 1:
                # Single line — only reflow if overlong.
                if (
                    full_tag_col + len(desc_lines[0])
                    > _MAX_LINE
                ):
                    needs = True
            else:
                # First-line ceiling = MAX - full_tag_col.
                if (
                    full_tag_col + len(desc_lines[0])
                    > _MAX_LINE
                ):
                    needs = True
                else:
                    # Continuation lines under their narrower
                    # max; orphan check uses the same width as
                    # the first line for the first transition.
                    cont_max = _MAX_LINE - len(cont_prefix)
                    for k in range(1, len(desc_lines)):
                        if len(desc_lines[k]) > cont_max:
                            needs = True
                            break
                    if not needs:
                        # Orphan check across each pair.
                        # Line 0 uses full_tag_col, others use
                        # cont_prefix.
                        for k in range(len(desc_lines) - 1):
                            this_len = (
                                full_tag_col
                                + len(desc_lines[k])
                                if k == 0
                                else len(cont_prefix)
                                + len(desc_lines[k])
                            )
                            next_words = desc_lines[k + 1].split()
                            if not next_words:
                                continue
                            first_word = next_words[0]
                            cap = (
                                _MAX_LINE
                                if k == 0
                                else _MAX_LINE
                            )
                            if (
                                this_len + 1 + len(first_word)
                                <= cap
                            ):
                                needs = True
                                break
            if not needs:
                # Emit original lines verbatim.
                emitter.newline()
                emitter.write(
                    star_prefix + tag_prefix + desc_lines[0]
                    if desc_lines
                    else star_prefix + tag_prefix.rstrip()
                )
                for k in range(1, len(desc_lines)):
                    emitter.newline()
                    emitter.write(cont_prefix + desc_lines[k])
                i = j
                continue
            # Reflow: flatten to words and refill.
            desc_words: list[str] = []
            for d in desc_lines:
                desc_words.extend(d.split())
            first_max = _MAX_LINE - full_tag_col
            line_words: list[str] = []
            current_len = 0
            wi = 0
            while wi < len(desc_words):
                w = desc_words[wi]
                projected = (
                    current_len + (1 if line_words else 0) + len(w)
                )
                if projected <= first_max:
                    line_words.append(w)
                    current_len = projected
                    wi += 1
                else:
                    break
            emitter.newline()
            emitter.write(
                star_prefix + tag_prefix + " ".join(line_words)
            )
            cont_text = _javadoc_reflow_words(
                desc_words[wi:], cont_prefix
            )
            for cont in cont_text:
                emitter.newline()
                emitter.write(cont_prefix + cont)
            i = j
            continue

        # Prose paragraph: collect consecutive prose lines (not
        # blank, not starting with `@`, no tag continuation
        # whitespace, not standalone block HTML).
        if not _javadoc_is_prose_line(line):
            # Block tag standalone (e.g. `<p>`, `<ul>`) — emit
            # verbatim and continue.
            emitter.newline()
            emitter.write(star_prefix + line)
            i += 1
            continue

        para_lines = [line]
        j = i + 1
        while j < len(interior):
            nxt = interior[j]
            if nxt == "":
                break
            if not _javadoc_is_prose_line(nxt):
                break
            if nxt[0].isspace():
                break
            para_lines.append(nxt)
            j += 1
        # Reflow decision mirrors the two-script legacy pipeline:
        #
        #   - Lines that START with `{@`/`<` (inline tags or HTML
        #     openers) are paragraph BOUNDARIES — `fix_javadoc_-
        #     reflow.py` excluded them from prose paragraphs.
        #     They emit as singletons (no reflow against
        #     neighbors) UNLESS some line in the surrounding
        #     paragraph overflows 80 chars.
        #   - If ANY line overflows, fall back to the
        #     `fix_javadoc_inline_tags.py` behavior: reflow the
        #     whole paragraph including `{@`/`<` lines.
        #   - Otherwise split at `{@`/`<` lines into sub-
        #     paragraphs; each sub-paragraph gets the orphan-
        #     or-overlong gate independently.
        max_content = _MAX_LINE - len(star_prefix)
        any_overlong = any(
            len(pl) > max_content for pl in para_lines
        )
        if any_overlong:
            # Combine and reflow everything.
            para_words: list[str] = []
            for pl in para_lines:
                para_words.extend(pl.split())
            reflowed = _javadoc_reflow_words(
                para_words, star_prefix
            )
            for rl in reflowed:
                emitter.newline()
                emitter.write(star_prefix + rl)
            i = j
            continue
        # Split at `{@`/`<` boundaries and process each sub-
        # paragraph independently.
        sub: list[str] = []
        for pl in para_lines:
            if pl.startswith("{@") or pl.startswith("<"):
                # Flush any accumulated sub-paragraph first.
                if sub:
                    _emit_javadoc_sub_paragraph(
                        emitter, sub, star_prefix
                    )
                    sub = []
                emitter.newline()
                emitter.write(star_prefix + pl)
            else:
                sub.append(pl)
        if sub:
            _emit_javadoc_sub_paragraph(
                emitter, sub, star_prefix
            )
        i = j

    # Closing `*/` line.
    emitter.newline()
    emitter.write(indent + " " + closing)


def _javadoc_match_tag(content: str) -> tuple[str, str] | None:
    """If `content` is a `@param NAME` / `@throws Type` / `@return`
    tag line, return `(prefix, first_description_segment)` where
    `prefix` is the part before the description (with its trailing
    space) and `first_description_segment` is the rest of the same
    line. Return None for non-tag lines.

    Other tags (`@see`, `@deprecated`, `@since`, etc.) currently
    return None — they are emitted as plain prose by the caller.
    Adding handlers for those tags lands in a follow-up.
    """
    if content.startswith("@return"):
        # `@return` has no parameter name; description starts
        # right after.
        rest = content[len("@return") :]
        if not rest or rest[0] != " ":
            return None
        return ("@return ", rest[1:])
    for tag in ("@param", "@throws"):
        if not content.startswith(tag + " "):
            continue
        rest = content[len(tag) + 1 :]
        # Capture the name / type up to the next whitespace.
        space = rest.find(" ")
        if space < 0:
            # `@param NAME` with no description (rare); treat
            # whole thing as the prefix with an empty description.
            return (tag + " " + rest + " ", "")
        name = rest[:space]
        desc_start = space + 1
        # Skip any extra whitespace between name and description.
        while desc_start < len(rest) and rest[desc_start] == " ":
            desc_start += 1
        return (tag + " " + name + " ", rest[desc_start:])
    return None


def _emit_comment(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit a `line_comment` or `block_comment`.

    Single-line `//` comments and single-line `/* */` block
    comments emit verbatim. Multi-line block comments dispatch
    based on whether they are javadoc (`/**` opener):

        - Javadoc — reflow paragraphs and `@tag` descriptions
          to fill lines near 80 chars per the Javadoc Reflow
          spec section (and the existing `fix_javadoc_*`
          script-level behaviors they replace). Handled by
          `_emit_javadoc_block`.
        - Non-javadoc multi-line `/* */` — emit verbatim,
          preserving the developer-authored interior indent.

    Side-comment attachment (end-of-line `//` comment that
    syntactically belongs to the preceding line, e.g.
    `int x = 1;  // explanation`) is partially handled at the
    block boundary by `_emit_block` (Phase 3a). Other side-
    comment positions emit on their own line below the code
    they were meant to annotate — a known drift documented in
    the calibration-gate notes.
    """
    text = _node_source_text(source, node)
    if "\n" not in text:
        emitter.write(text)
        return
    if text.startswith("/**"):
        _emit_javadoc_block(emitter, source, node, text)
        return
    emitter.write_raw_lines(text)


def _emit_marker_annotation(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `@IDENTIFIER` (annotation with no arguments).

    Grammar field: `name` (identifier).
    """
    name = node.child_by_field_name("name")
    if name is None:
        raise NotImplementedError(
            "marker_annotation missing 'name' — grammar shape "
            "unexpected."
        )
    emitter.write("@")
    _emit_node(emitter, source, name)


def _emit_annotation(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `@IDENTIFIER(ARGS)`.

    Grammar fields: `name` (identifier) and `arguments`
    (annotation_argument_list). No space between the name
    and the argument-list parens — same convention as method
    invocations.

    Phase 2n emits single-line annotation argument lists
    only; the priority-1-4 wrap pattern from the spec's
    "Annotations with arguments" subsection (A3) lands with
    the wrap-priority phase.
    """
    name = node.child_by_field_name("name")
    arguments = node.child_by_field_name("arguments")
    if name is None or arguments is None:
        raise NotImplementedError(
            "annotation missing 'name' or 'arguments' — "
            "grammar shape unexpected."
        )
    emitter.write("@")
    _emit_node(emitter, source, name)
    _emit_node(emitter, source, arguments)


def _emit_annotation_argument_list(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `(arg1, arg2, ...)` for an annotation.

    Same shape as `_emit_argument_list` — comma-space
    separator. Each argument can be either a plain
    expression (single-value form like
    `@SuppressWarnings("unchecked")`) or an
    `element_value_pair` (named form like
    `@Schedule(hour = "12")`).
    """
    args = list(node.named_children)
    emitter.write("(")
    for index, arg in enumerate(args):
        if index > 0:
            emitter.write(", ")
        _emit_node(emitter, source, arg)
    emitter.write(")")


def _emit_element_value_pair(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `KEY = VALUE` for a named annotation argument.

    Per "Whitespace and Operator Spacing" (assignment-
    operator row), single space on each side of `=`.
    """
    key = node.child_by_field_name("key")
    value = node.child_by_field_name("value")
    if key is None or value is None:
        raise NotImplementedError(
            "element_value_pair missing 'key' or 'value' — "
            "grammar shape unexpected."
        )
    _emit_node(emitter, source, key)
    emitter.write(" = ")
    _emit_node(emitter, source, value)


def _emit_ternary_expression(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `COND ? CONSEQUENCE : ALTERNATIVE`.

    Phase 2m implements Tier 1 (single-line) only per the
    spec's "Line Continuation / Ternary Operator" section.
    The remaining tiers (Tier 2: break before `?` keeping
    `? value : value` together; Tier 3: break before both
    `?` and `:`, with `:` aligned under `?`; Tier 4:
    parenthesize long value expressions) land with the
    wrap-priority phase.

    Per the "Whitespace and Operator Spacing" spec section,
    `?` and `:` each get single space on each side.

    The spec also requires nested ternaries to be wrapped in
    explicit grouping parentheses
    ("Miscellaneous Clarifications / Nested ternary").
    Phase 2m doesn't check for nesting; if the source author
    wrote a nested ternary without parens, the formatter
    re-emits the same shape — the spec violation is the
    developer's, not the formatter's invention.
    """
    cond = node.child_by_field_name("condition")
    consequence = node.child_by_field_name("consequence")
    alternative = node.child_by_field_name("alternative")
    if cond is None or consequence is None or alternative is None:
        raise NotImplementedError(
            "ternary_expression missing 'condition', "
            "'consequence', or 'alternative' — grammar shape "
            "unexpected."
        )
    _emit_node(emitter, source, cond)
    emitter.write(" ? ")
    _emit_node(emitter, source, consequence)
    emitter.write(" : ")
    _emit_node(emitter, source, alternative)


def _emit_object_creation_expression(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `new TYPE(ARGS)` or `new TYPE(ARGS) { BODY }`.

    Single space between the `new` keyword and the type, no
    space between the type and the argument list. Grammar
    fields: `type` (may be `type_identifier`, `generic_type`,
    or `scoped_type_identifier`) and `arguments`
    (`argument_list`).

    Anonymous class bodies are exposed as an optional
    `class_body` named child (no field name). Per spec C8
    ("Anonymous Classes"), the opening `{` stays SAME-LINE
    with `new TYPE(ARGS)` (anonymous classes are expressions,
    not top-level declarations, so they don't take Allman
    braces). The body content uses the standard class-body
    member emission via `_emit_class_body_members`. The
    closing `}` aligns with the surrounding statement's
    indent (current emitter indent level).

    Refuses array creation (`new int[5]`) and explicit type
    arguments on the constructor call (`new <T>Foo(...)`) —
    those land with subsequent phases.
    """
    if node.child_by_field_name("type_arguments") is not None:
        raise NotImplementedError(
            "object_creation_expression with explicit type "
            "arguments (`new <T>Foo(...)`) is not yet supported."
        )
    type_node = node.child_by_field_name("type")
    arguments = node.child_by_field_name("arguments")
    if type_node is None or arguments is None:
        raise NotImplementedError(
            "object_creation_expression missing 'type' or "
            "'arguments' — grammar shape unexpected."
        )
    class_body: Node | None = None
    for child in node.named_children:
        if child.type == "class_body":
            class_body = child
            break

    emitter.write("new ")
    _emit_node(emitter, source, type_node)
    _emit_node(emitter, source, arguments)

    if class_body is not None:
        # Per spec C8: same-line opening brace separated from
        # `)` by a single space. The body is structurally a
        # class body — same indent/newline rules as
        # `_emit_class_body_members` for top-level classes.
        emitter.write(" {")
        emitter.newline()
        _emit_class_body_members(emitter, source, class_body)
        emitter.write_indent()
        emitter.write("}")


def _emit_class_literal(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `TYPE.class` — a class literal expression.

    Grammar: a class_literal node contains the type child
    (type_identifier, generic_type, scoped_type_identifier,
    primitive_type, etc.) followed by anonymous `.` and
    `class` tokens. Emit type, then `.class`.
    """
    type_node = None
    for c in node.named_children:
        type_node = c
        break
    if type_node is None:
        raise NotImplementedError(
            "class_literal with no type child — grammar shape "
            "unexpected."
        )
    _emit_node(emitter, source, type_node)
    emitter.write(".class")


def _emit_array_initializer(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `{ a, b, c }` for an array initializer (or annotation
    value array). Per spec A4 ("Whitespace and Operator Spacing"
    / inside braces): single space after `{`, single space
    before `}` for non-empty initializers; `{}` for empty.

    Source-preservation kicks in when the source has the
    initializer spanning multiple rows — the formatter
    preserves the developer's layout. Single-row source
    re-emits with the normalized spacing.
    """
    if _node_spans_multiple_rows(node):
        emitter.write_raw_lines(_node_source_text(source, node))
        return
    elements = [c for c in node.named_children]
    if not elements:
        emitter.write("{}")
        return
    emitter.write("{ ")
    for index, e in enumerate(elements):
        if index > 0:
            emitter.write(", ")
        _emit_node(emitter, source, e)
    emitter.write(" }")


def _emit_array_creation_expression(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `new TYPE[N]` or `new TYPE[]{ init }`.

    Source-preservation for multi-row forms; for single-row
    forms, walk children and emit each piece. Grammar exposes
    the type as a named child and the dimensions as
    `dimensions_expr` (`[5]`) or `dimensions` (`[]`) nodes,
    optionally followed by an `array_initializer`.
    """
    if _node_spans_multiple_rows(node):
        emitter.write_raw_lines(_node_source_text(source, node))
        return
    emitter.write("new ")
    for child in node.named_children:
        _emit_node(emitter, source, child)


def _emit_array_access(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `ARRAY[INDEX]`. Grammar: `array` field for the
    receiver and `index` field for the index expression.
    """
    array = node.child_by_field_name("array")
    index = node.child_by_field_name("index")
    if array is None or index is None:
        raise NotImplementedError(
            "array_access missing 'array' or 'index' — grammar "
            "shape unexpected."
        )
    _emit_node(emitter, source, array)
    emitter.write("[")
    _emit_node(emitter, source, index)
    emitter.write("]")


def _emit_dimensions(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `[]` for an array-type dimension marker.

    The `dimensions` node carries the array's bracket pairs.
    Multi-dimensional arrays (`int[][][]`) have multiple
    bracket pairs but tree-sitter exposes them inside a
    single `dimensions` node — emit source verbatim to
    handle all variants.
    """
    emitter.write(_node_source_text(source, node))


def _emit_dimensions_expr(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `[EXPR]` for an array-creation dimension with a
    size expression. Grammar: anonymous `[` + expression + `]`.
    """
    emitter.write("[")
    for c in node.named_children:
        _emit_node(emitter, source, c)
    emitter.write("]")


def _emit_switch_expression(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `switch (cond) { CASES }` per spec B2.

    Tree-sitter-java exposes both the statement form and the
    expression form (used as RHS of an assignment, `return`
    operand, etc.) under the single `switch_expression` node
    type. The brace is Allman-style for the body since cases
    flow on multiple lines. Cases are emitted by `_emit_-
    switch_block` (the `switch_block` child).

    Caller positions the emitter at the column where `switch`
    begins. For switch-as-expression contexts (e.g. after `=`
    or `return`), the caller's trailing `;` / `,` follows the
    closing `}`.

    Source-preservation is the fallback for the body's
    internal layout: case bodies that wrap (multi-statement
    colon form, block bodies after `->`, etc.) emit
    via `_emit_switch_block` which delegates to per-rule
    emitters that fall back to source-text emission when
    they can't dispatch cleanly.
    """
    cond = None
    block = None
    for c in node.named_children:
        if c.type == "parenthesized_expression":
            cond = c
        elif c.type == "switch_block":
            block = c
    if cond is None or block is None:
        raise NotImplementedError(
            "switch_expression missing condition or block — "
            "grammar shape unexpected."
        )
    emitter.write("switch ")
    _emit_node(emitter, source, cond)
    emitter.newline()
    emitter.write_indent()
    _emit_node(emitter, source, block)


def _emit_switch_block(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `{ CASES }` for a switch's case body.

    Caller positions the emitter at the column where `{`
    starts. Case rules (`switch_rule` or `switch_block_-
    statement_group`) are emitted at indent_level + 1.
    """
    cases = [
        c for c in node.named_children
        if c.type in (
            "switch_rule", "switch_block_statement_group"
        )
    ]
    emitter.write("{")
    emitter.newline()
    if cases:
        emitter.push_indent()
        prev: Node | None = None
        for case in cases:
            if prev is not None:
                if case.start_point[0] - prev.end_point[0] > 1:
                    emitter.newline()
            emitter.write_indent()
            _emit_node(emitter, source, case)
            emitter.newline()
            prev = case
        emitter.pop_indent()
    emitter.write_indent()
    emitter.write("}")


def _emit_switch_rule(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `LABEL -> body[;]` (arrow form of a switch case).

    Per spec B2: single space around `->`. The body is one or
    more statements. Source-preservation for multi-row source.
    """
    if _node_spans_multiple_rows(node):
        emitter.write_raw_lines(_node_source_text(source, node))
        return
    label = None
    body_children: list[Node] = []
    for c in node.named_children:
        if c.type == "switch_label":
            label = c
        else:
            body_children.append(c)
    if label is None:
        raise NotImplementedError(
            "switch_rule missing label — grammar shape unexpected."
        )
    _emit_node(emitter, source, label)
    emitter.write(" -> ")
    for body in body_children:
        _emit_node(emitter, source, body)


def _emit_switch_block_statement_group(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `LABEL:\\n    stmt;\\n    stmt;` (colon form).

    Multiple labels can stack (fall-through):

        case 1:
        case 2:
            doSomething();

    Per spec B2, statements inside a case body indent +4 from
    the case label. Labels and statements are emitted via
    dispatch so each lands at the right authoritative indent
    column.

    Grammar shape: one or more `switch_label` named children
    (each followed by an anonymous `:` token), then any
    number of statement named children.
    """
    labels: list[Node] = []
    stmts: list[Node] = []
    for c in node.named_children:
        if c.type == "switch_label":
            labels.append(c)
        else:
            stmts.append(c)
    # Emit each label on its own line at the caller's indent
    # (the caller wrote `write_indent()` already, so the first
    # label emits on the current line; subsequent labels get
    # newline + write_indent).
    for index, label in enumerate(labels):
        if index > 0:
            emitter.newline()
            emitter.write_indent()
        _emit_node(emitter, source, label)
        emitter.write(":")
    # Statements indent +4 from the case label.
    if stmts:
        emitter.push_indent()
        prev: Node | None = None
        for s in stmts:
            emitter.newline()
            if prev is not None:
                if s.start_point[0] - prev.end_point[0] > 1:
                    emitter.newline()
            emitter.write_indent()
            _emit_node(emitter, source, s)
            prev = s
        emitter.pop_indent()


def _emit_switch_label(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `case VALUES` or `default`."""
    children = list(node.named_children)
    if not children:
        # `default` — no values; emit verbatim.
        emitter.write(_node_source_text(source, node))
        return
    emitter.write("case ")
    for index, c in enumerate(children):
        if index > 0:
            emitter.write(", ")
        _emit_node(emitter, source, c)


def _emit_yield_statement(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `yield VALUE;` (Java 14+ switch-expression yield)."""
    children = list(node.named_children)
    if not children:
        emitter.write("yield;")
        return
    emitter.write("yield ")
    for c in children:
        _emit_node(emitter, source, c)
    emitter.write(";")


def _emit_record_declaration(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit a Java 16+ record declaration:
    `[modifiers] record NAME(components) [implements ...] { body }`.

    The body's opening `{` follows the Allman rule (records
    are type declarations like classes). The components are
    exposed as `formal_parameters`; super_interfaces and
    type_parameters apply the same way as for classes.
    """
    modifiers_node: Node | None = None
    type_parameters_node: Node | None = None
    super_interfaces_node: Node | None = None
    params_node: Node | None = None
    for c in node.named_children:
        if c.type == "modifiers":
            modifiers_node = c
        elif c.type == "type_parameters":
            type_parameters_node = c
        elif c.type == "super_interfaces":
            super_interfaces_node = c
        elif c.type == "formal_parameters":
            params_node = c
    name = node.child_by_field_name("name")
    body = node.child_by_field_name("body")
    if name is None or body is None or params_node is None:
        raise NotImplementedError(
            "record_declaration missing required children — "
            "grammar shape unexpected."
        )
    if modifiers_node is not None:
        _emit_node(emitter, source, modifiers_node)
    emitter.write("record ")
    _emit_node(emitter, source, name)
    if type_parameters_node is not None:
        _emit_node(emitter, source, type_parameters_node)
    _emit_node(emitter, source, params_node)
    if super_interfaces_node is not None:
        emitter.write(" ")
        _emit_node(emitter, source, super_interfaces_node)
    emitter.newline()
    emitter.write_indent()
    emitter.write("{")
    emitter.newline()
    _emit_class_body_members(emitter, source, body)
    emitter.write_indent()
    emitter.write("}")


def _emit_compact_constructor_declaration(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit a record's compact constructor:
    `[modifiers] RECORD_NAME { body }`.

    No parameter list (the record's component list IS the
    parameter list). Per spec B9, compact constructors use
    Allman brace placement.
    """
    modifiers_node: Node | None = None
    for c in node.named_children:
        if c.type == "modifiers":
            modifiers_node = c
            break
    name = node.child_by_field_name("name")
    body = node.child_by_field_name("body")
    if name is None or body is None:
        raise NotImplementedError(
            "compact_constructor_declaration missing required "
            "children — grammar shape unexpected."
        )
    if modifiers_node is not None:
        _emit_node(emitter, source, modifiers_node)
    _emit_node(emitter, source, name)
    emitter.newline()
    emitter.write_indent()
    emitter.write("{")
    emitter.newline()
    statements = list(body.named_children)
    if statements:
        emitter.push_indent()
        prev: Node | None = None
        for stmt in statements:
            if prev is not None:
                if stmt.start_point[0] - prev.end_point[0] > 1:
                    emitter.newline()
            emitter.write_indent()
            _emit_node(emitter, source, stmt)
            emitter.newline()
            prev = stmt
        emitter.pop_indent()
    emitter.write_indent()
    emitter.write("}")


def _emit_synchronized_statement(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `synchronized (EXPR) { BODY }`. Same-line brace
    when the condition fits on one line; Allman when the
    condition spans multiple source rows.
    """
    body = node.child_by_field_name("body")
    # Find the parenthesized_expression child (condition).
    cond = None
    for c in node.named_children:
        if c.type == "parenthesized_expression":
            cond = c
            break
    if cond is None or body is None:
        raise NotImplementedError(
            "synchronized_statement missing condition or body — "
            "grammar shape unexpected."
        )
    emitter.write("synchronized ")
    if _node_spans_multiple_rows(cond):
        emitter.write_raw_lines(_node_source_text(source, cond))
        emitter.newline()
        emitter.write_indent()
        _emit_node(emitter, source, body)
    else:
        _emit_node(emitter, source, cond)
        emitter.write(" ")
        _emit_node(emitter, source, body)


def _emit_explicit_constructor_invocation(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `this(ARGS);` / `super(ARGS);` — used as the first
    statement in a constructor body to delegate to another
    constructor in the same class or the superclass.

    Grammar exposes either a `this` or `super` keyword as a
    named child followed by an `argument_list`. The trailing
    `;` is part of the node's source span (emitted by us
    since the constructor body's statement loop expects each
    statement to write its own terminator? — actually let me
    check). Looking at the existing statement handling, the
    block emitter iterates named children and adds newline
    after each. The statement nodes (return, throw, etc.)
    write their own `;`. We do the same here.
    """
    keyword = None
    args = None
    type_arguments = None
    # Inspect children: this/super keyword (named), optional
    # `type_arguments` (for `<T>this(...)` rare form), argument_list.
    for c in node.named_children:
        if c.type in ("this", "super"):
            keyword = c
        elif c.type == "argument_list":
            args = c
        elif c.type == "type_arguments":
            type_arguments = c
    if keyword is None or args is None:
        # Grammar may also expose a receiver chain (`obj.super(...)`
        # for inner-class super calls). Not yet supported.
        raise NotImplementedError(
            "explicit_constructor_invocation with unexpected "
            "shape — extended forms not yet supported."
        )
    if type_arguments is not None:
        _emit_node(emitter, source, type_arguments)
    emitter.write(keyword.type)
    _emit_node(emitter, source, args)
    emitter.write(";")


def _emit_generic_type(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `TYPE<TYPE_ARGS>` with no space between the two.

    Grammar: a `generic_type` node has a `type_identifier`
    (or `scoped_type_identifier`) child followed by a
    `type_arguments` child. Per the "Whitespace and Operator
    Spacing" spec section, no space inside or around `<>`.
    """
    for child in node.children:
        if child.is_named:
            _emit_node(emitter, source, child)


def _emit_type_arguments(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `<TYPE, TYPE, ...>` or the diamond `<>`.

    Comma-space separator between type arguments per the
    "Whitespace and Operator Spacing" spec section's
    "After commas" row.
    """
    types = [c for c in node.children if c.is_named]
    emitter.write("<")
    for index, t in enumerate(types):
        if index > 0:
            emitter.write(", ")
        _emit_node(emitter, source, t)
    emitter.write(">")


def _emit_throw_statement(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `throw EXPR;`.

    Single space between `throw` and the thrown expression.
    The expression is the single named child of the
    `throw_statement` node.
    """
    expr: Node | None = None
    for child in node.children:
        if child.is_named:
            expr = child
            break
    if expr is None:
        raise NotImplementedError(
            "throw_statement missing thrown expression — "
            "grammar shape unexpected."
        )
    emitter.write("throw ")
    _emit_node(emitter, source, expr)
    emitter.write(";")


def _emit_break_statement(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `break;` or `break LABEL;`.

    Per the spec's "Labels and Labeled break/continue" section,
    a single space sits between the keyword and the label name.
    """
    label: Node | None = None
    for child in node.children:
        if child.is_named:
            label = child
            break
    if label is None:
        emitter.write("break;")
    else:
        emitter.write("break ")
        _emit_node(emitter, source, label)
        emitter.write(";")


def _emit_continue_statement(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `continue;` or `continue LABEL;`.

    Same shape as `_emit_break_statement` — single space
    between the keyword and the label name per the
    "Labels and Labeled break/continue" spec section.
    """
    label: Node | None = None
    for child in node.children:
        if child.is_named:
            label = child
            break
    if label is None:
        emitter.write("continue;")
    else:
        emitter.write("continue ")
        _emit_node(emitter, source, label)
        emitter.write(";")


def _emit_labeled_statement(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `LABEL:` on its own line, then the labeled statement.

    Per the spec's "Labels and Labeled break/continue" section,
    the label appears on its own line at the column of the
    labeled statement. The grammar exposes two named children:
    the label identifier (first), and the statement being
    labeled (second — typically a `for_statement`,
    `while_statement`, `do_statement`, or `block`).

    Caller contract: enter with `write_indent` already applied
    (the block-loop convention). The emitter writes
    `"LABEL:"`, finalizes the line, re-applies `write_indent`,
    and dispatches the inner statement. The inner statement
    ends mid-line (per the usual emitter convention) and the
    caller's `newline()` finalizes it.
    """
    named = [c for c in node.children if c.is_named]
    if len(named) < 2:
        raise NotImplementedError(
            "labeled_statement missing label or inner "
            "statement — grammar shape unexpected."
        )
    label_node, inner_node = named[0], named[1]
    _emit_node(emitter, source, label_node)
    emitter.write(":")
    emitter.newline()
    emitter.write_indent()
    _emit_node(emitter, source, inner_node)


def _emit_try_statement(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `try { ... } catch (...) { ... } finally { ... }`.

    Per the "Closing Brace Rules" spec section, `catch` and
    `finally` cuddle with the closing `}` of the preceding
    block: `} catch (...) {`, `} finally {`. Multiple
    `catch_clause` children are emitted in order. The optional
    `finally_clause` follows any catches.

    Note: try-with-resources is a separate
    `try_with_resources_statement` node type in the grammar
    (not a `try_statement` with a `resources` field), so it
    naturally refuses via the dispatcher's "no emitter
    registered" path. The "Try-with-resources" spec section
    will get its own emitter in a later phase.
    """
    body = node.child_by_field_name("body")
    if body is None or body.type != "block":
        raise NotImplementedError(
            "try_statement missing or non-block body — grammar "
            "shape unexpected."
        )

    emitter.write("try ")
    _emit_node(emitter, source, body)
    for child in node.children:
        if child.type in ("catch_clause", "finally_clause"):
            emitter.write(" ")
            _emit_node(emitter, source, child)


def _emit_catch_clause(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `catch (PARAM) { ... }`.

    Same-line-brace form via `_emit_block`. The single
    `catch_formal_parameter` child is dispatched directly
    (carrying any multi-catch `|`-separated types via
    `_emit_catch_type`).
    """
    body = node.child_by_field_name("body")
    if body is None or body.type != "block":
        raise NotImplementedError(
            "catch_clause missing or non-block body — grammar "
            "shape unexpected."
        )
    cfp: Node | None = None
    for child in node.named_children:
        if child.type == "catch_formal_parameter":
            cfp = child
            break
    if cfp is None:
        raise NotImplementedError(
            "catch_clause missing catch_formal_parameter — "
            "grammar shape unexpected."
        )
    emitter.write("catch (")
    _emit_node(emitter, source, cfp)
    emitter.write(") ")
    _emit_node(emitter, source, body)


def _emit_catch_formal_parameter(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `TYPE [| TYPE]... NAME`.

    The grammar exposes `catch_type` (which itself handles the
    `|`-separated multi-catch list) plus the `name` field.
    Refuses modifiers / annotations on the parameter (those
    land with the annotation phase).
    """
    for child in node.named_children:
        if child.type == "modifiers":
            raise NotImplementedError(
                "catch_formal_parameter with modifiers or "
                "annotations is not yet supported."
            )
    catch_type: Node | None = None
    for child in node.named_children:
        if child.type == "catch_type":
            catch_type = child
            break
    name_node = node.child_by_field_name("name")
    if catch_type is None or name_node is None:
        raise NotImplementedError(
            "catch_formal_parameter missing catch_type or "
            "name — grammar shape unexpected."
        )
    _emit_node(emitter, source, catch_type)
    emitter.write(" ")
    _emit_node(emitter, source, name_node)


def _emit_catch_type(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `TYPE` or `TYPE | TYPE | ...` for multi-catch.

    Per the spec's "Multi-catch" section, the `|` separator
    gets a single space on each side. Single-line form only
    for now; the priority 2 / 3 two-line / one-per-line
    wrapping forms from that section land with the wrap-
    priority phase.
    """
    types = [c for c in node.children if c.is_named]
    for index, t in enumerate(types):
        if index > 0:
            emitter.write(" | ")
        _emit_node(emitter, source, t)


def _emit_finally_clause(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `finally { ... }`.

    The `block` child is not exposed via a field name; locate
    it by type iteration.
    """
    body: Node | None = None
    for child in node.named_children:
        if child.type == "block":
            body = child
            break
    if body is None:
        raise NotImplementedError(
            "finally_clause missing block body — grammar shape "
            "unexpected."
        )
    emitter.write("finally ")
    _emit_node(emitter, source, body)


def _emit_for_statement(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `for (init; cond; update) { ... }`.

    Per the "Brace Placement / Same-Line Style" spec section,
    the opening `{` for the for-block sits on the same line as
    `for (...)`. Per the "Whitespace and Operator Spacing"
    spec row "After semicolons in for headers: Exactly one
    space", each semicolon separator is followed by exactly
    one space IF the following component is non-empty;
    standalone `for (;;)` (no init / condition / update) emits
    with no interior spaces.

    Grammar fields: optional `init` (either a
    `local_variable_declaration` which carries its own
    trailing `;`, or a bare expression), optional `condition`,
    optional `update`, required `body`.

    Refuses brace-less bodies — those depend on the
    short-circuit-conditionals rules.
    """
    body = node.child_by_field_name("body")
    if body is None or body.type != "block":
        raise NotImplementedError(
            "for_statement with brace-less body is not yet "
            "supported; the short-circuit-conditionals phase "
            "will handle the brace-less form."
        )

    # tree-sitter-java surfaces comma-separated init or update
    # expressions as multiple children sharing the same field
    # name. `child_by_field_name(...)` would return only the
    # first, which would silently drop the others. Refuse the
    # multi-form for now — proper multi-init/multi-update
    # support lands with the wrap-priority phase that has the
    # column-aware logic for long headers.
    init_count = 0
    update_count = 0
    for index in range(len(node.children)):
        fn = node.field_name_for_child(index)
        if fn == "init":
            init_count += 1
        elif fn == "update":
            update_count += 1
    if init_count > 1:
        raise NotImplementedError(
            "for_statement with comma-separated init expressions "
            f"({init_count} of them, e.g. `for (i = 0, j = 0; ...`) "
            "is not yet supported; the multi-init form lands with "
            "the wrap-priority phase."
        )
    if update_count > 1:
        raise NotImplementedError(
            "for_statement with comma-separated update expressions "
            f"({update_count} of them, e.g. `for (...; ...; i++, j++)`) "
            "is not yet supported; the multi-update form lands "
            "with the wrap-priority phase."
        )

    init = node.child_by_field_name("init")
    condition = node.child_by_field_name("condition")
    update = node.child_by_field_name("update")

    # Per spec "Brace Placement / Exception: Multi-Line
    # Conditions" — when the for-header spans multiple source
    # rows the body's opening `{` switches to Allman. Detect
    # via body.start_row vs node.start_row; emit the verbatim
    # header text in that case to preserve developer-authored
    # line breaks (paren-aligned semicolon-separated parts).
    if body.start_point[0] != node.start_point[0]:
        header_text = source[
            node.start_byte : body.start_byte
        ].decode("utf-8").rstrip()
        emitter.write_raw_lines(header_text)
        emitter.newline()
        emitter.write_indent()
        _emit_node(emitter, source, body)
        return

    emitter.write("for (")
    # `local_variable_declaration` includes its own trailing
    # `;`; bare-expression and missing-init paths need a
    # manual `;`.
    if init is None:
        emitter.write(";")
    elif init.type == "local_variable_declaration":
        _emit_node(emitter, source, init)
    else:
        _emit_node(emitter, source, init)
        emitter.write(";")

    if condition is not None:
        emitter.write(" ")
        _emit_node(emitter, source, condition)
    emitter.write(";")

    if update is not None:
        emitter.write(" ")
        _emit_node(emitter, source, update)
    emitter.write(") ")
    _emit_node(emitter, source, body)


def _emit_enhanced_for_statement(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `for (TYPE NAME : VALUE) { ... }` (for-each form).

    Grammar fields: `type`, `name`, `value`, `body`. The `:`
    in the for-each header gets a single space on each side
    per "Whitespace and Operator Spacing" — same convention
    as binary operators and as the for-statement header's `;`
    separator.

    Refuses brace-less bodies.
    """
    body = node.child_by_field_name("body")
    if body is None or body.type != "block":
        raise NotImplementedError(
            "enhanced_for_statement with brace-less body is "
            "not yet supported."
        )

    type_node = node.child_by_field_name("type")
    name_node = node.child_by_field_name("name")
    value_node = node.child_by_field_name("value")
    if type_node is None or name_node is None or value_node is None:
        raise NotImplementedError(
            "enhanced_for_statement missing 'type', 'name', or "
            "'value' — grammar shape unexpected."
        )

    emitter.write("for (")
    _emit_node(emitter, source, type_node)
    emitter.write(" ")
    _emit_node(emitter, source, name_node)
    emitter.write(" : ")
    _emit_node(emitter, source, value_node)
    emitter.write(") ")
    _emit_node(emitter, source, body)


def _emit_while_statement(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `while (cond) { ... }`.

    Per the spec's "Brace Placement / Exception: Multi-Line
    Conditions" rule, when the condition spans multiple source
    rows the opening `{` goes Allman (on its own line, aligned
    with the `while` keyword's indent). Single-line conditions
    keep the same-line brace.

    Grammar fields: `condition` (parenthesized_expression),
    `body` (block).
    """
    condition = node.child_by_field_name("condition")
    body = node.child_by_field_name("body")
    if condition is None or body is None or body.type != "block":
        raise NotImplementedError(
            "while_statement with missing fields or brace-less "
            "body is not yet supported."
        )
    emitter.write("while ")
    if _node_spans_multiple_rows(condition):
        # Preserve the developer-authored multi-line condition
        # verbatim from source; switch to Allman brace.
        emitter.write_raw_lines(_node_source_text(source, condition))
        emitter.newline()
        emitter.write_indent()
        _emit_node(emitter, source, body)
    else:
        _emit_node(emitter, source, condition)
        emitter.write(" ")
        _emit_node(emitter, source, body)


def _emit_do_statement(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `do { ... } while (cond);`.

    Per the "Closing Brace Rules" spec section, `while`
    cuddles with the closing `}` of the body block:
    `} while (cond);`. Grammar fields: `body` (block),
    `condition` (parenthesized_expression).
    """
    body = node.child_by_field_name("body")
    condition = node.child_by_field_name("condition")
    if body is None or body.type != "block":
        raise NotImplementedError(
            "do_statement with missing body or brace-less body "
            "is not yet supported."
        )
    if condition is None:
        raise NotImplementedError(
            "do_statement missing 'condition' — grammar shape "
            "unexpected."
        )
    emitter.write("do ")
    _emit_node(emitter, source, body)
    # The block emitter ends mid-line at `}`; we continue on
    # the same line with cuddled ` while (cond);`.
    emitter.write(" while ")
    _emit_node(emitter, source, condition)
    emitter.write(";")


def _emit_return_statement(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `return;` or `return EXPR;`.

    Grammar: `return` anonymous keyword, optional named
    expression child, anonymous `;`. The optional expression
    (when present) is the only named child; we look for it by
    iteration rather than a field accessor (the grammar
    doesn't expose a `value` field for it).
    """
    value: Node | None = None
    for child in node.children:
        if child.is_named:
            value = child
            break
    if value is None:
        emitter.write("return;")
    else:
        emitter.write("return ")
        _emit_node(emitter, source, value)
        emitter.write(";")


def _emit_expression_statement(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `EXPR;` where EXPR is the single named child.

    Used for assignment-as-statement (`x = 1;`), method-call
    statement (`compute();`), update statements (`++x;`), etc.
    The current grammar version exposes exactly one named
    child for this node type; we look it up by iteration
    rather than a field accessor (the grammar does not expose
    a field name for it).
    """
    expr: Node | None = None
    for child in node.children:
        if child.is_named:
            expr = child
            break
    if expr is None:
        raise NotImplementedError(
            "expression_statement has no named child — grammar "
            "shape unexpected."
        )
    _emit_node(emitter, source, expr)
    emitter.write(";")


def _emit_assignment_expression(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `LHS OP RHS` with space-space around the operator.

    Per the "Whitespace and Operator Spacing" spec section's
    assignment-operator row, every assignment operator
    (`=`, `+=`, `-=`, `*=`, `/=`, `%=`, `&=`, `|=`, `^=`,
    `<<=`, `>>=`, `>>>=`) gets exactly one space on each side.
    Grammar fields: `left`, `operator`, `right`.
    """
    left_node = node.child_by_field_name("left")
    right_node = node.child_by_field_name("right")
    if left_node is None or right_node is None:
        raise NotImplementedError(
            "assignment_expression missing 'left' or 'right' — "
            "grammar shape unexpected."
        )
    # The operator is exposed as an anonymous child carrying
    # the operator text. The grammar names this child via the
    # `operator` field — recover it via field_name_for_child
    # to support every assignment-operator variant uniformly.
    op_text: str | None = None
    for index, child in enumerate(node.children):
        if node.field_name_for_child(index) == "operator":
            op_text = child.type
            break
    if op_text is None:
        raise NotImplementedError(
            "assignment_expression missing operator — grammar "
            "shape unexpected."
        )
    _emit_node(emitter, source, left_node)
    emitter.write(" ")
    emitter.write(op_text)
    emitter.write(" ")
    _emit_node(emitter, source, right_node)


def _emit_try_with_resources_statement(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `try (resources) BODY [catches] [finally]`.

    Per spec B8 ("Try-with-resources"):
        - Single resource fitting on one line: same-line
          opening brace — `try (Resource r = expr) {`.
        - Multi-resource: ALWAYS multi-line. Each resource
          on its own line; subsequent resources paren-aligned
          with the first (the column right after `try (`).
          Each resource but the last ends with `;`; the
          last ends with `)`. The opening `{` then goes on
          its own line (Allman) because the try condition
          spans multiple lines.

    Phase 2w emits both shapes. The single-resource
    break-on-`=` wrap (when the resource overflows on its
    own line) lands with the wrap-priority phase.

    `catch_clause` and `finally_clause` children, if
    present, cuddle with the closing `}` of the body block
    per spec's "Closing Brace Rules" — same as the regular
    `try_statement` emitter.
    """
    resources_node = node.child_by_field_name("resources")
    body = node.child_by_field_name("body")
    if resources_node is None or body is None:
        raise NotImplementedError(
            "try_with_resources_statement missing 'resources' "
            "or 'body' — grammar shape unexpected."
        )

    resources = [
        c for c in resources_node.named_children
        if c.type == "resource"
    ]
    if not resources:
        raise NotImplementedError(
            "try_with_resources_statement with no resource "
            "children — grammar shape unexpected."
        )

    emitter.write("try (")
    # Column right after the opening `(`; subsequent resource
    # lines align here.
    align_col = emitter.column
    for index, resource in enumerate(resources):
        if index > 0:
            emitter.write(";")
            emitter.newline()
            emitter.write(" " * align_col)
        _emit_node(emitter, source, resource)
    emitter.write(")")

    if len(resources) > 1:
        # Allman brace because the try condition is
        # multi-line.
        emitter.newline()
        emitter.write_indent()
        _emit_node(emitter, source, body)
    else:
        # Single resource on one line — same-line brace.
        emitter.write(" ")
        _emit_node(emitter, source, body)

    # Optional catch and finally clauses cuddle with the
    # closing `}` of the body. Same shape as
    # `_emit_try_statement`.
    for child in node.children:
        if child.type in ("catch_clause", "finally_clause"):
            emitter.write(" ")
            _emit_node(emitter, source, child)


def _emit_resource(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `TYPE NAME = VALUE` for a try-with-resources resource.

    Caller positions the resource on its line; this emitter
    writes only the declaration itself, no trailing `;` or
    newline (the parent `_emit_try_with_resources_statement`
    handles separators).

    Phase 2w covers the standard `TYPE name = value` form.
    The Java 9+ shorthand where a previously-declared
    `final` variable can be used directly (`try (conn) { ...
    }`) isn't yet exercised; that form may surface as a
    different grammar shape.
    """
    type_node = node.child_by_field_name("type")
    name_node = node.child_by_field_name("name")
    value_node = node.child_by_field_name("value")
    if type_node is None or name_node is None or value_node is None:
        raise NotImplementedError(
            "resource missing 'type' / 'name' / 'value' — "
            "shorthand resource form (Java 9+ effectively-"
            "final variable) is not yet supported."
        )
    _emit_node(emitter, source, type_node)
    emitter.write(" ")
    _emit_node(emitter, source, name_node)
    emitter.write(" = ")
    _emit_node(emitter, source, value_node)


def _emit_lambda_expression(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `PARAMS -> BODY`.

    Per spec B5 ("Lambdas"): single space on each side of
    `->`. The parameters field can be:
        - `identifier` — single inferred-type param
          (`x -> body`)
        - `inferred_parameters` — multi inferred-type params
          (`(x, y) -> body`)
        - `formal_parameters` — explicit-typed params
          (`(int x) -> body`)
    The body field can be an expression (`x + 1`) or a
    block (`{ stmt; stmt; }`). When the body is a block, it
    dispatches through `_emit_block` which uses same-line
    opening brace per the spec's "Brace Placement /
    Same-Line Style" bullet for lambda expressions.

    Phase 2v emits the single-line form unconditionally.
    Multi-line wrap rules (the universal `->` placement
    rule from spec B5, including breaking before `->` when
    the parameter list itself wraps) land with the
    wrap-priority phase.
    """
    parameters = node.child_by_field_name("parameters")
    body = node.child_by_field_name("body")
    if parameters is None or body is None:
        raise NotImplementedError(
            "lambda_expression missing 'parameters' or "
            "'body' — grammar shape unexpected."
        )
    _emit_node(emitter, source, parameters)
    emitter.write(" -> ")
    _emit_node(emitter, source, body)


def _emit_inferred_parameters(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `(x, y, ...)` for a multi-arg inferred-type lambda.

    Comma-space separator per spec A4 ("After commas").
    """
    names = [
        c for c in node.children if c.is_named and c.type == "identifier"
    ]
    emitter.write("(")
    for index, name in enumerate(names):
        if index > 0:
            emitter.write(", ")
        _emit_node(emitter, source, name)
    emitter.write(")")


def _emit_wildcard(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `?` / `? extends T` / `? super T`.

    Per spec A4 ("Whitespace and Operator Spacing"):
    Space after `?` before `extends` / `super` keyword.
    Grammar shape: `?` anonymous, optional `extends` or
    `super` keyword (anonymous or named depending on form),
    optional type child.
    """
    emitter.write("?")
    for child in node.children:
        if child.type == "?":
            continue
        emitter.write(" ")
        if child.is_named:
            _emit_node(emitter, source, child)
        else:
            emitter.write(child.type)


def _emit_superclass(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `extends TYPE` for a class declaration's superclass.

    Grammar: `superclass` node contains the `extends` keyword
    (anonymous) and a type child. Emits `extends ` + type.
    """
    types = [c for c in node.named_children]
    if not types:
        raise NotImplementedError(
            "superclass node with no type child — grammar shape "
            "unexpected."
        )
    emitter.write("extends ")
    _emit_node(emitter, source, types[0])


def _emit_extends_interfaces(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `extends TYPE, ...` for an interface declaration's
    extends_interfaces clause.

    Grammar: `extends_interfaces` node contains the `extends`
    keyword (anonymous) and a `type_list` child holding the
    parent-interface types. Single-line form; the multi-line
    wrap rule from spec B1 ("Class Headers") lands later.
    """
    type_list = None
    for c in node.named_children:
        if c.type == "type_list":
            type_list = c
            break
    if type_list is None:
        raise NotImplementedError(
            "extends_interfaces missing 'type_list' child — "
            "grammar shape unexpected."
        )
    types = list(type_list.named_children)
    emitter.write("extends ")
    for index, t in enumerate(types):
        if index > 0:
            emitter.write(", ")
        _emit_node(emitter, source, t)


def _emit_method_reference(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `RECEIVER::METHOD` (or `Class::new`).

    Per spec B6: no space on either side of `::`. The grammar
    exposes the receiver as the first named child and the
    method name as the second; emit each with `::` between,
    no spaces.
    """
    children = [c for c in node.named_children]
    if len(children) < 2:
        # Method references with explicit type witness
        # (`Class::<T>method`) surface with extra named
        # children. Emit source verbatim as a fallback.
        emitter.write(_node_source_text(source, node))
        return
    receiver = children[0]
    name_part = children[1]
    _emit_node(emitter, source, receiver)
    emitter.write("::")
    _emit_node(emitter, source, name_part)


def _emit_super_interfaces(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `implements TYPE, ...` for a class declaration's
    super_interfaces clause.

    Grammar: `super_interfaces` node contains the `implements`
    keyword (anonymous) and a `type_list` child holding the
    types. Single-line form for now; spec B1 multi-line wrap
    (when the implements clause overflows on its own) lands
    later.
    """
    type_list = None
    for c in node.named_children:
        if c.type == "type_list":
            type_list = c
            break
    if type_list is None:
        raise NotImplementedError(
            "super_interfaces missing 'type_list' child — grammar "
            "shape unexpected."
        )
    types = list(type_list.named_children)
    emitter.write("implements ")
    for index, t in enumerate(types):
        if index > 0:
            emitter.write(", ")
        _emit_node(emitter, source, t)


def _emit_type_parameters(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `<T1, T2, ...>` for a generic declaration.

    Per spec A4 ("Whitespace and Operator Spacing"): no space
    inside or around `<>`; comma-space between type parameters.
    Phase 2x emits the single-line form unconditionally. The
    spec B11 multi-line wraps (P2 paren-aligned with the first
    parameter, P3 next-line single-indented with each parameter
    on its own line) land with the wrap-priority phase.

    Used by `_emit_class_declaration`, `_emit_interface_-
    declaration`, `_emit_method_declaration`, and `_emit_-
    constructor_declaration` to render the `<...>` clause.
    """
    params = [c for c in node.named_children if c.type == "type_parameter"]
    if not params:
        raise NotImplementedError(
            "type_parameters node with no type_parameter "
            "children — grammar shape unexpected."
        )
    emitter.write("<")
    for index, param in enumerate(params):
        if index > 0:
            emitter.write(", ")
        _emit_node(emitter, source, param)
    emitter.write(">")


def _emit_type_parameter(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit a single type parameter: `T`, `T extends Foo`,
    `T extends Foo & Bar`, or `@Ann T extends Foo`.

    Grammar shape: optional annotation(s) (`marker_annotation`
    / `annotation`), then `type_identifier` for the parameter
    name, then optional `type_bound`. Per spec B11 / A4:

        - Single space between annotation and identifier.
        - Single space between identifier and `extends` keyword
          (emitted by `_emit_type_bound`).
        - Single space around `&` for multi-bound types
          (emitted by `_emit_type_bound`).
    """
    emitted_anything = False
    for child in node.named_children:
        if child.type in ("marker_annotation", "annotation"):
            if emitted_anything:
                emitter.write(" ")
            _emit_node(emitter, source, child)
            emitted_anything = True
        elif child.type == "type_identifier":
            if emitted_anything:
                emitter.write(" ")
            _emit_node(emitter, source, child)
            emitted_anything = True
        elif child.type == "type_bound":
            emitter.write(" ")
            _emit_node(emitter, source, child)
        else:
            raise NotImplementedError(
                f"type_parameter child {child.type!r} is not "
                "yet supported."
            )


def _emit_type_bound(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `extends Type` or `extends A & B & ...`.

    Grammar shape: anonymous `extends` keyword followed by one
    or more type nodes (named children) separated by anonymous
    `&` tokens. Per spec B11 / A4: single space on each side
    of `extends`; single space on each side of `&`.

    Caller positions the leading space; this emitter writes
    `extends ` + type1 [+ ` & ` + typeN]....
    """
    type_children = [c for c in node.named_children]
    if not type_children:
        raise NotImplementedError(
            "type_bound with no named type children — grammar "
            "shape unexpected."
        )
    emitter.write("extends ")
    for index, type_child in enumerate(type_children):
        if index > 0:
            emitter.write(" & ")
        _emit_node(emitter, source, type_child)


def _emit_enum_declaration(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `[modifiers] enum NAME { body }` with Allman braces.

    Per the spec's "Brace Placement / Allman Style" section,
    enum definitions take Allman braces. Per spec A2 and B9,
    the body emits each enum constant on its own line with a
    `,` separator, a final `;` after the last constant
    (always emitted regardless of whether more members
    follow), then a blank line and any non-constant
    members.

    Refuses `extends_interfaces`, `permits`, and
    `type_parameters` clauses — those land with the
    "Class Headers" wrap-priority phase.
    """
    modifiers_node: Node | None = None
    super_interfaces_node: Node | None = None
    for child in node.named_children:
        if child.type in (
            "type_parameters",
            "permits",
        ):
            raise NotImplementedError(
                f"enum_declaration child {child.type!r} is not "
                "yet supported; that construct comes in a "
                "later phase."
            )
        if child.type == "modifiers":
            modifiers_node = child
        elif child.type == "super_interfaces":
            super_interfaces_node = child

    name = node.child_by_field_name("name")
    body = node.child_by_field_name("body")

    if modifiers_node is not None:
        _emit_node(emitter, source, modifiers_node)
    emitter.write("enum ")
    if name is not None:
        _emit_node(emitter, source, name)
    if super_interfaces_node is not None:
        emitter.write(" ")
        _emit_node(emitter, source, super_interfaces_node)
    emitter.newline()
    emitter.write_indent()
    emitter.write("{")
    emitter.newline()
    if body is not None:
        _emit_enum_body_members(emitter, source, body)
    emitter.write_indent()
    emitter.write("}")


def _emit_enum_body_members(
    emitter: Emitter, source: bytes, body_node: Node
) -> None:
    """Emit the interior of an enum body.

    Per spec B9: each enum constant on its own line with a
    trailing `,`; the last constant gets `;` instead. Per
    spec A2: one blank line between the constants block and
    any non-constant members that follow. Per the existing
    spec convention, each non-private enum constant is
    typically preceded by a javadoc block — the grammar
    exposes such javadocs as `block_comment` siblings of
    `enum_constant` in the enum_body. Collect leading
    comments and emit them above each constant.

    Caller emits the opening `{` and closing `}`.
    """
    # Walk the body in order: comments accumulate until the
    # next enum_constant, then flush.
    pending_comments: list[Node] = []
    # Constants with their preceding comment groups.
    grouped: list[tuple[list[Node], Node]] = []
    extra_members: list[Node] = []
    for child in body_node.named_children:
        if child.type in ("block_comment", "line_comment"):
            pending_comments.append(child)
        elif child.type == "enum_constant":
            grouped.append((pending_comments, child))
            pending_comments = []
        elif child.type == "enum_body_declarations":
            for grandchild in child.named_children:
                extra_members.append(grandchild)

    if not grouped and not extra_members:
        return

    emitter.push_indent()
    prev_const_end_row = -1
    for index, (comments, const) in enumerate(grouped):
        # Spec A2: blank line above a comment that introduces
        # a constant — only when source had a blank line
        # between this group and the previous one.
        if index > 0 and comments:
            # Compare prev constant's end_row to first comment's
            # start_row.
            first_comment_row = comments[0].start_point[0]
            if first_comment_row - prev_const_end_row > 1:
                emitter.newline()
        for c in comments:
            emitter.write_indent()
            _emit_node(emitter, source, c)
            emitter.newline()
        emitter.write_indent()
        _emit_node(emitter, source, const)
        if index < len(grouped) - 1:
            emitter.write(",")
        else:
            emitter.write(";")
        emitter.newline()
        prev_const_end_row = const.end_point[0]

    if extra_members:
        # Spec A2: blank line between the constants `;` and
        # the first non-constant member.
        emitter.newline()
        prev: Node | None = None
        for member in extra_members:
            if prev is not None:
                if member.start_point[0] - prev.end_point[0] > 1:
                    emitter.newline()
            emitter.write_indent()
            _emit_node(emitter, source, member)
            emitter.newline()
            prev = member
    emitter.pop_indent()


def _emit_enum_constant(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `[modifiers] NAME [(arguments)] [{ body }]`.

    Per spec B9 ("Enum Constant Bodies"):

        - Plain constant — `INACTIVE("inactive", 0)`.
        - Constant with anonymous body — body opens on its
          OWN line (Allman braces), NOT same-line. This
          differs from C8 anonymous classes (which DO use
          same-line braces) because here the body is the
          continuation of a top-level enum constant
          declaration rather than an inline expression.
        - Combined constant + arguments + body —
          `PLUS("plus", 1) { @Override ... }` follows the
          same Allman placement.

    The body, when present, is structurally a class body —
    same content rules as `_emit_class_body_members` for
    top-level classes (method declarations inside still
    take their normal Allman brace placement, etc.).
    Body members are indented one level deeper than the
    constant; the closing `}` aligns with the constant.

    The trailing `,` or `;` separator is emitted by the
    parent `_emit_enum_body_members` — this function ends
    mid-line at the constant's last token (closing `)` of
    arguments, closing `}` of body, or identifier).
    """
    modifiers_node: Node | None = None
    for child in node.named_children:
        if child.type == "modifiers":
            modifiers_node = child
            break

    if modifiers_node is not None:
        _emit_node(emitter, source, modifiers_node)
    name = node.child_by_field_name("name")
    arguments = node.child_by_field_name("arguments")
    body = node.child_by_field_name("body")
    if name is None:
        raise NotImplementedError(
            "enum_constant missing 'name' — grammar shape "
            "unexpected."
        )
    _emit_node(emitter, source, name)
    if arguments is not None:
        _emit_node(emitter, source, arguments)
    if body is not None:
        # Per spec B9: body opens on its own line (Allman),
        # NOT same-line like C8 anonymous-class expressions.
        emitter.newline()
        emitter.write_indent()
        emitter.write("{")
        emitter.newline()
        _emit_class_body_members(emitter, source, body)
        emitter.write_indent()
        emitter.write("}")


def _emit_interface_declaration(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit an interface declaration with Allman brace placement.

    Shares its emission shape with `_emit_class_declaration`:
    `[modifiers] interface NAME { body }`. Per the spec's
    "Brace Placement / Allman Style" section, interface
    definitions take Allman braces.

    Single-line `<T>` / `<T extends Foo>` type parameters
    (spec B11) are emitted by `_emit_type_parameters`.
    `extends_interfaces` and `permits` clauses still refuse —
    they have their own priority-by-line-length wrapping
    rules in the "Class Headers" spec section that the
    current emitter doesn't yet handle.
    """
    modifiers_node: Node | None = None
    type_parameters_node: Node | None = None
    extends_interfaces_node: Node | None = None
    for child in node.named_children:
        if child.type == "permits":
            raise NotImplementedError(
                f"interface_declaration child {child.type!r} is "
                "not yet supported; that construct comes in a "
                "later phase."
            )
        if child.type == "modifiers":
            modifiers_node = child
        elif child.type == "type_parameters":
            type_parameters_node = child
        elif child.type == "extends_interfaces":
            extends_interfaces_node = child

    name = node.child_by_field_name("name")
    body = node.child_by_field_name("body")

    if modifiers_node is not None:
        _emit_node(emitter, source, modifiers_node)
    emitter.write("interface ")
    if name is not None:
        _emit_node(emitter, source, name)
    if type_parameters_node is not None:
        _emit_node(emitter, source, type_parameters_node)
    if extends_interfaces_node is not None:
        emitter.write(" ")
        _emit_node(emitter, source, extends_interfaces_node)
    emitter.newline()
    emitter.write_indent()
    emitter.write("{")
    emitter.newline()
    if body is not None:
        _emit_interface_body_members(emitter, source, body)
    emitter.write_indent()
    emitter.write("}")


def _emit_interface_body_members(
    emitter: Emitter, source: bytes, body_node: Node
) -> None:
    """Emit the members of an interface body, indented one level.

    Shape mirrors `_emit_class_body_members`: open and close
    braces are emitted by the caller, this function emits the
    interior. Members are typically abstract method
    declarations, constant declarations, default / static
    methods, nested types, etc. Preserves source-authored
    blank lines between members per spec A2 (same rule as
    `_emit_class_body_members`).
    """
    members = list(body_node.named_children)
    if not members:
        return
    emitter.push_indent()
    prev: Node | None = None
    for member in members:
        if prev is not None:
            if member.start_point[0] - prev.end_point[0] > 1:
                emitter.newline()
        emitter.write_indent()
        _emit_node(emitter, source, member)
        emitter.newline()
        prev = member
    emitter.pop_indent()


def _emit_constructor_declaration(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit a constructor declaration with Allman brace placement.

    Constructors share their grammar shape with methods minus
    the return-type field: `[modifiers] NAME(params) [throws]
    { body }`. Per the "Brace Placement / Allman Style" spec
    section, constructor definitions use Allman braces (same
    rule that applies to method definitions).

    Single-line `<T>` / `<T extends Foo>` type parameters
    (spec B11) are emitted by `_emit_type_parameters`. The
    `<...>` clause sits between any modifiers and the
    constructor name, with a single space after the closing
    `>`.
    """
    modifiers_node: Node | None = None
    type_parameters_node: Node | None = None
    throws_node: Node | None = None
    for child in node.named_children:
        if child.type == "modifiers":
            modifiers_node = child
        elif child.type == "type_parameters":
            type_parameters_node = child
        elif child.type == "throws":
            throws_node = child

    name_node = node.child_by_field_name("name")
    parameters_node = node.child_by_field_name("parameters")
    body = node.child_by_field_name("body")
    if name_node is None or parameters_node is None or body is None:
        raise NotImplementedError(
            "constructor_declaration missing 'name', "
            "'parameters', or 'body' — grammar shape "
            "unexpected."
        )

    if modifiers_node is not None:
        _emit_node(emitter, source, modifiers_node)
    if type_parameters_node is not None:
        # Per spec B11: `<T>` comes BEFORE the constructor name,
        # with a single space after the closing `>`.
        _emit_node(emitter, source, type_parameters_node)
        emitter.write(" ")
    _emit_node(emitter, source, name_node)
    _emit_node(emitter, source, parameters_node)
    emitter.newline()
    if throws_node is not None:
        emitter.push_indent()
        emitter.write_indent()
        _emit_node(emitter, source, throws_node)
        emitter.newline()
        emitter.pop_indent()
    emitter.write_indent()
    emitter.write("{")
    emitter.newline()

    statements = list(body.named_children)
    if statements:
        emitter.push_indent()
        prev_stmt: Node | None = None
        for stmt in statements:
            if prev_stmt is not None:
                if stmt.start_point[0] - prev_stmt.end_point[0] > 1:
                    emitter.newline()
            emitter.write_indent()
            _emit_node(emitter, source, stmt)
            emitter.newline()
            prev_stmt = stmt
        emitter.pop_indent()

    emitter.write_indent()
    emitter.write("}")
    # Caller appends the trailing newline.


def _emit_static_initializer(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `static { ... }` with Allman brace placement.

    Per spec B10 ("Static and Instance Initializer Blocks"),
    `static` sits on its own line, opening `{` on the next
    line at the same column, body indented +4, closing `}`
    on its own line at the same column. Static initializer
    blocks are declaration-level members (like methods and
    constructors), not control flow, so they take Allman
    braces.

    Grammar: `static` anonymous keyword followed by a `block`
    named child (no field name).
    """
    block: Node | None = None
    for child in node.named_children:
        if child.type == "block":
            block = child
            break
    if block is None:
        raise NotImplementedError(
            "static_initializer missing block — grammar shape "
            "unexpected."
        )
    emitter.write("static")
    emitter.newline()
    emitter.write_indent()
    emitter.write("{")
    emitter.newline()

    statements = list(block.named_children)
    if statements:
        emitter.push_indent()
        for stmt in statements:
            emitter.write_indent()
            _emit_node(emitter, source, stmt)
            emitter.newline()
        emitter.pop_indent()

    emitter.write_indent()
    emitter.write("}")
    # Caller appends the trailing newline.


def _emit_annotated_type(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `@Annotation [@Annotation ...] TYPE` for a type-use annotation.

    Per spec A3 ("Type-use annotations"): annotations sit
    inline immediately before the type they annotate, with a
    single space between annotation and type. Multiple
    annotations are likewise separated by a single space.

    Grammar: one or more annotation children
    (`marker_annotation`, `annotation`) followed by the type
    node (`type_identifier`, `generic_type`, or
    `scoped_type_identifier`).
    """
    children = list(node.named_children)
    for index, child in enumerate(children):
        if index > 0:
            emitter.write(" ")
        _emit_node(emitter, source, child)


def _emit_throws(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `throws TYPE [, TYPE]...` with wrap-priority selection.

    Caller is responsible for positioning this emitter on
    its own line single-indented from the method declaration
    (per the "Method and Constructor Declarations / Throws
    Clause" spec section). This emitter writes the keyword,
    a single space, and the type list; it does NOT add a
    leading or trailing newline.

    Two forms per spec "Throws Clause / Wrap Priority":
        - P1 (single line): `throws TypeA, TypeB, TypeC` when
          the resulting line — counting the caller's leading
          indent and the `throws ` keyword and all types and
          their separators — fits within 80 characters.
        - P2 (column-aligned multi-line): each type on its
          own line, with continuation lines aligned to the
          column right after `throws ` (i.e. the column where
          the FIRST type starts). Each line but the last
          carries a trailing `,`; the last carries no
          terminator.

    The P3/P4 fallbacks (next-line double-indented if even
    P2 overflows; CSOFF/CSON warning emission) land with
    later wrap-priority phases — for the current corpus, no
    fixture pushes past P2.
    """
    types = list(node.named_children)
    if not types:
        emitter.write("throws")
        return

    # Measure the would-be P1 single-line width. `emitter.column`
    # is the current line position right before we emit "throws".
    # That's the leading-indent column for the throws line. The
    # P1 width therefore equals indent + `throws ` + sum of type
    # source widths + 2*(n-1) comma-space separators.
    start_col = emitter.column
    type_widths = [
        len(_node_source_text(source, t)) for t in types
    ]
    single_line_width = (
        start_col
        + len("throws ")
        + sum(type_widths)
        + 2 * (len(types) - 1)
    )

    emitter.write("throws ")
    # `emitter.column` is now start_col + 7 — the continuation
    # column for P2 lines.
    cont_col = emitter.column

    if single_line_width <= _MAX_LINE:
        # P1: all types on one line, comma-space separated.
        for index, t in enumerate(types):
            if index > 0:
                emitter.write(", ")
            _emit_node(emitter, source, t)
        return

    # P2: one type per line, continuation aligned at `cont_col`.
    for index, t in enumerate(types):
        if index > 0:
            emitter.newline()
            emitter.write(" " * cont_col)
        _emit_node(emitter, source, t)
        if index < len(types) - 1:
            emitter.write(",")


def _emit_formal_parameters(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `(p1, p2, ...)`.

    Single-line form for parameters whose source span fits on
    one row. When the source has the parameter list spanning
    multiple rows, the developer-authored multi-line layout
    is preserved (paren-aligned continuation lines from
    source) — the formatter does not collapse them.

    The full four-priority wrapping rules from the "Method and
    Constructor Declarations / Parameter Placement" spec
    section (auto-wrap when single-line would overflow 80
    chars, choose P1/P2/P3/P4 by width) land with later wrap-
    priority phases. The current behavior is source-
    preservation only.

    Receivers (`@This Foo this`) and varargs (`Type... name`)
    are not yet supported and will surface via dispatch
    refusals from the per-parameter / per-type emitters.
    """
    if _node_spans_multiple_rows(node):
        # Preserve developer-authored multi-line params from
        # source. Includes opening `(` and closing `)`.
        emitter.write_raw_lines(_node_source_text(source, node))
        return
    params = [
        c for c in node.children
        if c.type in ("formal_parameter", "spread_parameter")
    ]
    emitter.write("(")
    for index, param in enumerate(params):
        if index > 0:
            emitter.write(", ")
        _emit_node(emitter, source, param)
    emitter.write(")")


def _emit_spread_parameter(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `TYPE... NAME` for a varargs parameter (spec B12).

    Per spec B12: no space before the ellipsis, single space
    after. Grammar exposes the type as a named child, the `...`
    as an anonymous token, and the name as a `variable_declarator`
    named child.
    """
    type_node = None
    name_node = None
    for c in node.named_children:
        if c.type == "modifiers":
            # Emit modifiers inline (same rule as
            # _emit_formal_parameter).
            for mc in c.children:
                if mc.is_named:
                    _emit_node(emitter, source, mc)
                else:
                    emitter.write(mc.type)
                emitter.write(" ")
        elif type_node is None:
            type_node = c
        else:
            name_node = c
    if type_node is None or name_node is None:
        raise NotImplementedError(
            "spread_parameter missing type or name child — "
            "grammar shape unexpected."
        )
    _emit_node(emitter, source, type_node)
    emitter.write("... ")
    _emit_node(emitter, source, name_node)


def _emit_formal_parameter(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `[MODIFIERS] TYPE NAME` for a single formal parameter.

    Per spec A3 ("Annotations on parameters"), keyword modifiers
    (`final`) and annotations (`@NonNull`) appear before the
    type INLINE with a single space separator. The full
    annotation+type-combo column-alignment rule for multi-line
    parameter lists lands with the wrap-priority phase; this
    emitter handles the single-line form.

    The shared `_emit_modifiers` helper puts annotations on
    their own LINE (suitable for top-level declarations);
    parameter annotations are inline, so we emit them
    explicitly here rather than dispatching.
    """
    modifiers_node: Node | None = None
    for child in node.named_children:
        if child.type == "modifiers":
            modifiers_node = child
            break
    type_node = node.child_by_field_name("type")
    name_node = node.child_by_field_name("name")
    if type_node is None or name_node is None:
        raise NotImplementedError(
            "formal_parameter missing 'type' or 'name' — "
            "grammar shape unexpected."
        )
    if modifiers_node is not None:
        # Emit each annotation / keyword inline with a trailing
        # space. Order of named children (annotations) is
        # preserved; anonymous children are keywords (`final`).
        for c in modifiers_node.children:
            if c.is_named:
                _emit_node(emitter, source, c)
            else:
                emitter.write(c.type)
            emitter.write(" ")
    _emit_node(emitter, source, type_node)
    emitter.write(" ")
    _emit_node(emitter, source, name_node)


def _emit_array_type(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `T[]` (element type + `[]` per dimension).

    Grammar: `array_type` has named fields `element` (the
    element type) and `dimensions` (a `dimensions` node with
    `[`/`]` anonymous children, one pair per dimension).
    Brackets are adjacent to the type per the spec's
    "Multi-dimensional arrays" subsection of "Miscellaneous
    Clarifications".
    """
    element_node = node.child_by_field_name("element")
    dimensions_node = node.child_by_field_name("dimensions")
    if element_node is None or dimensions_node is None:
        raise NotImplementedError(
            "array_type missing 'element' or 'dimensions' — "
            "grammar shape unexpected."
        )
    _emit_node(emitter, source, element_node)
    # Each `[ ]` pair contributes "[]" with no spaces. The
    # dimensions node also has no spaces inside.
    dim_text = _node_source_text(source, dimensions_node)
    # Strip any internal whitespace the developer may have
    # written (e.g. `[ ]` → `[]`); spec requires no spaces.
    emitter.write("".join(dim_text.split()))


def _emit_field_access(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `OBJECT.FIELD` with no spaces around the dot.

    Grammar: `field_access` has named fields `object` (the
    receiver expression) and `field` (the identifier after the
    dot). The `.` itself is an anonymous child.
    """
    object_node = node.child_by_field_name("object")
    field_node = node.child_by_field_name("field")
    if object_node is None or field_node is None:
        raise NotImplementedError(
            "field_access missing 'object' or 'field' — grammar "
            "shape unexpected."
        )
    _emit_node(emitter, source, object_node)
    emitter.write(".")
    _emit_node(emitter, source, field_node)


def _emit_instanceof_expression(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `VALUE instanceof TYPE` with single spaces.

    Grammar: `instanceof_expression` has named fields `left`
    (the value) and `right` (the type), with `instanceof` as
    an anonymous keyword between them. Per the surrounding
    "Whitespace and Operator Spacing" rules and the spec's
    "Pattern matching — type patterns" subsection, the keyword
    gets one space on each side.

    Two extended forms are explicitly refused here because they
    have dedicated spec sections that need their own emitters:
        - **Pattern-binding form** `obj instanceof Type t` adds
          a `name` field carrying the bound identifier.
        - **Record / deconstruction pattern form**
          `obj instanceof Point(int x, int y)` replaces the
          `right` field with a `pattern` field pointing at a
          `record_pattern` node.
    Both land in a later phase with the pattern-matching
    emitters.
    """
    # Record-pattern form must be checked BEFORE looking for
    # `right`, because the grammar uses `pattern` instead of
    # `right` for the deconstruction case.
    if node.child_by_field_name("pattern") is not None:
        raise NotImplementedError(
            "instanceof record/deconstruction pattern form "
            "(`x instanceof Point(int x, int y)`) is not yet "
            "supported; pattern matching lands in a later phase."
        )
    if node.child_by_field_name("name") is not None:
        raise NotImplementedError(
            "instanceof pattern-binding form "
            "(`x instanceof Type t`) is not yet supported; "
            "pattern matching lands in a later phase."
        )
    left_node = node.child_by_field_name("left")
    right_node = node.child_by_field_name("right")
    if left_node is None or right_node is None:
        raise NotImplementedError(
            "instanceof_expression missing 'left' or 'right' — "
            "grammar shape unexpected."
        )
    _emit_node(emitter, source, left_node)
    emitter.write(" instanceof ")
    _emit_node(emitter, source, right_node)


def _emit_cast_expression(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `(TYPE) VALUE` with a single space after the closing paren.

    Per the "Whitespace and Operator Spacing" spec section, a
    type cast emits as `(Type) value` — single space between
    the closing cast paren and the value. The grammar exposes
    `cast_expression` with named fields `type` (for the cast
    target type) and `value` (for the expression being cast).

    Intersection-type casts (`(A & B) value`) are explicitly
    refused for now: tree-sitter-java surfaces both bound types
    as siblings each carrying the `type` field, with the `&`
    operator as an anonymous child between them.
    `child_by_field_name("type")` returns only the FIRST type,
    so a naive emission would silently drop the second bound.
    The "Cast expressions" spec section's intersection-type
    bullet documents the required formatting; full emission
    lands with the generic-types phase.
    """
    type_node = node.child_by_field_name("type")
    value_node = node.child_by_field_name("value")
    if type_node is None or value_node is None:
        raise NotImplementedError(
            "cast_expression missing 'type' or 'value' — grammar "
            "shape unexpected."
        )
    # Detect intersection-type cast: more than one `type` field
    # or the presence of an anonymous `&` child indicates the
    # extended form.
    type_field_count = 0
    has_amp = False
    for index, child in enumerate(node.children):
        if node.field_name_for_child(index) == "type":
            type_field_count += 1
        elif not child.is_named and child.type == "&":
            has_amp = True
    if type_field_count > 1 or has_amp:
        raise NotImplementedError(
            "cast_expression with intersection type "
            "(`(A & B) value`) is not yet supported; full "
            "emission lands with the generic-types phase."
        )
    emitter.write("(")
    _emit_node(emitter, source, type_node)
    emitter.write(") ")
    _emit_node(emitter, source, value_node)


def _emit_argument_list(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `(arg1, arg2, ...)` with wrap-priority selection.

    Per spec "Method Call Arguments / Placement (in priority
    order by line length)":

        - P1 (single line): entire call fits in 80 chars.
        - P2 (two-line paren-aligned, comma-packed): the
          argument list spans exactly two source lines —
          pack as many args as fit on the call line, wrap
          the rest aligned to the column after `(`.
        - P3 (paren-aligned, one arg per line): each arg on
          its own line at the column after `(`.
        - P4 (next-line single-indent): line-break before
          the first arg; each arg on its own line at
          single-indent (4 spaces) past the call's
          statement start.

    Current implementation: P1 + P2 fully supported using
    source-text widths. P3 and P4 lands with later phases as
    fixtures surface them; this emitter falls back to P2
    behavior even for cases that would technically require
    P3/P4, leaving an over-80 line that the C1 emit+warn
    behavior will eventually flag. The current corpus has
    only P2 cases plus one P4 case (string-concat arg)
    that's addressed in Phase 5e.
    """
    args = [c for c in node.children if c.is_named]
    if not args:
        emitter.write("()")
        return

    # Source-preservation for already-wrapped argument lists.
    # When the source already spans multiple rows, preserve
    # the developer-authored layout verbatim rather than
    # collapsing then re-wrapping. This handles cases like
    # multi-line `executeQuery("SELECT ...")` arguments
    # inside a try-with-resources resource, where the source
    # layout encodes the spec's P4 form.
    if _node_spans_multiple_rows(node):
        emitter.write_raw_lines(_node_source_text(source, node))
        return

    # Capture column at start of `(` for paren-alignment.
    open_col = emitter.column
    emitter.write("(")
    cont_col = emitter.column  # column right after `(`

    # Measure P1 single-line width: open_col + 1 + sum(arg
    # widths) + 2*(n-1) + 1 (closing `)`).
    arg_texts = [_node_source_text(source, a) for a in args]
    arg_widths = [len(t) for t in arg_texts]
    # Reject P1 measurement when any arg has internal newlines
    # — those would render multi-line regardless. Treat as
    # "doesn't fit on one line" and fall through to P2.
    any_multiline_arg = any("\n" in t for t in arg_texts)
    p1_width = (
        open_col + 1 + sum(arg_widths) + 2 * (len(args) - 1) + 1
    )

    if not any_multiline_arg and p1_width <= _MAX_LINE:
        # P1: all args on one line.
        for index, arg in enumerate(args):
            if index > 0:
                emitter.write(", ")
            _emit_node(emitter, source, arg)
        emitter.write(")")
        return

    # P4: single-arg call whose arg is too long for the call
    # line. Per spec "Method Call Arguments / Priority 4":
    # line-break before the first arg; arg lands at
    # single-indent past the call's statement start. The
    # closing `)` stays on the arg's last line.
    if len(args) == 1:
        emitter.newline()
        emitter.push_indent()
        emitter.write_indent()
        _emit_node(emitter, source, args[0])
        emitter.write(")")
        emitter.pop_indent()
        return

    # P2: pack as many args as fit on the call line at the
    # paren-aligned continuation column. Greedily place args
    # on the current line; when the next arg would overflow,
    # break to a continuation line at `cont_col` and continue
    # placing args there.
    max_first_line = _MAX_LINE
    # `cont_col` doubles as the max-line-length budget for
    # continuation lines (each continuation prefix is
    # `cont_col` spaces, so the remaining budget is
    # `_MAX_LINE - cont_col` chars of content per line).
    for index, arg in enumerate(args):
        if index == 0:
            _emit_node(emitter, source, arg)
            continue
        # Compute the projected width of appending `, arg` to
        # the current line.
        projected = emitter.column + 2 + arg_widths[index]
        # If this is the last arg, also account for the
        # trailing `)` — we don't want to push it onto a new
        # line by itself.
        if index == len(args) - 1:
            projected += 1
        if projected <= max_first_line:
            emitter.write(", ")
            _emit_node(emitter, source, arg)
        else:
            # Break to the continuation line at cont_col.
            emitter.write(",")
            emitter.newline()
            emitter.write(" " * cont_col)
            _emit_node(emitter, source, arg)
    emitter.write(")")


def _emit_method_invocation(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `[OBJECT.]METHOD(ARGS)` on a single line.

    Grammar fields:
        - `object` (optional): the receiver expression
        - `name`: the method identifier
        - `arguments`: the `argument_list` node
        - `type_arguments` (optional): explicit `<T>` type
          witness — refused for now (lands with the generic-
          type-parameter phase)

    Like `_emit_argument_list`, this emits the single-line form
    unconditionally; the wrap-priority logic from the
    "Method Call Arguments" spec section lands in a later phase.
    """
    if node.child_by_field_name("type_arguments") is not None:
        raise NotImplementedError(
            "method_invocation with explicit type arguments "
            "(`obj.<Type>method(...)`) is not yet supported."
        )
    object_node = node.child_by_field_name("object")
    name_node = node.child_by_field_name("name")
    arguments_node = node.child_by_field_name("arguments")
    if name_node is None or arguments_node is None:
        raise NotImplementedError(
            "method_invocation missing 'name' or 'arguments' — "
            "grammar shape unexpected."
        )
    if object_node is not None:
        _emit_node(emitter, source, object_node)
        emitter.write(".")
    _emit_node(emitter, source, name_node)
    _emit_node(emitter, source, arguments_node)


def _emit_modifiers(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit a list of modifiers — annotations + keyword modifiers.

    Per the "Annotations" spec section (A3): each annotation
    on a declaration goes on its own line directly above the
    declaration, with no blank line between annotations or
    between the last annotation and the declaration.

    Keyword modifiers (`public`, `private`, `protected`,
    `static`, `final`, `abstract`, `volatile`, `synchronized`,
    `native`, `strictfp`, `transient`, `default`) emit inline
    space-separated. Modifier order is preserved from the
    source — the formatter does NOT reorder modifiers
    (checkstyle enforces the JLS conventional order
    separately).

    Caller contract: the caller has just emitted any
    preceding leading whitespace via `write_indent`. This
    emitter writes the annotations (one per line, each
    followed by `newline()` + `write_indent()`) and then the
    keyword modifiers followed by a single trailing space.
    The caller writes the next declaration token (e.g.
    `class Foo`, `int x`, `void m()`) directly without an
    intermediate `write(" ")` call.

    If only annotations are present (no keyword modifiers),
    the trailing `newline()` + `write_indent()` positions
    the caller's next token correctly on the line below the
    last annotation. If only keyword modifiers are present
    (no annotations), the trailing space positions the next
    token on the same line.
    """
    annotations: list[Node] = []
    keywords: list[str] = []
    for child in node.children:
        if child.is_named:
            annotations.append(child)
        else:
            keywords.append(child.type)

    for ann in annotations:
        _emit_node(emitter, source, ann)
        emitter.newline()
        emitter.write_indent()

    if keywords:
        emitter.write(" ".join(keywords))
        emitter.write(" ")


def _emit_variable_declarator(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `NAME` or `NAME = VALUE`, optionally wrapping at `=`.

    Spaces around `=` are spec-required (per "Whitespace and
    Operator Spacing"). When the single-line `NAME = VALUE;`
    form (accounting for the trailing `;` the caller will
    write) would exceed 80 chars, break BEFORE `=` per the
    spec's "Line Continuation / break before binary
    operators" rule. The `=` lands at the start of the
    continuation line, at the statement's start column + 4
    (single-indent past the statement start, NOT paren-
    aligned — paren-alignment doesn't apply to top-level
    `=` since there's no enclosing paren).

    Layout:

        TYPE NAME
            = VALUE;

    The continuation indent is computed from the EMITTER's
    current indent level (`indent_level * 4`) rather than
    the source's leading whitespace. This is correct because
    by the time `_emit_variable_declarator` is dispatched,
    the caller (field_declaration / local_variable_declar-
    ation) has already written the indent + modifiers +
    type, so the emitter's column reflects the source's
    "statement start + leading text".
    """
    name = node.child_by_field_name("name")
    value = node.child_by_field_name("value")
    if name is None:
        raise NotImplementedError(
            "variable_declarator missing 'name' field — grammar "
            "shape unexpected."
        )
    _emit_node(emitter, source, name)
    if value is None:
        return
    # Wrap-priority for assignment: prefer the cleanest single-
    # line form over wrapping the value internally. Order:
    #
    #   (1) Inline single-line: if `NAME = VALUE;` fits within
    #       80 chars (value rendered single-line), use it.
    #   (2) Break-at-`=` single-line: if `= VALUE;` at the
    #       continuation column fits, use the break form. The
    #       VALUE renders single-line on the continuation; the
    #       LHS gets its own line up through NAME.
    #   (3) Inline with value-wrap: fall back to letting the
    #       value emit its own wrap (method-call P2/P4, binary-
    #       expression wrap, etc.).
    value_text = _node_source_text(source, value)
    value_is_multiline = "\n" in value_text
    if not value_is_multiline:
        # Step 1: try inline single-line.
        cont_col = (emitter.indent_level + 1) * 4
        inline_width = (
            emitter.column + len(" = ") + len(value_text) + 1
        )
        if inline_width <= _MAX_LINE:
            emitter.write(" = ")
            _emit_node(emitter, source, value)
            return
        # Step 2: try break-at-`=` with single-line value.
        break_width = (
            cont_col + len("= ") + len(value_text) + 1
        )
        if break_width <= _MAX_LINE:
            emitter.newline()
            emitter.push_indent()
            emitter.write_indent()
            emitter.write("= ")
            _emit_node(emitter, source, value)
            emitter.pop_indent()
            return

    # Step 3 (and the multi-line-value path): emit inline and
    # let the value handle its own wrap.
    saved = emitter.snapshot()
    emitter.write(" = ")
    _emit_node(emitter, source, value)
    if value_is_multiline:
        return
    inline_overflow = (
        emitter.last_lines_max_width(saved[0]) > _MAX_LINE
        or len(emitter._current) + 1 > _MAX_LINE
    )
    if not inline_overflow:
        return
    # Backtrack and emit break-at-`=` even though the value
    # itself will wrap on the continuation line.
    emitter.restore(saved)
    emitter.newline()
    emitter.push_indent()
    emitter.write_indent()
    emitter.write("= ")
    _emit_node(emitter, source, value)
    emitter.pop_indent()


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
    "package_declaration": _emit_package_declaration,
    "import_declaration": _emit_import_declaration,
    "scoped_identifier": _emit_scoped_identifier,
    "class_declaration": _emit_class_declaration,
    "field_declaration": _emit_field_declaration,
    "variable_declarator": _emit_variable_declarator,
    "modifiers": _emit_modifiers,
    "line_comment": _emit_comment,
    "block_comment": _emit_comment,
    "marker_annotation": _emit_marker_annotation,
    "annotation": _emit_annotation,
    "annotation_argument_list": _emit_annotation_argument_list,
    "element_value_pair": _emit_element_value_pair,
    "method_declaration": _emit_method_declaration,
    "constructor_declaration": _emit_constructor_declaration,
    "static_initializer": _emit_static_initializer,
    "interface_declaration": _emit_interface_declaration,
    "enum_declaration": _emit_enum_declaration,
    "enum_constant": _emit_enum_constant,
    "wildcard": _emit_wildcard,
    "type_parameters": _emit_type_parameters,
    "type_parameter": _emit_type_parameter,
    "superclass": _emit_superclass,
    "super_interfaces": _emit_super_interfaces,
    "extends_interfaces": _emit_extends_interfaces,
    "method_reference": _emit_method_reference,
    "type_bound": _emit_type_bound,
    "lambda_expression": _emit_lambda_expression,
    "inferred_parameters": _emit_inferred_parameters,
    # `constant_declaration` shares its grammar shape with
    # `field_declaration` (optional modifiers + type +
    # variable_declarator(s) + `;`); reuse the existing
    # emitter.
    "constant_declaration": _emit_field_declaration,
    "throws": _emit_throws,
    "annotated_type": _emit_annotated_type,
    "formal_parameters": _emit_formal_parameters,
    "formal_parameter": _emit_formal_parameter,
    "spread_parameter": _emit_spread_parameter,
    "array_type": _emit_array_type,
    # `local_variable_declaration` has the same grammar shape
    # as `field_declaration` (optional modifiers + type +
    # variable_declarator(s) + `;`); share the emitter.
    "local_variable_declaration": _emit_field_declaration,
    "return_statement": _emit_return_statement,
    "expression_statement": _emit_expression_statement,
    "block": _emit_block,
    "if_statement": _emit_if_statement,
    "for_statement": _emit_for_statement,
    "enhanced_for_statement": _emit_enhanced_for_statement,
    "while_statement": _emit_while_statement,
    "do_statement": _emit_do_statement,
    "try_statement": _emit_try_statement,
    "try_with_resources_statement": _emit_try_with_resources_statement,
    "resource": _emit_resource,
    "catch_clause": _emit_catch_clause,
    "catch_formal_parameter": _emit_catch_formal_parameter,
    "catch_type": _emit_catch_type,
    "finally_clause": _emit_finally_clause,
    "throw_statement": _emit_throw_statement,
    "break_statement": _emit_break_statement,
    "continue_statement": _emit_continue_statement,
    "labeled_statement": _emit_labeled_statement,
    # --- Expression emitters ---
    "binary_expression": _emit_binary_expression,
    "unary_expression": _emit_unary_expression,
    "update_expression": _emit_update_expression,
    "parenthesized_expression": _emit_parenthesized_expression,
    "field_access": _emit_field_access,
    "instanceof_expression": _emit_instanceof_expression,
    "cast_expression": _emit_cast_expression,
    "method_invocation": _emit_method_invocation,
    "argument_list": _emit_argument_list,
    "assignment_expression": _emit_assignment_expression,
    "ternary_expression": _emit_ternary_expression,
    "object_creation_expression": _emit_object_creation_expression,
    "class_literal": _emit_class_literal,
    "array_initializer": _emit_array_initializer,
    "element_value_array_initializer": _emit_array_initializer,
    "array_creation_expression": _emit_array_creation_expression,
    "array_access": _emit_array_access,
    "dimensions": _emit_dimensions,
    "dimensions_expr": _emit_dimensions_expr,
    "synchronized_statement": _emit_synchronized_statement,
    "switch_expression": _emit_switch_expression,
    "switch_block": _emit_switch_block,
    "switch_rule": _emit_switch_rule,
    "switch_block_statement_group": _emit_switch_block_statement_group,
    "switch_label": _emit_switch_label,
    "yield_statement": _emit_yield_statement,
    "record_declaration": _emit_record_declaration,
    "compact_constructor_declaration": _emit_compact_constructor_declaration,
    "explicit_constructor_invocation": _emit_explicit_constructor_invocation,
    "generic_type": _emit_generic_type,
    "type_arguments": _emit_type_arguments,
    # Outer.Inner scoped type identifier — source text is the
    # canonical form; emit verbatim.
    "scoped_type_identifier": _emit_verbatim,
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

    Currently supported subset: a single top-level class with
    optional keyword modifiers (no annotations yet), no type
    parameters, no extends / implements / permits, whose body
    contains primitive- or named-typed field declarations with
    optional keyword modifiers and optional initializers, or
    method declarations whose bodies are zero-or-more simple
    statements. Supported initializer / expression shapes
    include literal values, identifiers, binary / unary /
    update / parenthesized expressions, field accesses, casts
    (no intersection types yet), non-pattern instanceof, and
    single-line method invocations (no explicit type witness,
    no wrap-priority logic yet). Supported statement shapes
    include `return_statement` (with or without a value),
    `expression_statement` (assignment-as-statement, method-
    call statement, update statement), `local_variable_-
    declaration` (with optional keyword modifiers), and
    `assignment_expression` (with space-space around any
    assignment operator).

    Method declarations may carry keyword modifiers, primitive-
    or named-typed return types (including `Type[]` arrays via
    `array_type`), and zero-or-more single-line formal
    parameters. Throws clauses, type parameters, abstract /
    interface methods, parameter annotations, and control-flow
    statements (`if`, `for`, `while`, `do`, `try`, `switch`)
    are NOT yet supported. Anything outside the supported
    subset raises `NotImplementedError` from the dispatcher
    (the explicit "this construct isn't supported yet"
    signal).

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
        "--format",
        metavar="FILE",
        type=Path,
        help=(
            "Format FILE and print the result to stdout. Useful "
            "for pre-flight diffs against consumer codebases "
            "before JDT removal. Combine with --write to rewrite "
            "the file in place, or with --check to exit non-zero "
            "if the file would be modified. Refused constructs "
            "(NotImplementedError) print a diagnostic to stderr "
            "and exit non-zero."
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=(
            "With --format, rewrite FILE in place instead of "
            "printing the formatted output to stdout. No effect "
            "without --format."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "With --format, exit 0 if the file is already "
            "spec-compliant, 1 if formatting would change it, "
            "2 on a parse error or refused construct. Does NOT "
            "write or print the formatted output."
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

    if args.format is not None:
        path = args.format
        if not path.is_file():
            print(
                f"format_java.py: ERROR: no such file: {path}",
                file=sys.stderr,
            )
            return 2
        source = path.read_bytes()
        try:
            formatted = format_source(source)
        except NotImplementedError as e:
            print(
                f"format_java.py: REFUSED: {path}: {e}",
                file=sys.stderr,
            )
            return 2
        except ValueError as e:
            print(
                f"format_java.py: PARSE ERROR: {path}: {e}",
                file=sys.stderr,
            )
            return 2
        if args.check:
            if formatted == source:
                return 0
            print(
                f"format_java.py: would reformat {path}",
                file=sys.stderr,
            )
            return 1
        if args.write:
            if formatted != source:
                path.write_bytes(formatted)
            return 0
        sys.stdout.buffer.write(formatted)
        return 0

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
