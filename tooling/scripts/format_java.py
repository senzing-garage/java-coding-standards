"""Canonical Java formatter for the senzing-garage standards.

This module is the AST-based replacement for the JDT+six-script
pipeline that shipped through 0.2.x. It parses each Java source file
to a tree-sitter-java CST and (eventually) emits spec-compliant text
directly per the rules in `docs/java-coding-standards.md`.

Status (Phase 2n — annotations on declarations):
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
      spec C7). Remaining control-flow constructs (`switch`,
      try-with-resources, `synchronized`) refuse until
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
        # `_emit_modifiers` emits its own trailing space (for
        # keyword modifiers) or its own trailing newline +
        # indent (for annotation-only modifiers), so the
        # caller does not write a separator here.
        _emit_node(emitter, source, modifiers_node)
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
    """
    children = node.children
    if len(children) != 3:
        raise NotImplementedError(
            f"binary_expression with {len(children)} children — "
            "expected exactly 3 (left, operator, right)."
        )
    left, op, right = children
    _emit_node(emitter, source, left)
    emitter.write(" ")
    emitter.write(op.type)
    emitter.write(" ")
    _emit_node(emitter, source, right)


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
    # Refuse throws clauses and type_parameters via the named-
    # children scan; also locate the optional modifiers child.
    modifiers_node: Node | None = None
    for child in node.named_children:
        if child.type == "throws":
            raise NotImplementedError(
                "method_declaration with throws clause is not "
                "yet supported; throws-clause wrapping lands in "
                "a later phase."
            )
        if child.type == "type_parameters":
            raise NotImplementedError(
                "method_declaration with type parameters "
                "(`<T> void m()`) is not yet supported; that "
                "construct lands with the generic-type phase."
            )
        if child.type == "modifiers":
            modifiers_node = child

    body = node.child_by_field_name("body")
    if body is None:
        raise NotImplementedError(
            "method_declaration without body (abstract / "
            "interface method) is not yet supported; interface "
            "bodies and abstract methods land in a later phase."
        )

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
    _emit_node(emitter, source, type_node)
    emitter.write(" ")
    _emit_node(emitter, source, name_node)
    _emit_node(emitter, source, parameters_node)
    emitter.newline()
    emitter.write_indent()
    emitter.write("{")
    emitter.newline()

    statements = list(body.named_children)
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

    Method-declaration bodies use the Allman form (opening `{`
    on its own line) and emit their body inline from
    `_emit_method_declaration` rather than dispatching here.
    """
    statements = list(node.named_children)
    emitter.write("{")
    emitter.newline()
    emitter.push_indent()
    for stmt in statements:
        emitter.write_indent()
        _emit_node(emitter, source, stmt)
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
    with the closing `}` of the preceding block (`} else {` or
    `} else if (...)`).

    Currently supports:
        - `if (cond) { ... }`
        - `if (cond) { ... } else { ... }`
        - `if (cond) { ... } else if (cond2) { ... } else { ... }`
          (else-if chains, recursive via the grammar's
          `alternative` field which can itself be an
          `if_statement`)

    Refuses:
        - The brace-less Tier 1 short-circuit form
          (`if (x) return;`) — the
          "Short-Circuit Conditionals" spec section's Tier 1
          handling lands in a later phase

    Known limitation until wrap-priority logic lands: the
    condition is always emitted on a single line. For a long
    compound boolean condition that the developer authored
    across multiple lines, the output collapses to one line
    which may exceed the 80-character limit. The spec's
    "Brace Placement / Exception: Multi-Line Conditions" rule
    (Allman `{` on its own line when the condition wraps) will
    be enforced when the wrap-priority machinery lands.

    Caller contract: the emitter ends mid-line at the final
    `}` (column = current indent + 1) so the caller's
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

    if consequence.type != "block":
        raise NotImplementedError(
            "if_statement with brace-less consequence "
            "(Tier 1 short-circuit form, e.g. `if (x) return;`) "
            "is not yet supported; short-circuit handling lands "
            "in the short-circuit-conditionals phase."
        )

    emitter.write("if ")
    _emit_node(emitter, source, condition)
    emitter.write(" ")
    _emit_node(emitter, source, consequence)

    if alternative is not None:
        if alternative.type == "if_statement":
            # else-if chain: dispatch the nested if_statement;
            # its emitter writes "if (...) { ... }" starting at
            # the current column (right after "} else ").
            emitter.write(" else ")
            _emit_node(emitter, source, alternative)
        elif alternative.type == "block":
            emitter.write(" else ")
            _emit_node(emitter, source, alternative)
        else:
            raise NotImplementedError(
                "if_statement with brace-less else alternative "
                f"({alternative.type!r}) is not yet supported."
            )


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
    """Emit `new TYPE(ARGS)`.

    Single space between the `new` keyword and the type, no
    space between the type and the argument list. Grammar
    fields: `type` (may be `type_identifier`, `generic_type`,
    or `scoped_type_identifier`) and `arguments`
    (`argument_list`).

    Refuses anonymous class bodies (`new Type() { ... }`),
    array creation (`new int[5]`), and explicit type arguments
    on the constructor call (`new <T>Foo(...)`) — those land
    with subsequent phases.
    """
    # Anonymous class body is exposed as a `class_body` named
    # child (no field name); refuse it explicitly. The
    # "Anonymous Classes" spec section (C8) needs its own
    # emitter with the expression-form same-line-brace rule.
    for child in node.named_children:
        if child.type == "class_body":
            raise NotImplementedError(
                "object_creation_expression with anonymous "
                "class body (`new Type() { ... }`) is not yet "
                "supported; that construct lands with the "
                "anonymous-classes phase."
            )
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
    emitter.write("new ")
    _emit_node(emitter, source, type_node)
    _emit_node(emitter, source, arguments)


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

    Same-line-brace control-flow form. Grammar fields:
    `condition` (parenthesized_expression) and `body` (block).
    """
    condition = node.child_by_field_name("condition")
    body = node.child_by_field_name("body")
    if condition is None or body is None or body.type != "block":
        raise NotImplementedError(
            "while_statement with missing fields or brace-less "
            "body is not yet supported."
        )
    emitter.write("while ")
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


def _emit_formal_parameters(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `(p1, p2, ...)` on a single line.

    Single-line form only for Phase 2g; the four-priority
    wrapping rules from the "Method and Constructor
    Declarations / Parameter Placement" spec section land in
    a later phase. Receivers (`@This Foo this`) and varargs
    (`Type... name`) are not yet supported and will surface
    via dispatch refusals from the per-parameter / per-type
    emitters.
    """
    params = [
        c for c in node.children
        if c.type == "formal_parameter"
    ]
    emitter.write("(")
    for index, param in enumerate(params):
        if index > 0:
            emitter.write(", ")
        _emit_node(emitter, source, param)
    emitter.write(")")


def _emit_formal_parameter(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `TYPE NAME` for a single formal parameter.

    Phase 2g refuses parameter modifiers and annotations
    (`@NonNull` etc.). The "Annotations on parameters" spec
    subsection's annotation+type-combo alignment rule lands
    with the annotation-emitter phase.
    """
    for child in node.named_children:
        if child.type == "modifiers":
            raise NotImplementedError(
                "formal_parameter with modifiers or annotations "
                "is not yet supported; that construct lands "
                "with the annotation phase."
            )
    type_node = node.child_by_field_name("type")
    name_node = node.child_by_field_name("name")
    if type_node is None or name_node is None:
        raise NotImplementedError(
            "formal_parameter missing 'type' or 'name' — "
            "grammar shape unexpected."
        )
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
    """Emit `(arg1, arg2, ...)` on a single line.

    Method-call argument-list WRAPPING (the priority 1 / 2 / 3
    / 4 rules from the "Method Call Arguments" spec section) is
    NOT yet implemented — this emitter always uses the
    single-line form. If the surrounding context makes the
    resulting line exceed 80 characters, the emitter still
    produces single-line output; the wrap-priority phase will
    add the column-aware logic that decides among the four
    priorities.
    """
    args = [c for c in node.children if c.is_named]
    emitter.write("(")
    for index, arg in enumerate(args):
        if index > 0:
            emitter.write(", ")
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
    "marker_annotation": _emit_marker_annotation,
    "annotation": _emit_annotation,
    "annotation_argument_list": _emit_annotation_argument_list,
    "element_value_pair": _emit_element_value_pair,
    "method_declaration": _emit_method_declaration,
    "formal_parameters": _emit_formal_parameters,
    "formal_parameter": _emit_formal_parameter,
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
