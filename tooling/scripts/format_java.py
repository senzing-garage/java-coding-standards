"""Canonical Java formatter for the senzing-garage standards.

This module is the AST-based formatter that replaced the JDT +
six-script pipeline used through 0.2.x. It parses each Java
source file to a tree-sitter-java CST and emits spec-compliant
text via a recursive node-emitter walk per the rules in
`docs/java-coding-standards.md`.

Architecture
------------

`Emitter` is the append-only output buffer. It tracks the
current column and indent level, strips trailing whitespace per
spec A5, and supports speculative emission via `snapshot()` /
`restore()` for the wrap-priority engine.

`_emit_node(emitter, source, node)` dispatches each CST node to
its registered emitter function via the `_NODE_EMITTERS` table.
Each emitter handles its own children — recursion is explicit,
no generic walker. Unknown node types raise `NotImplementedError`
with a "not yet supported" diagnostic; the dispatcher never
silently passes source text through.

Wrap priority — the engine handles overflow on:

- throws-clause types (single line → column-aligned one-per-
  line per spec).
- method-call argument lists (P1 single line → P2 two-line
  paren-aligned comma-packed → P4 next-line single-indent for
  single-arg overflow).
- variable_declarator initializers (inline single-line →
  break-at-`=` with single-line value → inline-with-value-wrap).
- class-header type parameters when the header overflows.
- binary expressions (break before the leftmost operator with
  cumulative +4 continuation indent per spec C3).
- multi-row source headers on while / for / method parameters
  (preserved verbatim; surrounding brace switches to Allman
  per the spec's multi-line-condition rule).
- Tier-1 short-circuit `if` collapse with width gating.

Coverage
--------

`format_source()` handles every Java construct exercised by
the 83 fixture pairs under `tooling/scripts/tests/fixtures/`
and every file in the senzing-commons-java consumer codebase
(106 files, 0 refusals). Constructs deliberately out-of-scope
for 0.3.0:

- `module_declaration` / `module-info.java` (no consumer
  project uses Java modules; a B-series spec section can be
  added later).
- Java text blocks (triple-quoted string literals) inside an
  indented context (i.e. appearing as a value inside a class
  or method body). The emitter refuses these with
  `NotImplementedError` so they surface a clear "not yet
  supported" diagnostic rather than emit mis-aligned output.
  Text blocks at top-level positions that re-indent cleanly
  still format. Indented-context support lands in a later
  release alongside spec B4 full enforcement.

Blank-line counts between class members are preserved from
the source (clamped at one) rather than rewritten to match the
spec A2 table. In practice consumer code already follows A2,
so this matches in calibration; strict A2 spec-enforcement is
planned for a later release.

CLI
---

End-user entry point is `format_file.py`, which invokes
`format_source()` in-process per file. This module's own CLI
(`python format_java.py ...`) supports:

    --check-grammar     Verify the tree-sitter-java grammar
                        loads and parses a trivial Java input.
    --parse FILE        Parse FILE and print a one-line
                        diagnostic.
    --format FILE       Format FILE and print the result to
                        stdout.
        --write         With --format: rewrite FILE in place.
        --check         With --format: exit 0 if compliant, 1
                        if formatting would change it, 2 on
                        parse error or refused construct.

The grammar and Python-binding versions are pinned in
`tooling/scripts/requirements.txt`; `GRAMMAR_VERSION` below
records the same pins as in-source constants for runtime
validation and diagnostics.

"""

from __future__ import annotations

import argparse
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final, TextIO

import tree_sitter_java
from tree_sitter import Language, Node, Parser, Tree


__version__: Final[str] = "0.7.0"

# Tree-sitter Python binding + tree-sitter-java grammar versions
# this formatter is calibrated against. Kept in sync with the pins
# in tooling/scripts/requirements.txt. Bumping requires a
# calibration-gate re-run; the emitter dispatches on grammar node
# names that can drift between grammar releases.
GRAMMAR_VERSION: Final[dict[str, str]] = {
    "tree-sitter": "0.26.0",
    "tree-sitter-java": "0.23.5",
}


def _load_java_language() -> Language:
    """Build a tree-sitter `Language` for Java.

    The `tree_sitter_java.language()` entry point returns the raw
    grammar pointer; wrapping it in `Language` is what the
    `Parser.language` setter expects.
    """
    return Language(tree_sitter_java.language())


JAVA_LANGUAGE: Final[Language] = _load_java_language()

# Per-thread Parser instances. `tree_sitter.Parser` is not
# documented as safe to share across threads — its internal scratch
# buffers are reused across parse calls. We lazy-construct one
# instance per thread so concurrent callers (pytest-xdist, parallel
# batch formatters, in-process web services) don't trip over each
# other. `Parser(JAVA_LANGUAGE)` is cheap so the first parse on a
# new thread pays only a small one-time cost.
_PARSER_LOCAL: Final[threading.local] = threading.local()


def _thread_parser() -> Parser:
    """Return this thread's `Parser` instance, constructing one
    on first use.
    """
    p = getattr(_PARSER_LOCAL, "parser", None)
    if p is None:
        p = Parser(JAVA_LANGUAGE)
        _PARSER_LOCAL.parser = p
    return p


# Spec line-length limit. Used throughout the wrap-priority
# engine and the javadoc-reflow helpers.
_MAX_LINE: Final[int] = 80


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
    return _thread_parser().parse(source)


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


@dataclass(frozen=True, slots=True)
class FormatterWarning:
    """A non-blocking advisory emitted during formatting.

    Reported when the formatter detects a layout corner case
    it cannot fully canonicalize and the developer is the only
    party who can resolve it — e.g. a source-preserved arg
    list whose continuation columns sit below the current
    indent because the contained string literal would need to
    be split into smaller concatenated chunks (a code change,
    not a formatting choice).

    Line / column are 1-indexed for direct comparison with
    editor / `grep` output.
    """

    line: int
    column: int
    message: str


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

    __slots__ = (
        "_lines",
        "_current",
        "_indent",
        "_tail_reserve",
        "_paren_align_col",
        "_paren_expr_col",
        "_arg_list_p4_fired",
        "_array_init_inline_only",
        "_anchor_escaped",
        "_raw_rows_emitted",
        "warnings",
    )

    def __init__(self) -> None:
        self._lines: list[str] = []
        self._current: str = ""
        self._indent: int = 0
        # Collected formatter warnings — non-blocking advisories
        # about layout corner cases the formatter can't fully
        # canonicalize (e.g. a source-preserved arg list whose
        # continuation columns are below the current indent
        # because the contained string literal can't be split
        # without a code change). The CLI prints these to stderr
        # after each file so adopters know which spots warrant
        # manual cleanup.
        self.warnings: list[FormatterWarning] = []
        # Chars to reserve at the end of the current line for
        # trailing context the wrap candidates can't see — e.g.
        # `) {` after an `if` condition, `);` after a call inside
        # an expression_statement. Set by callers via the
        # `tail_reserve` context manager around speculative emits;
        # consulted by wrap candidates whose overflow check would
        # otherwise commit at exactly `_MAX_LINE` and let the
        # trailing tokens push the line past the limit.
        self._tail_reserve: int = 0
        # When an expression is wrapped in grouping parentheses,
        # this records the column immediately after the opening
        # `(` so an inner binary / ternary / chain emitter can
        # paren-align its operator continuations per spec C6
        # ("Parenthesized-expression operator continuation").
        # `None` means no enclosing grouping paren is in scope;
        # wrap candidates use the standard cumulative `+4` indent
        # in that case.
        #
        # `_paren_align_col` serves dual duty (dating from 0.5.0
        # item 10, the spec C6 extension to method/constructor
        # call parens): it is ALSO set by `_emit_argument_list`'s
        # single-arg binary-expression case so the inner binary
        # can paren-align to the call's `(`. Anchors that need to
        # discriminate grouping parens from method-call parens
        # (e.g. `emit_p4_single_arg`'s 0.6.0 paren-deference rule)
        # consult `_paren_expr_col` instead, which is set ONLY by
        # `_emit_parenthesized_expression`.
        self._paren_align_col: int | None = None
        # Column immediately after the opening `(` of the
        # innermost enclosing `parenthesized_expression`. Distinct
        # from `_paren_align_col`: this field is set ONLY by
        # `_emit_parenthesized_expression` — never by the item 10
        # extension inside `_emit_argument_list`. Consulted by
        # `emit_p4_single_arg`'s single-arg P4 fallback so the
        # continuation column can defer to the grouping paren
        # that owns the arg (0.6.0 P0 rule), while ignoring
        # method-call parens for that purpose.
        self._paren_expr_col: int | None = None
        # 0.6.0: flag set to True inside
        # `_emit_argument_list`'s P4 candidates
        # (`emit_p4_multi_arg`, `emit_p4_single_arg_block_indent`)
        # whenever they fire. Consulted by the binary-expression
        # wrap engine (`emit_greedy`, `emit_paren_aligned`) to
        # reject paren-alignment when an operand's emission
        # cascaded through arg-list P4 (leaf-arg wrap).
        # Distinguishes "operand wrapped via arg-list P4"
        # (paren-align rejects → falls to +4-greedy compact
        # shape) from "operand wrapped via nested
        # binary/chain/ternary" (paren-align commits, spec C6
        # behavior preserved). The pre-0.6 `_operand_emitted
        # _shallow_line` check was tied to arg-list P4's
        # `block+4` orphan pattern; when arg-list P4's anchor
        # changes (e.g. to `line-start-col + 4`), the shallow-
        # line signal misses. This flag is a direct signal
        # instead of an indirect visual-symptom heuristic.
        #
        # Ownership: sites that read the flag do a
        # save-reset-check-restore cycle around the emission
        # they care about (see `_emit_binary_expression`).
        # Sites that set it (arg-list P4 candidates) just set
        # it to True — they never reset. This gives the read
        # site full control of scoping.
        self._arg_list_p4_fired: bool = False
        # 0.7.0: set when an argument list commits its
        # block-relative last-resort anchor, which has no
        # relationship to the `(` it belongs to. Read by the
        # variable-declarator cascade to backtrack to
        # break-at-`=`, where the construct starts shallow
        # enough that the last resort is not reached.
        self._anchor_escaped: bool = False
        # Set whenever an emit replays source rows verbatim through
        # `write_raw_lines`. Readers save-reset-check-restore, like
        # `_arg_list_p4_fired`. Distinguishes "this construct wrapped"
        # from "this construct's rows came out of the source", which
        # look identical in `line_count` but mean opposite things to a
        # wrap decision.
        self._raw_rows_emitted: bool = False
        # 0.6.0: when True, `_emit_array_initializer` emits the
        # single-line inline form unconditionally rather than
        # running its own multi-line cascade. Callers that are
        # themselves speculating a single-line shape (the
        # variable-declarator / assignment-expression cascade's
        # Step 1 "inline all" and Step 2 "break at `=`, array
        # still inline" attempts) set this True; the outer
        # width check then rejects the speculation cleanly
        # without the array committing to a multi-line P3/P4
        # shape that would only have been discarded.
        self._array_init_inline_only: bool = False

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
        self._lines.append(self._current.rstrip(" \t"))
        self._current = ""

    @property
    def tail_reserve(self) -> int:
        """Chars currently reserved at the end of the line for
        unseen trailing context (e.g. `) {` after an `if`'s
        condition). Wrap candidates that fit at exactly
        `_MAX_LINE - tail_reserve` commit; anything wider is
        overflow even if it would fit at `_MAX_LINE`.
        """
        return self._tail_reserve

    def set_tail_reserve(self, value: int) -> int:
        """Set the tail-reserve and return the previous value
        so the caller can restore it via `set_tail_reserve(...)`
        again. Pair with a try/finally to handle exceptions.
        """
        previous = self._tail_reserve
        self._tail_reserve = value
        return previous

    @property
    def paren_align_col(self) -> int | None:
        """The column immediately after an enclosing grouping
        `(` if one is in scope, else `None`. Set by
        `_emit_parenthesized_expression` around its inner emit;
        consulted by `_emit_binary_expression` to enable the
        spec C6 paren-aligned operator-continuation candidate.
        """
        return self._paren_align_col

    @property
    def paren_expr_col(self) -> int | None:
        """The column immediately after the innermost enclosing
        `parenthesized_expression`'s `(`, or `None`.

        Set ONLY by `_emit_parenthesized_expression`. Unlike
        `paren_align_col` (which item 10 also sets from
        `_emit_argument_list`'s single-arg binary path), this
        field discriminates grouping/control-flow parens from
        method-call parens — used by `emit_p4_single_arg`'s
        0.6.0 paren-deference rule.
        """
        return self._paren_expr_col

    def set_paren_expr_col(self, value: int | None) -> int | None:
        """Set `paren_expr_col` and return the previous value.
        Pair with a try/finally so nested emits restore cleanly.
        """
        previous = self._paren_expr_col
        self._paren_expr_col = value
        return previous

    def set_paren_align_col(self, value: int | None) -> int | None:
        """Set `paren_align_col` and return the previous value
        so the caller can restore it via the symmetric call.
        Pair with a try/finally to handle exceptions.
        """
        previous = self._paren_align_col
        self._paren_align_col = value
        return previous

    def snapshot(
        self,
    ) -> tuple[
        int, str, int, int, int | None, int | None, bool, bool, bool,
        bool, int
    ]:
        """Capture the emitter state for speculative emission.

        Returns a tuple `(lines_count, current, indent,
        tail_reserve, paren_align_col, paren_expr_col,
        arg_list_p4_fired, array_init_inline_only,
        anchor_escaped, warnings_count)` suitable for
        `restore()`. The
        wrap-priority engines use the pattern:

            saved = emitter.snapshot()
            <try emitting in some shape>
            if overflowed:
                emitter.restore(saved)
                <emit in the next-priority shape>

        Cheap because the lines / warnings lists are immutable
        from the perspective of restore (we capture their
        lengths, not their contents). `tail_reserve` is
        included so a candidate that adjusts it via
        `set_tail_reserve()` without using try/finally still
        restores cleanly on backtrack. `warnings_count` is
        included so any `FormatterWarning` appended during a
        speculative emit that subsequently rolls back is
        removed — otherwise a rejected P1 candidate's warnings
        would linger and produce spurious advisories even when
        the committed P2/P3 layout doesn't trigger them.
        `arg_list_p4_fired` is included so speculative emits
        that trigger arg-list P4 rollback cleanly for the
        outer wrap engine to make its P4-vs-not decision on
        the eventually-committed candidate.
        `array_init_inline_only` is included so callers that
        set it for a speculative inline emit have it restored
        cleanly on rollback.
        """
        return (
            len(self._lines),
            self._current,
            self._indent,
            self._tail_reserve,
            self._paren_align_col,
            self._paren_expr_col,
            self._arg_list_p4_fired,
            self._array_init_inline_only,
            self._anchor_escaped,
            self._raw_rows_emitted,
            len(self.warnings),
        )

    def restore(
        self,
        snap: tuple[
            int, str, int, int, int | None, int | None, bool, bool,
            bool, bool, int
        ],
    ) -> None:
        """Restore a previously-captured state from `snapshot()`.

        Truncates the lines and warnings lists back to their
        captured lengths and resets the current line, indent,
        tail reserve, and paren-align columns. Any text emitted
        — and any warnings appended — after the snapshot are
        discarded.
        """
        (
            lines_count,
            current,
            indent,
            tail_reserve,
            paren_align_col,
            paren_expr_col,
            arg_list_p4_fired,
            array_init_inline_only,
            anchor_escaped,
            raw_rows_emitted,
            warnings_count,
        ) = snap
        del self._lines[lines_count:]
        self._current = current
        self._indent = indent
        self._tail_reserve = tail_reserve
        self._paren_align_col = paren_align_col
        self._paren_expr_col = paren_expr_col
        self._arg_list_p4_fired = arg_list_p4_fired
        self._array_init_inline_only = array_init_inline_only
        self._anchor_escaped = anchor_escaped
        self._raw_rows_emitted = raw_rows_emitted
        del self.warnings[warnings_count:]

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

    def write_raw_lines(
        self, text: str, *, strip_trailing_ws: bool = False
    ) -> None:
        """Append text that may contain newlines, preserved verbatim.

        Used by leaf emitters for content the formatter must
        reproduce byte-for-byte — text blocks ("Text Blocks /
        Content preservation" spec section) and eventually block
        comments. With the default `strip_trailing_ws=False`,
        newlines inside `text` finalize each intermediate line
        WITHOUT stripping trailing whitespace, since that
        whitespace is the developer's content (the spec's
        "Normalize spacing or alignment of content is a no-op"
        rule applies to text-block contents).

        Source-preserved CODE (argument-list verbatim preservation,
        mid-statement-comment preservation, etc.) is not
        whitespace-significant content — trailing whitespace
        there is just stray bytes the source author left behind
        and the spec's "Trailing Whitespace" rule applies. Such
        callers pass `strip_trailing_ws=True` to apply the same
        `rstrip(" \t")` that `newline()` does on its finalized
        lines.

        The in-progress line at the END of `text` (the part after
        the last newline) is left open so subsequent `write()` /
        `newline()` calls continue normally.
        """
        # Any caller of this method is replaying source bytes rather
        # than laying content out, so the rows it produces are not a
        # wrap. Wrap decisions that count rows must be able to tell
        # the difference.
        self._raw_rows_emitted = True
        parts = text.split("\n")
        # First segment continues the current line.
        self._current += parts[0]
        for part in parts[1:]:
            if strip_trailing_ws:
                self._lines.append(self._current.rstrip(" \t"))
            else:
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
            self._lines.append(self._current.rstrip(" \t"))
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
# Wrap-priority engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WrapContext:
    """Indent + column context passed down through speculative
    wrap emitters.

    Replaces ad-hoc `start_col` parameters scattered through the
    per-construct wrap helpers. Threaded by callers like
    `_emit_method_header_wrapped`, `_emit_class_header_wrapped`,
    and `_emit_argument_list` to make their continuation-column
    arithmetic uniform.

    Fields:
        start_col: column where the current construct began
            (e.g. column of `class`, `void`, the `(` of a call).
        indent_col: continuation indent for this construct
            (typically `start_col + 4`).
        p3_indent_col: next-line "P3" fallback column when a
            paren-aligned continuation column would itself
            overflow (typically `start_col + 8`).

    Future enhancement: a `parent` pointer for nested
    speculation, added the first time a wrap candidate needs
    to know the outer construct's remaining budget.
    """

    start_col: int
    indent_col: int
    p3_indent_col: int

    @classmethod
    def at(cls, start_col: int) -> "WrapContext":
        """Build a context with the conventional `+4` / `+8`
        offsets from `start_col`.

        Most callers use this; pass explicit fields only when a
        construct wants a non-conventional continuation column.
        """
        return cls(
            start_col=start_col,
            indent_col=start_col + 4,
            p3_indent_col=start_col + 8,
        )


def try_priorities(
    emitter: Emitter,
    candidates: list[Callable[[], None]],
) -> int:
    """Try each emit thunk in turn; commit the first one whose
    output keeps every line at or under `_MAX_LINE -
    emitter.tail_reserve`.

    Each `candidate` is a zero-argument callable that emits via
    `emitter`. Between candidates the buffer is rolled back to
    the state at entry, so partially-emitted output from a
    failed attempt is invisible to callers.

    The effective max is `_MAX_LINE - emitter.tail_reserve` so
    that wrap decisions inside an enclosing context (an `if`
    condition, an expression statement, etc.) account for the
    trailing tokens (`) {`, `;`, ...) the candidate can't see.

    Returns the 0-based index of the candidate that committed:

        - The first candidate whose final line widths stay
          within the effective max, OR
        - `len(candidates) - 1` if every candidate overflowed.
          The last candidate's emission is left committed in
          that case — this is the spec C1 "emit + warn" fallback,
          which prefers a visible LineLength violation over a
          formatter refusal.

    Callers do not need to call `snapshot()` themselves; this
    helper manages the speculative buffer entirely.

    Callers MUST provide at least one candidate. An empty
    `candidates` list is a programming error and raises
    `ValueError` — the spec C1 emit-and-warn fallback only
    makes sense when there's something to emit.
    """
    if not candidates:
        raise ValueError(
            "try_priorities() requires at least one candidate"
        )
    initial = emitter.snapshot()
    last_index = len(candidates) - 1
    # `effective_max` is captured once because `initial`
    # already carries the tail_reserve in effect at entry,
    # and `restore(initial)` at the top of each loop
    # iteration resets tail_reserve to that same value —
    # so the cap stays consistent across all attempts even
    # if a misbehaving candidate adjusts tail_reserve
    # internally without unwinding it.
    effective_max = _MAX_LINE - emitter.tail_reserve
    for index, fn in enumerate(candidates):
        emitter.restore(initial)
        speculative = emitter.snapshot()
        fn()
        max_width = emitter.last_lines_max_width(speculative[0])
        if max_width <= effective_max:
            return index
    # Spec C1 emit-and-warn: the last candidate is left
    # committed even though its lines overflow. Callers that
    # want a `FormatterWarning` advisory invoke
    # `_fire_wrap_overflow_advisory(emitter, node,
    # cascade_start, label)` AFTER `try_priorities` returns —
    # the advisory describes only the committed candidate's
    # lines, since speculative emits rolled back during the
    # cascade have their warnings truncated by `restore()`.
    return last_index


def _fire_wrap_overflow_advisory(
    emitter: "Emitter",
    node: "Node",
    since_line_count: int,
    site_label: str,
    remedy: str | None = None,
) -> None:
    """Fire a `FormatterWarning` when this wrap site's
    committed emit produced any on-disk line wider than
    `_MAX_LINE`. Per-line accounting applies: finalized lines
    are checked at their literal width, while only the
    in-progress `_current` line gets `+ tail_reserve` added
    (representing the trailing chars the parent will append
    after this wrap returns).

    Called at the terminal commit point of every wrap-engine
    cascade (binary / ternary / method-chain / arg-list) — the
    "spec C1 emit + warn" exit. Speculative emits earlier in
    the cascade that overflowed but rolled back via
    `snapshot()` / `restore()` don't fire this — their
    `warnings` appended would be truncated by `restore()`. The
    advisory therefore describes only the line(s) the
    formatter actually committed and could not shrink further.

    `remedy` overrides the closing sentence for sites where the
    default advice does not apply — a preserved javadoc line has
    no operand to split, so telling the developer to split one
    sends them looking for something that isn't there.

    `site_label` names the wrap engine for the message (e.g.
    `"binary expression"`, `"ternary expression"`,
    `"method chain"`, `"argument list"`); the message tells
    the developer that no break-point in the cascade fit and
    that the only resolution is a source-code change (split a
    literal, rename a long operand, restructure the
    expression).
    """
    # The wrap engine uses `_MAX_LINE - tail_reserve` as its
    # commit gate (be conservative because the parent may
    # append tail chars to the in-progress line). The on-disk
    # width is different: every line is rendered verbatim, and
    # ONLY the in-progress `_current` line will receive
    # `tail_reserve` chars from the parent. The advisory must
    # match what checkstyle's LineLength check will actually
    # see, so compute per-line on-disk widths instead of
    # uniformly applying `tail_reserve` to every line.
    max_finalized_width = 0
    for line in emitter._lines[since_line_count:]:
        if len(line) > max_finalized_width:
            max_finalized_width = len(line)
    current_on_disk = len(emitter._current) + emitter.tail_reserve
    max_on_disk = max(max_finalized_width, current_on_disk)
    if max_on_disk <= _MAX_LINE:
        return
    # Deduplicate: a wrap engine that contains another wrap engine
    # which already fired (e.g. an argument list containing a
    # binary expression that exhausted its own cascade) inherits
    # the inner advisory and shouldn't double-fire. Suppress when
    # any existing advisory's source line falls inside this
    # node's line range — the inner advisory is more specific
    # (a smaller source span) so it's the more actionable
    # pointer for the developer.
    my_start_line = node.start_point[0] + 1
    my_end_line = node.end_point[0] + 1
    for existing in emitter.warnings:
        if my_start_line <= existing.line <= my_end_line:
            return
    if remedy is None:
        remedy = (
            "Split a long operand or literal so the wrap engine "
            "has a break point that fits the line limit."
        )
    emitter.warnings.append(FormatterWarning(
        line=node.start_point[0] + 1,
        column=node.start_point[1] + 1,
        message=(
            f"{site_label} wrap could not fit within "
            f"{_MAX_LINE} chars (max line width "
            f"{max_on_disk}). {remedy}"
        ),
    ))


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


_CSOFF_SCOPE_TYPES: Final[frozenset[str]] = frozenset({
    "block",
    "class_body",
    "interface_body",
    "enum_body",
    "constructor_body",
    "program",
    # Switch bodies need their own entry: a `// CSOFF` placed
    # inside one `case` of an old-style colon-form switch must
    # NOT bleed into subsequent cases. Without these scope
    # entries the walk-up would halt at the enclosing method
    # `block` and find a stale-but-still-open CSOFF marker.
    "switch_block",
    "switch_block_statement_group",
})


def _is_inside_csoff_region(source: bytes, node: Node) -> bool:
    """Return True if `node` sits inside an unbalanced
    `// CSOFF` / `// CSON` region.

    Used by the source-preserve gate in `_emit_argument_list`
    (and other multi-line emitters) to force verbatim emission
    of deliberately-aligned multi-line content per the spec's
    "Formatted Log and Diagnostic Messages" section. When the
    developer has wrapped a region with CSOFF / CSON markers,
    the formatter must NOT re-flow on column boundaries —
    doing so would destroy the alignment the markers were
    placed to protect.

    Detection: walk up to the enclosing block-like scope, then
    scan source bytes from the start of that scope through
    `node.start_byte` counting `// CSOFF` (or `// CHECKSTYLE`)
    versus `// CSON` (or matching closing) markers. A positive
    nesting depth means we're inside an open region.
    """
    scope = node.parent
    while scope is not None and scope.type not in _CSOFF_SCOPE_TYPES:
        scope = scope.parent
    if scope is None:
        return False
    text = source[scope.start_byte:node.start_byte].decode(
        "utf-8", errors="replace"
    )
    depth = 0
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("//"):
            continue
        content = stripped[2:].lstrip()
        if content.startswith(("CSOFF", "CHECKSTYLE:OFF")):
            depth += 1
        elif content.startswith(("CSON", "CHECKSTYLE:ON")):
            if depth > 0:
                depth -= 1
    return depth > 0


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
        if text.startswith('"""') and text.rstrip().endswith('"""'):
            _emit_text_block(emitter, text)
            return
        if emitter.indent_level > 0:
            raise NotImplementedError(
                f"Multi-line {node.type!r} inside an indented "
                "context is not yet supported."
            )
        emitter.write_raw_lines(text)
    else:
        emitter.write(text)


def _emit_text_block(emitter: Emitter, text: str) -> None:
    """Emit a Java triple-quoted text block (spec B4).

    The opening `\"\"\"` ends the line that introduces it (after
    `=`, `(`, `,`, `return`, etc.); the closing `\"\"\"` sits on
    its own line at +4 from the introducing statement's column
    (single-indent past the statement). Content lines are at
    the same column as the closing `\"\"\"` or further right.

    Content preservation: lines are re-emitted byte-for-byte
    EXCEPT for a uniform shift of leading whitespace so the
    closing-`\"\"\"` column matches the new indent context.
    Per JLS § 3.10.6 ("Incidental White Space"), all non-blank
    content lines have leading whitespace ≥ the closing
    delimiter's column, so a single delta shifts every line
    consistently and preserves the rendered string verbatim.
    Blank lines stay blank (they're stripped by the compiler's
    incidental-whitespace removal regardless of any leading
    whitespace they carry).
    """
    lines = text.split("\n")
    if len(lines) < 2:
        emitter.write_raw_lines(text)
        return
    closing_line = lines[-1]
    closing_indent = len(closing_line) - len(
        closing_line.lstrip(" ")
    )
    # The target column for the closing `"""` is one indent
    # level deeper than the introducing statement. The
    # introducing statement sits at the current emitter indent
    # level (we're called mid-line, just after `=`/`(`/etc.),
    # so the closing delimiter goes at `+4` of that level.
    new_indent = (emitter.indent_level + 1) * 4
    delta = new_indent - closing_indent
    if delta == 0:
        emitter.write_raw_lines(text)
        return

    adjusted = [lines[0]]
    for line in lines[1:]:
        if line.strip() == "":
            # Blank content line — preserve as empty. JLS
            # incidental-whitespace stripping discards any
            # leading whitespace on blank lines anyway, so
            # they don't need shifting and keeping them empty
            # avoids the spec A5 "trailing whitespace forbidden"
            # interaction.
            adjusted.append("")
        elif delta > 0:
            adjusted.append(" " * delta + line)
        elif delta < 0:
            # Remove `-delta` leading spaces. Valid Java text
            # blocks always have content lines with leading
            # whitespace ≥ the closing-delimiter column per
            # JLS § 3.10.6 ("Incidental White Space"), so this
            # is safe — the `lstrip` fallback covers malformed
            # inputs that wouldn't compile anyway. The compiler
            # will reject any source where a content line is
            # indented less than the closing `"""`; the
            # formatter just avoids crashing on it so the rest
            # of the file can still be processed.
            stripped = line.lstrip(" ")
            leading = len(line) - len(stripped)
            if leading >= -delta:
                adjusted.append(line[-delta:])
            else:
                adjusted.append(stripped)
    emitter.write_raw_lines("\n".join(adjusted))


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
    if emitter.last_lines_max_width(saved[0]) > _MAX_LINE:
        # Overflow — backtrack and rewrap. Use last_lines_max_width
        # rather than just emitter.column so internal multi-line
        # source-preservation (super_interfaces / type_parameters
        # that span rows in the source) still triggers the wrap
        # when any of those rendered lines exceeded 80 chars.
        emitter.restore(saved)
        _emit_class_header_wrapped(
            emitter,
            source,
            type_parameters_node,
            superclass_node,
            super_interfaces_node,
            WrapContext.at(start_col),
        )

    emitter.newline()
    emitter.write_indent()
    emitter.write("{")
    emitter.newline()
    if body is not None:
        _emit_class_body_members(emitter, source, body)
    emitter.write_indent()
    emitter.write("}")


def _emit_extends_implements_p2_p3(
    emitter: Emitter,
    source: bytes,
    superclass_node: Node | None,
    super_interfaces_node: Node | None,
    cont_indent: str,
) -> None:
    """Emit `extends X` and `implements Y, Z` clauses on
    continuation line(s) per the spec B1 P2/P3 cascade.

    Speculatively emits the P2 form (both clauses on a single
    continuation line after a newline at `cont_indent`); on
    overflow, backtracks and emits P3 (each clause on its own
    continuation line, each at `cont_indent`).

    Caller has already positioned the emitter at the column
    where the continuation should begin (typically right after
    `class NAME` or after the closing `>` of a wrapped
    type-parameter block). This helper writes the leading
    newline(s); it does NOT write a trailing newline.
    """
    has_extends = superclass_node is not None
    has_implements = super_interfaces_node is not None
    if not has_extends and not has_implements:
        return

    # P2: both clauses on a single continuation line.
    attempt = emitter.snapshot()
    emitter.newline()
    emitter.write(cont_indent)
    if has_extends:
        _emit_node(emitter, source, superclass_node)
        if has_implements:
            emitter.write(" ")
    if has_implements:
        _emit_node(emitter, source, super_interfaces_node)
    if emitter.last_lines_max_width(attempt[0]) <= _MAX_LINE:
        return

    # P3: each clause on its own continuation line.
    emitter.restore(attempt)
    if has_extends:
        emitter.newline()
        emitter.write(cont_indent)
        _emit_node(emitter, source, superclass_node)
    if has_implements:
        p3_impl_saved = emitter.snapshot()
        emitter.newline()
        emitter.write(cont_indent)
        _emit_node(emitter, source, super_interfaces_node)
        if emitter.last_lines_max_width(p3_impl_saved[0]) > _MAX_LINE:
            # P4: implements clause still overflows on its own
            # line (a class implementing 3+ long-named interfaces
            # exceeds 80 chars even after breaking `implements`
            # onto its own continuation line). Break each
            # interface onto its own line, paren-aligned under
            # the first interface's column
            # (`cont_indent + len("implements ")`), matching the
            # shape a developer would author by hand.
            #
            # 0.6.0 P0 consumer trial surfaced this on
            # `DataMartReportsServices.java` — 4 interfaces
            # totaling 138 chars collapsed into a 142-char P3
            # line. This P4 tier drops each interface to its
            # own line.
            emitter.restore(p3_impl_saved)
            _emit_super_interfaces_broken(
                emitter, source, super_interfaces_node, cont_indent
            )


def _require_type_list(
    node: Node, container_name: str
) -> list[Node]:
    """Return the named children of `node`'s `type_list` child.

    Shared helper for the three interface-clause emitters
    (`_emit_extends_interfaces`, `_emit_super_interfaces`,
    `_emit_super_interfaces_broken`) which all need the same
    "find the `type_list` child, raise `NotImplementedError` if
    missing" lookup. `container_name` is the outer node type
    (e.g. `"super_interfaces"`) used in the error message so
    the traceback names the actual grammar node that surprised
    us.
    """
    for c in node.named_children:
        if c.type == "type_list":
            return list(c.named_children)
    raise NotImplementedError(
        f"{container_name} missing 'type_list' child — grammar "
        "shape unexpected."
    )


def _emit_super_interfaces_broken(
    emitter: Emitter,
    source: bytes,
    super_interfaces_node: Node,
    cont_indent: str,
) -> None:
    """Emit `implements X, Y, Z, W` with each interface on its own
    continuation line. First interface stays on the `implements`
    line; subsequent interfaces align under the first interface's
    column (paren-align to `implements `).

    Called as the P4 fallback in
    `_emit_extends_implements_p2_p3` when the P3 single-line
    implements clause overflows 80 chars.
    """
    types = _require_type_list(
        super_interfaces_node, "super_interfaces"
    )
    emitter.newline()
    emitter.write(cont_indent)
    emitter.write("implements ")
    align_col = emitter.column
    for index, t in enumerate(types):
        if index > 0:
            emitter.write(",")
            emitter.newline()
            emitter.write(" " * align_col)
        _emit_node(emitter, source, t)


def _emit_class_header_wrapped(
    emitter: Emitter,
    source: bytes,
    type_parameters_node: Node | None,
    superclass_node: Node | None,
    super_interfaces_node: Node | None,
    ctx: WrapContext,
) -> None:
    """Emit the type-parameter / extends / implements portion of a
    class declaration in wrapped form. Caller has already emitted
    `[modifiers] class NAME`; this function appends the type-
    parameter list (with wrap) and the extends / implements
    clauses.

    The wrap shape: the first type-parameter stays on the class
    declaration line (right after `<`). Subsequent type-parameters
    each go on their own continuation line at `ctx.indent_col`
    (single-indent past the class start). The closing `>` ends
    the last type-parameter's line, followed by ` extends X` and
    ` implements Y, Z` (which stay on that same line if they fit).
    """
    cont_indent = " " * ctx.indent_col
    if type_parameters_node is not None:
        params = [
            c for c in type_parameters_node.named_children
            if c.type == "type_parameter"
        ]
        # Type-parameter shape selection:
        #
        #   - P2 (first param on the class declaration line,
        #     subsequent params on continuation lines): tried
        #     first. Compact for short first params.
        #   - P3 (break right after `<`, every param on its own
        #     continuation line): used when P2's first line would
        #     overflow because the first type parameter is itself
        #     too long.
        #
        # Without P3, a class whose FIRST type parameter is the
        # long one cannot be brought under 80 chars by the
        # formatter — the adopter is forced to a manual CSOFF
        # suppression, which the spec forbids as a general
        # escape hatch.
        attempt = emitter.snapshot()
        emitter.write("<")
        for index, p in enumerate(params):
            if index > 0:
                emitter.write(",")
                emitter.newline()
                emitter.write(cont_indent)
            _emit_node(emitter, source, p)
        emitter.write(">")
        # Honor `tail_reserve` for consistency with the other
        # manual P1/P2/P3 sites (`_emit_binary_expression`,
        # `_emit_method_chain_wrapped`, `_emit_resource`).
        # No runtime impact today — class declarations are
        # never inside a tail-reserved context — but the
        # pattern stays uniform.
        p2_effective_max = _MAX_LINE - emitter.tail_reserve
        if emitter.last_lines_max_width(attempt[0]) > p2_effective_max:
            # P2 overflowed — emit P3 instead. Each param on
            # its own continuation line at `cont_indent`; the
            # `<` ends the class declaration line.
            #
            # P3 is the terminal candidate per spec C1
            # ("emit + warn"): there is no further fallback,
            # so a single type parameter wider than 76 chars
            # commits unconditionally and surfaces as a
            # checkstyle `LineLength` violation rather than a
            # formatter refusal. Same shape as the neighbor
            # helper `_emit_extends_implements_p2_p3`.
            emitter.restore(attempt)
            emitter.write("<")
            for index, p in enumerate(params):
                emitter.newline()
                emitter.write(cont_indent)
                _emit_node(emitter, source, p)
                if index < len(params) - 1:
                    emitter.write(",")
            emitter.write(">")

    has_extends = superclass_node is not None
    has_implements = super_interfaces_node is not None
    if not has_extends and not has_implements:
        return

    if type_parameters_node is None:
        # No type-param block to attach to. The clauses move
        # directly to continuation line(s) per the P2/P3 cascade.
        _emit_extends_implements_p2_p3(
            emitter,
            source,
            superclass_node,
            super_interfaces_node,
            cont_indent,
        )
        return

    # Type parameters were emitted multi-line. Try the inline
    # form first (clauses appended to the closing-`>` line);
    # if that line overflows, fall through to the P2/P3 cascade.
    attempt = emitter.snapshot()
    if has_extends:
        emitter.write(" ")
        _emit_node(emitter, source, superclass_node)
    if has_implements:
        emitter.write(" ")
        _emit_node(emitter, source, super_interfaces_node)
    if emitter.last_lines_max_width(attempt[0]) <= _MAX_LINE:
        return

    emitter.restore(attempt)
    _emit_extends_implements_p2_p3(
        emitter,
        source,
        superclass_node,
        super_interfaces_node,
        cont_indent,
    )


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
    index = 0
    while index < len(members):
        member = members[index]
        if prev is not None:
            # If the source had at least one blank line between
            # prev's last row and this member's first row,
            # emit a single blank line.
            if member.start_point[0] - prev.end_point[0] > 1:
                emitter.newline()
        emitter.write_indent()
        _emit_node(emitter, source, member)
        # 0.7.0: spec C6 same-row side-comment attachment. When
        # the next sibling is a `//` or single-row `/* */`
        # comment that originally sat on the same source row as
        # this member's closing `;` (field) or `}` (method), attach
        # it inline with two-space separation instead of letting it
        # emit as its own class-body member on a new line.
        # Method-body iteration (`_emit_indented_member_list`,
        # `_emit_block`) has always done this; pre-0.7.0 the
        # class-body iterator was missing the call, so a
        # `public int x = 5; // desc` at class level split to
        # `public int x = 5;\n    // desc`.
        index, member = _attach_trailing_side_comments(
            emitter, source, members, index, member
        )
        emitter.newline()
        prev = member
        index += 1
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


# Precedence groups for Java binary operators, used by
# `_emit_binary_expression` to flatten only same-precedence
# sub-chains. Higher-precedence sub-expressions are kept atomic
# rather than being absorbed into the wrap chain, so a wrap of
# `a + b + (c * d)` (precedence: `*` > `+`) breaks at `+` only,
# never at `*` — matching Java associativity and the spec's
# "break at the lowest-precedence operator" intent.
_BINARY_BOOLEAN_OPERATORS: Final[frozenset[str]] = frozenset({
    "&&", "||",
})
"""Operators whose chains keep one-per-line paren-aligned wrap
(each clause on its own continuation line) rather than greedy
packing. Per the spec preference: each boolean condition is a
distinct semantic clause and benefits from vertical separation;
arithmetic / string-concat / comparison chains are continuous
combinations and benefit from greedy horizontal packing.
"""


_PAIR_ALIGNED_LABEL_DELIM_PREFIXES: Final[frozenset[str]] = frozenset({
    " ", ",", ";", "]", ")", "}", "|", ":",
})
"""Characters that, when they begin a string-literal operand
inside a `+` chain, qualify that operand as a "label" worth
breaking before for the 0.5.0 item 2a pair-aligned wrap. The
set captures the canonical Senzing-style toString() pattern
(`"label1=[ " + val1 + " ], label2=[ " + val2 + " ]"`) where
each subsequent label introduces a new field with a leading
separator. Opening delimiters (`{`, `[`, `(`) are deliberately
excluded — the first label in a `toString()` typically opens
with `{` or `[` and doesn't need a break before it (it's the
line-anchor); subsequent labels carry the separator.
"""


_BINARY_OP_PRECEDENCE: Final[dict[str, int]] = {
    "||": 1,
    "&&": 2,
    "|": 3,
    "^": 4,
    "&": 5,
    "==": 6, "!=": 6,
    "<": 7, ">": 7, "<=": 7, ">=": 7,
    "<<": 8, ">>": 8, ">>>": 8,
    "+": 9, "-": 9,
    "*": 10, "/": 10, "%": 10,
}


_SQL_DDL_KEYWORDS: Final[frozenset[str]] = frozenset({
    "create", "insert", "update", "delete", "select",
    "alter", "drop", "with", "merge", "truncate",
})
"""SQL keywords that identify a string-concat chain as
hand-authored SQL DDL, engaging the 0.6.0 SQL-DDL detector
in `_emit_binary_expression`.

Matched case-insensitively against the first non-whitespace
token of each string_literal operand's content. A chain with
at least one operand starting with one of these keywords is
treated as SQL and emitted one-clause-per-line (emit_p3
shape) instead of greedy-packed.

Deliberately narrow to reduce false positives — a prose
string that happens to start with "CREATE a new file"
would match, but that's rare in practice and the CSOFF
escape hatch remains available.
"""


def _chain_matches_sql_ddl_pattern(
    source: bytes,
    root_op: Node,
    leftmost_operand: Node,
    chain: list[tuple[Node, Node]],
) -> bool:
    """Return True when a `+` binary chain matches the SQL-DDL
    pattern eligible for one-clause-per-line preservation
    (0.6.0 P4).

    Gate:
      1. Root operator is `+` AND all chain operators are `+`
         (no mixed operators — same-precedence flattening
         already ensures this, but check explicitly for
         defense-in-depth).
      2. Leftmost operand is a `string_literal`.
      3. ALL subsequent operands are `string_literal` (pure
         string-concat chain — no interleaved variables).
      4. Chain has at least 2 operators (= 3+ string
         literals). A single `+` between two literals doesn't
         warrant one-per-line breaks.
      5. The LEFTMOST literal's content starts with a
         recognized SQL keyword (see `_SQL_DDL_KEYWORDS`),
         case-insensitive. Restricting the keyword match to
         the leftmost operand (rather than any operand)
         keeps common English prose from triggering the
         detector when a later operand starts with an
         ambiguous word like "with" or "select" (both SQL
         keywords AND common English words) — see the
         inline comment on the check for the full
         rationale.

    Motivating example: a hand-authored `CREATE TABLE` split
    one clause per line. The current binary cascade would
    greedy-pack the strings — visually unreadable for DDL.
    Preserving one-per-line requires firing this detector to
    engage `emit_p3` before the greedy candidates.

    False-positive tolerance: a long prose string that begins
    with "CREATE a new file..." would match, but is rare and
    the developer can opt out via `// CSOFF` markers.
    """
    if root_op.type != "+":
        return False
    if any(op.type != "+" for op, _ in chain):
        return False
    if len(chain) < 2:
        return False
    if leftmost_operand.type != "string_literal":
        return False
    operands = [leftmost_operand] + [operand for _, operand in chain]
    if any(op.type != "string_literal" for op in operands):
        return False
    # Restricted to the LEFTMOST operand — a hand-authored
    # SQL block invariably opens with the keyword (`CREATE
    # TABLE ...`, `SELECT ...`, `INSERT INTO ...`). Requiring
    # the LEFTMOST match keeps common English prose from
    # triggering the detector when a later operand starts
    # with an ambiguous word like "with" or "select" (both
    # SQL keywords AND common English words).
    text = _node_source_text(source, leftmost_operand)
    if len(text) < 2 or text[0] != '"':
        return False
    content = text[1:-1] if text.endswith('"') else text[1:]
    stripped = content.lstrip()
    if not stripped:
        return False
    first_token = ""
    for ch in stripped:
        if ch.isalpha():
            first_token += ch
        else:
            break
    return first_token.lower() in _SQL_DDL_KEYWORDS


def _chain_matches_pair_aligned_pattern(
    source: bytes,
    root_op: Node,
    leftmost_operand: Node,
    chain: list[tuple[Node, Node]],
) -> bool:
    """Return True if a flattened binary chain matches the
    label/value pattern eligible for `emit_pair_aligned`
    (0.5.0 item 2a).

    Gate (lenient — see Senzing handoff for full discussion):

    1. Root operator is `+` AND all chain operators are `+`
       (no mixed `+`/`-` since same precedence-group flattens
       both into the chain).
    2. Leftmost operand is a `string_literal` (the first
       "label" — its prefix doesn't need to be a delimiter
       since it's the line-anchor).
    3. Operands alternate string ↔ non-string. Index 0 is
       a string (already checked); indices 1, 3, 5, ...
       must be non-string; indices 2, 4, 6, ... must be
       string.
    4. Subsequent label literals (overall indices 2, 4, 6,
       ... = chain indices 1, 3, 5, ...) start with a
       character from `_PAIR_ALIGNED_LABEL_DELIM_PREFIXES`
       (`{" ", ",", ";", "]", ")", "}", "|", ":"}`).
    5. Chain has at least 2 operators (= at least one
       subsequent label to break before). A length-1 chain
       has nothing to pair-align.

    The lenient stance on the first label is what makes the
    pattern match the typical Senzing toString() opener
    `"ClassName[ "` or `"{ name=[ "` — those start with
    `{`/`[` which aren't delimiters in this set, but they're
    the line-anchor and don't need a break before them.
    """
    if root_op.type != "+":
        return False
    if any(op.type != "+" for op, _ in chain):
        return False
    if leftmost_operand.type != "string_literal":
        return False
    if len(chain) < 2:
        return False
    for chain_idx, (_op, operand) in enumerate(chain):
        # Overall operand index = chain_idx + 1.
        expected_string = ((chain_idx + 1) % 2 == 0)
        is_string = operand.type == "string_literal"
        if expected_string != is_string:
            return False
        if expected_string:
            # Subsequent label — verify delim prefix. The gate
            # is over-conservative for escape-led literals
            # (`"\\foo"`, `"\nbar"`): `text[1]` is the escape's
            # leading backslash (or similar), never one of the
            # delim characters, so the gate declines. Acceptable
            # because escape-led labels are not part of the
            # canonical Senzing `toString()` pattern this gate
            # is designed to detect; the chain falls through to
            # greedy / paren-aligned (still valid layout).
            text = _node_source_text(source, operand)
            if (
                len(text) < 2
                or text[0] != '"'
                or text[1] not in _PAIR_ALIGNED_LABEL_DELIM_PREFIXES
            ):
                return False
    return True


def _emit_binary_expression(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `LEFT OP RIGHT` with wrap-priority selection on overflow.

    Per the "Whitespace and Operator Spacing" spec section,
    every binary operator gets exactly one space on each side.
    The grammar exposes the binary operator as an anonymous
    keyword child between the two named operand children.
    Supported operators are whatever tree-sitter-java exposes
    as a `binary_expression`: `+`, `-`, `*`, `/`, `%`, `==`,
    `!=`, `<`, `>`, `<=`, `>=`, `&`, `|`, `^`, `<<`, `>>`,
    `>>>`, `&&`, `||`. `instanceof` is its own
    `instanceof_expression` node type and not handled here.

    Wrap priorities (per spec "Line Continuation / break
    before binary operators" and spec C3 cumulative
    continuation indent):

        - **P1**: single line `a OP1 b OP2 c ... OPn z`.
          Rejected (regardless of width) if any nested emit
          introduced newlines — a parenthesized sub-expression
          that wrapped internally is not a true "single line"
          even when the resulting widths all fit.
        - **P2**: break before the leftmost operator; the
          remainder of the chain stays on a single
          continuation line at +4 indent.
        - **P3**: break before every operator in the chain;
          each operand-after-the-first on its own continuation
          line at the +4 indent column.

    Operator chain flattening is **precedence-aware**: only
    same-precedence-group binary expressions on the left
    spine are absorbed into the wrap chain. A higher-precedence
    sub-expression (`a == b` under `||`, `c * d` under `+`,
    etc.) stays atomic — emitted in full as a single chain
    operand. Without this, an `if (a == null || b)` would
    break before `==` instead of before `||`.

    All width checks honor `tail_reserve` so the wrap engine
    accounts for trailing context the binary expression can't
    see (`;` from an expression statement, `)` from an
    enclosing call, `) {` from an `if` condition, etc.).
    """
    children = node.children
    if len(children) != 3:
        raise NotImplementedError(
            f"binary_expression with {len(children)} children — "
            "expected exactly 3 (left, operator, right)."
        )

    # Walk down the left spine, descending only through
    # binary_expression children whose operator shares the
    # root's precedence group. Higher-precedence
    # sub-expressions become atomic operands at the root's
    # level, never broken across continuation lines.
    root_op = node.children[1]
    root_precedence = _BINARY_OP_PRECEDENCE.get(root_op.type)
    leftmost = node
    while True:
        left_child = leftmost.children[0]
        if left_child.type != "binary_expression":
            break
        child_op = left_child.children[1]
        child_precedence = _BINARY_OP_PRECEDENCE.get(child_op.type)
        # Defensive: an operator missing from
        # `_BINARY_OP_PRECEDENCE` (future grammar additions
        # the table hasn't been taught yet) stops the descent.
        # Without this clause, `None != None` evaluates to
        # `False` and two unknown-precedence operators would
        # silently be treated as same-precedence, flattening
        # them into the chain.
        if child_precedence is None or root_precedence is None:
            break
        if child_precedence != root_precedence:
            break
        leftmost = left_child
    leftmost_operand = leftmost.children[0]

    # Collect `[(op_token, right_operand), ...]` left-to-right.
    # Walk back up from `leftmost` to `node` using byte
    # positions for identity (tree-sitter Python wrappers
    # compare by `==`/byte position, not `is`).
    chain: list[tuple[Node, Node]] = [
        (leftmost.children[1], leftmost.children[2])
    ]
    current = leftmost
    while (
        current.start_byte != node.start_byte
        or current.end_byte != node.end_byte
    ):
        parent = current.parent
        if parent is None:
            raise NotImplementedError(
                "binary_expression chain walk lost parent "
                "before reaching root — grammar shape "
                "unexpected."
            )
        chain.append(
            (parent.children[1], parent.children[2])
        )
        current = parent

    def emit_p1() -> None:
        _emit_node(emitter, source, leftmost_operand)
        for op, operand in chain:
            emitter.write(" ")
            emitter.write(op.type)
            emitter.write(" ")
            _emit_node(emitter, source, operand)

    def emit_p2() -> None:
        # Break before the leftmost operator; rest of chain
        # stays on a single continuation line at +4 indent.
        _emit_node(emitter, source, leftmost_operand)
        emitter.newline()
        emitter.push_indent()
        emitter.write_indent()
        for index, (op, operand) in enumerate(chain):
            if index > 0:
                emitter.write(" ")
            emitter.write(op.type)
            emitter.write(" ")
            _emit_node(emitter, source, operand)
        emitter.pop_indent()

    # Shared with `emit_greedy` — set when an operand of the
    # paren-aligned candidate (this function or `emit_greedy`
    # called at `align_col`) introduces a continuation line
    # whose leading-whitespace column is SHALLOWER than the
    # chain's `align_col`. The paren-aligned site reads this
    # after the candidate's emit to decide whether to commit
    # or fall back to the +4 cascade.
    #
    # Multi-row operands at or deeper than `align_col` are
    # fine (e.g. a nested parenthesized binary that
    # paren-aligns to its own inner `(` at a deeper column).
    # Operands that "escape" left past `align_col` (e.g. a
    # nested call whose arg-list wrap-engine emit_p4 indents
    # to `block + 4` while the chain is paren-aligned at a
    # much deeper column) break visual alignment with the
    # operator column; fall back to the +4 cascade where the
    # operand typically fits single-line because the operand
    # has more horizontal room.
    paren_inner_wrap = False

    def _operand_emitted_shallow_line(
        start_line_count: int, threshold: int
    ) -> bool:
        # Skip the first newly-finalized line — it's the line
        # the operand started on (containing the chain prefix +
        # whatever the operand wrote before its first newline);
        # its leading-whitespace reflects the chain's container
        # statement, not the operand's continuations. Any
        # subsequent finalized lines, plus the in-progress
        # `_current` (when the operand advanced past at least
        # one newline) are continuation lines the operand chose
        # itself.
        for line in emitter._lines[start_line_count + 1:]:
            stripped = line.lstrip()
            if not stripped:
                continue
            leading = len(line) - len(stripped)
            if leading < threshold:
                return True
        if emitter.line_count > start_line_count:
            current = emitter._current
            stripped = current.lstrip()
            if stripped:
                leading = len(current) - len(stripped)
                if leading < threshold:
                    return True
        return False

    def emit_paren_aligned(align_col: int) -> None:
        # Spec C6: when an enclosing grouping `(` is in scope,
        # paren-align each operator under the column immediately
        # after that `(`. One operator per continuation line.
        # Caller passes `align_col` directly (captured before
        # clearing the emitter state so a nested grouping paren
        # inside an operand resets cleanly).
        #
        # Reject conditions (set `paren_inner_wrap = True`):
        #   1. Operand emits a "shallow" continuation line —
        #      leading whitespace < `align_col`. Signals the
        #      operand's own wrap engine chose an anchor
        #      shallower than paren-alignment.
        #   2. Operand's emission fires an arg-list P4
        #      (leaf-arg wrap). Distinct from operand's own
        #      binary/chain/ternary wrap: an arg-list P4
        #      inside a paren-aligned operand produces the
        #      "5-line ugly" cascade (each op on own line
        #      PLUS the operand's args broken across
        #      additional lines). Prefer +4-greedy compact.
        nonlocal paren_inner_wrap
        operand_start = emitter.line_count
        prev_p4 = emitter._arg_list_p4_fired
        emitter._arg_list_p4_fired = False
        _emit_node(emitter, source, leftmost_operand)
        if _operand_emitted_shallow_line(operand_start, align_col):
            paren_inner_wrap = True
        if emitter._arg_list_p4_fired:
            paren_inner_wrap = True
        emitter._arg_list_p4_fired = prev_p4 or emitter._arg_list_p4_fired
        for op, operand in chain:
            emitter.newline()
            emitter.write(" " * align_col)
            emitter.write(op.type)
            emitter.write(" ")
            operand_start = emitter.line_count
            prev_p4 = emitter._arg_list_p4_fired
            emitter._arg_list_p4_fired = False
            _emit_node(emitter, source, operand)
            if _operand_emitted_shallow_line(operand_start, align_col):
                paren_inner_wrap = True
            if emitter._arg_list_p4_fired:
                paren_inner_wrap = True
            emitter._arg_list_p4_fired = (
                prev_p4 or emitter._arg_list_p4_fired
            )

    def emit_p3() -> None:
        # Each operand on its own continuation line at +4
        # indent column, prefixed with the operator.
        _emit_node(emitter, source, leftmost_operand)
        emitter.push_indent()
        for op, operand in chain:
            emitter.newline()
            emitter.write_indent()
            emitter.write(op.type)
            emitter.write(" ")
            _emit_node(emitter, source, operand)
        emitter.pop_indent()

    def emit_pair_aligned(cont_col: int) -> None:
        # Item 2a: label/value-aware pair-aligned wrap. For
        # `+` chains where operands alternate string ↔
        # non-string with delimiter-prefix subsequent labels,
        # break before each subsequent label so each line
        # carries one `label + value` pair. Continuation lines
        # start with the operator at `cont_col`, the operand at
        # `cont_col + 2` (after `+ `).
        #
        # Trades horizontal density for semantic alignment —
        # makes the label/value structure visually obvious in
        # the canonical Senzing `toString()` pattern.
        # Item 8 invariant: after each operand emit, if the
        # operand's OWN render introduced newlines (a nested
        # construct that wrapped multi-line), the next
        # operator MUST break to a new line — otherwise the
        # subsequent operator would visually merge with the
        # wrapped operand's tail at the same column, stranding
        # the chain. Applies to both label-break positions
        # (already break-before by design) and value-pack
        # positions (which otherwise pack onto the same line
        # as the prior label). The check captures
        # `start_line_count` BEFORE the leftmost emit so a
        # multi-row leftmost operand (e.g. a parenthesized
        # binary that wraps) also forces the first chain entry
        # to break, matching the `emit_greedy` shape.
        start_line_count = emitter.line_count
        _emit_node(emitter, source, leftmost_operand)
        prev_operand_multi_row = (
            emitter.line_count > start_line_count
        )
        for index, (op, operand) in enumerate(chain):
            # Chain index 0 corresponds to overall operand
            # index 1 (first value after the first label).
            # Chain indices 1, 3, 5, ... are subsequent
            # labels — break before each.
            is_subsequent_label = (index % 2 == 1)
            if is_subsequent_label or prev_operand_multi_row:
                emitter.newline()
                emitter.write(" " * cont_col)
                emitter.write(op.type)
                emitter.write(" ")
                operand_start_line = emitter.line_count
                _emit_node(emitter, source, operand)
            else:
                emitter.write(" ")
                emitter.write(op.type)
                emitter.write(" ")
                operand_start_line = emitter.line_count
                _emit_node(emitter, source, operand)
            prev_operand_multi_row = (
                emitter.line_count > operand_start_line
            )

    def emit_greedy(cont_col: int) -> None:
        nonlocal paren_inner_wrap
        # Greedy packing (0.5.0 item 3): pack as many
        # `OP operand` pairs per continuation line as fit
        # within `effective_max`; break at operator boundary;
        # continuation lines start at `cont_col`. Used for
        # non-boolean operators (`+`, `-`, `*`, `/`, `==`,
        # etc.) where horizontal density is preferred over
        # vertical separation. Boolean chains (`&&` / `||`)
        # keep `emit_paren_aligned` (one-per-line) instead.
        #
        # Item 8 invariant: after each operand emit, if the
        # operand's OWN render introduced newlines (a nested
        # construct that wrapped multi-line), the next
        # `OP operand` pair MUST break to a new line —
        # otherwise the subsequent operator would visually
        # merge with the wrapped operand's tail at the same
        # column, stranding the chain. Same anti-stranding
        # principle as 0.4.3's Bug 1 fix for method chains,
        # applied at the binary-operator level. The key
        # subtlety: we track ONLY the operand's internal
        # newlines (captured AFTER any explicit break we
        # wrote ourselves), not the cumulative newlines from
        # this iteration — otherwise `pack-failed → broke →
        # re-emit` would falsely signal "operand went
        # multi-row" and force every subsequent operator to
        # break (degenerating into one-per-line output).
        # 0.6.0: also mark paren_inner_wrap when an operand's
        # emission fires an arg-list P4 (leaf-arg wrap). See
        # design note on `Emitter._arg_list_p4_fired`. The
        # save-reset-check-restore cycle isolates the flag to
        # each operand's emission scope; the outer `prev_p4`
        # bubbles the flag up so a P4 that fires deep inside
        # is still visible to callers of this emit.
        start_line_count = emitter.line_count
        prev_p4 = emitter._arg_list_p4_fired
        emitter._arg_list_p4_fired = False
        _emit_node(emitter, source, leftmost_operand)
        prev_operand_multi_row = (
            emitter.line_count > start_line_count
        )
        if _operand_emitted_shallow_line(
            start_line_count, cont_col
        ):
            paren_inner_wrap = True
        if emitter._arg_list_p4_fired:
            paren_inner_wrap = True
        emitter._arg_list_p4_fired = prev_p4 or emitter._arg_list_p4_fired
        for op, operand in chain:
            if prev_operand_multi_row:
                # Item 8: force break before this operator.
                emitter.newline()
                emitter.write(" " * cont_col)
                emitter.write(op.type)
                emitter.write(" ")
                operand_start_line = emitter.line_count
                prev_p4 = emitter._arg_list_p4_fired
                emitter._arg_list_p4_fired = False
                _emit_node(emitter, source, operand)
            else:
                # Speculatively pack `" OP operand"` on the
                # current line.
                pack_saved = emitter.snapshot()
                emitter.write(" ")
                emitter.write(op.type)
                emitter.write(" ")
                operand_start_line = emitter.line_count
                prev_p4 = emitter._arg_list_p4_fired
                emitter._arg_list_p4_fired = False
                _emit_node(emitter, source, operand)
                pack_ok = (
                    emitter.last_lines_max_width(pack_saved[0])
                    <= effective_max
                    and emitter.line_count == operand_start_line
                )
                if not pack_ok:
                    # Either overflowed or operand wrapped
                    # multi-line. Restore, break, re-emit at
                    # cont_col.
                    emitter.restore(pack_saved)
                    emitter.newline()
                    emitter.write(" " * cont_col)
                    emitter.write(op.type)
                    emitter.write(" ")
                    operand_start_line = emitter.line_count
                    prev_p4 = emitter._arg_list_p4_fired
                    emitter._arg_list_p4_fired = False
                    _emit_node(emitter, source, operand)
            prev_operand_multi_row = (
                emitter.line_count > operand_start_line
            )
            if _operand_emitted_shallow_line(
                operand_start_line, cont_col
            ):
                paren_inner_wrap = True
            if emitter._arg_list_p4_fired:
                paren_inner_wrap = True
            emitter._arg_list_p4_fired = (
                prev_p4 or emitter._arg_list_p4_fired
            )

    # Manual P1 speculation with newline-detection (replaces
    # try_priorities for this site because try_priorities
    # only inspects widths — a nested emit that wraps
    # internally can satisfy the width check while breaking
    # the "single line" semantic). P2 and P3 still use
    # straightforward width-based commit since their own
    # newlines are deliberate.
    #
    # Regression tests for this gate live at
    # `condition_wrap/07_mixed_precedence_inner_parens_atomic`
    # (outer P1 emit produces multi-line output via a nested
    # parenthesized binary that wraps internally; all line
    # widths still fit, so a width-only check would miss the
    # break — the newline-rejection below is what catches it
    # and triggers the fall-through to P2). Verified
    # empirically: removing the `line_count == saved[0]`
    # clause causes that fixture to fail.
    effective_max = _MAX_LINE - emitter.tail_reserve
    saved = emitter.snapshot()
    emit_p1()
    p1_fits = (
        emitter.last_lines_max_width(saved[0]) <= effective_max
        and emitter.line_count == saved[0]
    )
    if p1_fits:
        return
    emitter.restore(saved)

    # Operator-conditional cascade (0.5.0 items 2a + 3):
    #
    # Boolean chains (`&&` / `||`) preserve the spec preference
    # of one-per-line paren-aligned (each clause on its own
    # continuation line for vertical readability). Non-boolean
    # chains (`+`, `-`, `*`, `/`, `==`, etc.) use greedy
    # horizontal packing.
    #
    # `+` chains with the label/value pattern (alternating
    # string ↔ non-string operands, with delimiter-prefix
    # subsequent labels) ALSO try `emit_pair_aligned` BEFORE
    # greedy — break before each label so each line carries
    # one `label + value` pair. Greedy stays as the fallback
    # when the pair-aligned shape itself overflows (e.g. a
    # particularly long value).
    is_boolean = root_op.type in _BINARY_BOOLEAN_OPERATORS
    is_pair_aligned_candidate = _chain_matches_pair_aligned_pattern(
        source, root_op, leftmost_operand, chain
    )
    is_sql_ddl_candidate = _chain_matches_sql_ddl_pattern(
        source, root_op, leftmost_operand, chain
    )

    # 0.6.0 P4 — SQL DDL detector. When the chain is a
    # pure-string `+` concatenation and at least one operand
    # starts with a recognized SQL keyword (CREATE, INSERT,
    # etc.), emit one-clause-per-line via `emit_p3` BEFORE
    # trying the greedy/pair-aligned candidates. Preserves
    # the hand-authored one-per-line DDL layout that greedy
    # packing would otherwise collapse into an unreadable
    # jumble. Pre-0.6, the only escape hatch was `// CSOFF`
    # markers.
    if is_sql_ddl_candidate:
        sql_saved = emitter.snapshot()
        emit_p3()
        if emitter.last_lines_max_width(sql_saved[0]) <= effective_max:
            return
        # If emit_p3 itself overflows (a single clause is
        # too wide even at block+4), fall through to the
        # standard cascade — the developer must split that
        # clause by hand and checkstyle will surface the
        # overflow.
        emitter.restore(sql_saved)

    # Item 2a — pair-aligned candidate. Tried BEFORE the
    # paren-aligned / greedy candidates when the chain matches
    # the label/value pattern. Uses paren_align_col if set,
    # else +4 cumulative-indent column.
    if is_pair_aligned_candidate:
        pair_col = (
            emitter.paren_align_col
            if emitter.paren_align_col is not None
            else 4 * (emitter.indent_level + 1)
        )
        pair_saved = emitter.snapshot()
        prev_align = emitter.set_paren_align_col(None)
        try:
            emit_pair_aligned(pair_col)
        finally:
            emitter.set_paren_align_col(prev_align)
        if emitter.last_lines_max_width(pair_saved[0]) <= effective_max:
            return
        emitter.restore(pair_saved)

    # Spec C6 paren-aligned candidate, preferred over the
    # standard +4-indent fallback when an enclosing grouping
    # `(` (or, post-0.5.0-item-4, a single-arg call paren) is
    # in scope and the paren-aligned shape doesn't itself
    # overflow. Tried BEFORE the +4 fallback so a parenthesized
    # expression like `(a || b || c)` wraps with `||` lined up
    # under the column after `(`, rather than getting pulled
    # to the cumulative `+4` column (which would produce the
    # "staircase" shape when grouping parens are nested).
    #
    # For boolean chains the paren-aligned shape is
    # one-per-line (`emit_paren_aligned`); for non-boolean
    # chains it is greedy at `align_col` (`emit_greedy`).
    align_col = emitter.paren_align_col
    if align_col is not None:
        paren_saved = emitter.snapshot()
        # Clear paren_align_col while emitting this candidate's
        # operands. The paren context applies to THIS binary
        # chain's operator continuations only; nested binary
        # expressions inside the operands have their own
        # `_emit_parenthesized_expression` to re-set
        # `paren_align_col` if they themselves sit inside
        # grouping parens.
        prev_align = emitter.set_paren_align_col(None)
        # Reset the shared `paren_inner_wrap` flag before this
        # candidate's speculative emit so the post-emit check
        # below reflects ONLY operands emitted under this
        # candidate. Without the reset, a prior speculative
        # attempt (e.g. emit_pair_aligned at the same align_col)
        # could leave the flag True and cause this candidate to
        # falsely reject. Keep this reset paired with any future
        # addition of a third candidate that calls the shared
        # emit_paren_aligned / emit_greedy.
        paren_inner_wrap = False
        try:
            if is_boolean:
                emit_paren_aligned(align_col)
            else:
                emit_greedy(align_col)
        finally:
            emitter.set_paren_align_col(prev_align)
        # Commit the paren-aligned candidate ONLY when (a) all
        # lines fit within `effective_max` AND (b) no operand
        # wrapped multi-row internally. (b) is what keeps the
        # +4-fallback as the preferred shape for cases like
        # `super("..." + foo() + (longInner.that.wraps))` — the
        # paren-aligned column gives each operand less
        # horizontal room than the +4 column does, so an
        # operand that wraps at align_col will typically fit
        # single-line at the +4 column. Rejecting here keeps
        # the chain visually coherent (operator column aligned
        # with operand body) rather than committing to a
        # poorly aligned shape.
        if (
            emitter.last_lines_max_width(paren_saved[0])
            <= effective_max
            and not paren_inner_wrap
        ):
            return
        emitter.restore(paren_saved)

    # +4-indent fallback. For boolean chains: P2 (leftmost-only
    # break, rest on one continuation line); falls through to
    # P3 (every operator on own line) on overflow. For
    # non-boolean chains: greedy at the +4 continuation column;
    # P3 remains as defensive last-resort.
    p2_col = 4 * (emitter.indent_level + 1)
    fallback_saved = emitter.snapshot()
    if is_boolean:
        emit_p2()
    else:
        emit_greedy(p2_col)
    if emitter.last_lines_max_width(fallback_saved[0]) <= effective_max:
        return
    emitter.restore(fallback_saved)
    emit_p3()
    _fire_wrap_overflow_advisory(
        emitter, node, fallback_saved[0], "binary expression"
    )


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
    # Reserve 1 char for the closing `)` so any wrap candidate
    # inside the parens accounts for it. Without this an inner
    # binary or chain that fits at exactly effective_max
    # commits, and the trailing `)` + further surrounding
    # tokens (e.g. an outer `;` or `) {`) push the line past
    # the budget.
    #
    # Spec C6 paren-alignment applies to every
    # `parenthesized_expression` node (0.5.0+) — both
    # developer-authored grouping parens AND the
    # syntactically-required parens of control-flow
    # constructs (`if (cond)`, `while (cond)`, `for (...)`,
    # `catch (...)`, `synchronized (...)`, `switch (...)`).
    # Earlier releases (0.4.3) restricted paren-alignment to
    # grouping parens only; 0.5.0 extends the rule to
    # control-flow parens so an operator continuation inside
    # an `if (long binary)` aligns under the column after the
    # `(`, matching what the formatter already did inside
    # `return (long binary)`. The yields-to-source-preserve
    # inversion check below still applies — when an inner
    # source-preserved arg list has continuation columns
    # below the proposed paren-align column, paren-alignment
    # is declined and the wrap engine falls back to the
    # cumulative `+4` continuation.
    prev_reserve = emitter.set_tail_reserve(
        emitter.tail_reserve + 1
    )
    # Paren-align yields to source-preservation when they
    # conflict. Walk the inner expression looking for nested
    # `argument_list` nodes that would actually source-preserve
    # at their emission column; if any such arg list has a
    # continuation line whose leading-whitespace count is LESS
    # than the proposed paren-align column (`emitter.column`
    # right after `(`), then engaging paren-alignment would
    # visually invert the output — the outer operator chain
    # (paren-aligned at `emitter.column`) would appear MORE
    # indented than the source-preserved inner content. Spec C6
    # paren-alignment is meant to avoid the +4-staircase shape;
    # preserving the developer's source-authored break points
    # wins when those two goals conflict.
    #
    # Using `_arg_list_takes_source_preserve_path` here (rather
    # than scanning the source text directly) avoids the false
    # positive where a low-col continuation in the source comes
    # from an arg list that Bug 4's width opt-out will collapse
    # to single-line. Those don't actually source-preserve, so
    # their source columns are irrelevant to the inversion
    # check.
    apply_paren_align = not _inner_would_invert_paren_align(
        emitter, source, inner, emitter.column
    )
    prev_paren_align: int | None = None
    # `paren_expr_col` tracks the SAME column but is set here
    # unconditionally so `emit_p4_single_arg`'s paren-deference
    # rule sees the grouping paren even when
    # `_inner_would_invert_paren_align` declined the spec C6
    # binary-continuation alignment. Item 10's setting of
    # `paren_align_col` from `_emit_argument_list` never touches
    # `paren_expr_col`.
    prev_paren_expr = emitter.set_paren_expr_col(emitter.column)
    if apply_paren_align:
        prev_paren_align = emitter.set_paren_align_col(emitter.column)
    try:
        _emit_node(emitter, source, inner)
    finally:
        emitter.set_tail_reserve(prev_reserve)
        if apply_paren_align:
            emitter.set_paren_align_col(prev_paren_align)
        emitter.set_paren_expr_col(prev_paren_expr)
    emitter.write(")")


def _inner_would_invert_paren_align(
    emitter: Emitter,
    source: bytes,
    inner: Node,
    proposed_col: int,
) -> bool:
    """Return True when paren-aligning `inner` at `proposed_col`
    would produce visually inverted output — i.e., the inner
    expression contains an `argument_list` node that would
    source-preserve via `_emit_argument_list`'s `write_raw_lines`
    path AND that arg list's source has a continuation line at
    a column less than `proposed_col`.

    Walks the inner tree top-down. For each `argument_list`
    node visited, consults
    `_arg_list_takes_source_preserve_path` to determine whether
    the arg list will actually take the verbatim-emit path. The
    column passed to the predicate is `proposed_col` — a lower
    bound on the arg list's eventual emit column (since the arg
    list will be nested deeper than the paren whose alignment
    we're considering). Using a lower bound makes the predicate's
    width opt-out fire more aggressively (more arg lists treated
    as "Bug 4 collapses"), which gives a safe under-detection
    bias: we may miss declining paren-align in cases where the
    actual inner emit column is larger and source-preservation
    kicks in — at worst this leaves the inversion in place,
    same as pre-0.4.3 behavior for those nested cases.
    """
    stack = [inner]
    while stack:
        current = stack.pop()
        if current.type == "argument_list" and (
            _arg_list_takes_source_preserve_path(
                emitter, source, current
            )
        ):
            src = _node_source_text(source, current)
            for line in src.split("\n")[1:]:
                stripped = line.lstrip()
                if not stripped:
                    continue
                leading = len(line) - len(stripped)
                if leading < proposed_col:
                    return True
        for child in current.named_children:
            stack.append(child)
    return False


def _emit_method_header_wrapped(
    emitter: Emitter,
    source: bytes,
    type_parameters_node: Node,
    type_node: Node,
    name_node: Node,
    parameters_node: Node,
    ctx: WrapContext,
) -> None:
    """Emit a method signature in the spec B11 wrapped form.

    Used by `_emit_method_declaration` when the single-line
    signature would exceed 80 chars due to a long generic-type
    parameter list. The shape:

        [modifiers] <T1,
                ... TN>
            RETURN_TYPE NAME(PARAMS)

    The first type-parameter stays on the modifiers line right
    after `<`. Subsequent type-parameters wrap to continuation
    lines at `ctx.indent_col` (single-indent past the method
    start). The closing `>` ends the last type-parameter line.
    Then a newline + `ctx.indent_col` indent drops to the
    return-type / name / parameters portion (so the method
    header is multi-line and any following `throws` clause or
    Allman opening brace can land independently per the standard
    "multi-line condition → Allman brace" interaction).

    Caller has already emitted the modifiers (if any). This
    function appends the type-parameter list (with wrap) and the
    return-type / name / parameters portion.
    """
    cont_indent = " " * ctx.indent_col
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
    emitter.newline()
    emitter.write(cont_indent)
    _emit_node(emitter, source, type_node)
    emitter.write(" ")
    _emit_node(emitter, source, name_node)
    # Force a fresh emit of the parameter list with overflow-aware
    # paren-alignment. JDT-source-preservation of the original
    # signature would otherwise carry over JDT's far-paren-aligned
    # continuation column, producing >80-char lines after the
    # type-param wrap moved the signature to a new shorter column.
    _emit_formal_parameters(
        emitter, source, parameters_node,
        force_wrap=True,
        p3_indent_col=ctx.p3_indent_col,
    )


def _attach_trailing_side_comments(
    emitter: Emitter,
    source: bytes,
    nodes: list[Node],
    index: int,
    anchor: Node,
) -> tuple[int, Node]:
    """Consume any `line_comment` / `block_comment` siblings of
    `anchor` that originally sat on the same source row, emitting
    them inline on the emitter's current line with two spaces of
    separation per spec C6 ("End-of-line side comments").

    Returns the new `index` (advanced past the consumed comments)
    and the new `anchor` (the last comment consumed, or the
    original `anchor` if none were). The new anchor is what the
    caller uses for the next iteration's source-blank-line
    tracking — using the comment's end row instead of the
    original statement's end row is correct as long as the
    comment ends on the same source row it started on, which is
    always true for `line_comment` and true for single-line
    `block_comment`. Multi-line `block_comment` would change
    blank-line tracking semantics; the function guards against
    that by refusing to consume a block comment that spans
    multiple rows.

    Used by `_emit_indented_member_list` (method / constructor /
    static-initializer bodies, switch-block cases) and
    `_emit_block` (control-flow blocks). Centralizing the
    same-row attachment rule here keeps the two sites
    consistent — the brace-row side-comment loop in
    `_emit_block` (which writes `{  // comment`) accepts both
    comment types, so the trailing-comment loops accept both
    too.
    """
    while index + 1 < len(nodes):
        nxt = nodes[index + 1]
        if nxt.type not in ("line_comment", "block_comment"):
            break
        if nxt.start_point[0] != anchor.end_point[0]:
            break
        if (
            nxt.type == "block_comment"
            and nxt.end_point[0] != nxt.start_point[0]
        ):
            # Multi-line block comment — declining to attach
            # would let it emit on its own line below, which
            # is the safer behavior (an inline multi-row
            # comment would change blank-line tracking and is
            # rare in practice).
            break
        index += 1
        emitter.write("  ")
        _emit_node(emitter, source, nodes[index])
        anchor = nodes[index]
    return index, anchor


def _emit_indented_member_list(
    emitter: Emitter, source: bytes, items: list[Node]
) -> None:
    """Emit each item in `items` on its own line at +1 indent
    relative to the caller's current level, preserving
    source-authored blank lines between consecutive items
    (clamped at one per spec A2).

    Used for the bodies of method / constructor / compact-
    constructor / static-initializer declarations and switch-
    block cases — all of which place each child on its own
    line, with at most one blank between consecutive children
    when the source had at least one between them.

    No-op when `items` is empty (caller still emits the
    enclosing `{ }`).
    """
    if not items:
        return
    emitter.push_indent()
    prev: Node | None = None
    index = 0
    while index < len(items):
        item = items[index]
        if prev is not None:
            if item.start_point[0] - prev.end_point[0] > 1:
                emitter.newline()
        emitter.write_indent()
        _emit_node(emitter, source, item)
        # Spec C6 same-row side-comment attachment — see
        # `_attach_trailing_side_comments`.
        index, item = _attach_trailing_side_comments(
            emitter, source, items, index, item
        )
        emitter.newline()
        prev = item
        index += 1
    emitter.pop_indent()


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

    # Capture the method declaration's start column for the
    # type-parameter wrap continuation indent. The wrap form
    # places subsequent type-parameters and the return-type /
    # name / parameters portion at `start_col + 4`.
    start_col = emitter.column

    if modifiers_node is not None:
        # `_emit_modifiers` emits its own trailing space (for
        # keyword modifiers) or its own trailing newline +
        # indent (for annotation-only modifiers), so the
        # caller does not write a separator here.
        _emit_node(emitter, source, modifiers_node)

    # Try-emit the single-line signature. If it overflows 80
    # chars, backtrack and emit the wrapped form. With type
    # parameters present, the spec B11 type-parameter wrap
    # applies (`_emit_method_header_wrapped`). Without type
    # parameters, the parameter list itself is force-wrapped
    # via `_emit_formal_parameters(force_wrap=True)`.
    #
    # For abstract/interface/native methods (no body), the
    # signature is followed by a trailing `;` appended after
    # the fit check below — so a signature emitting to
    # exactly 80 chars would land at 81 on disk. Reserve 1
    # extra char in the fit threshold to catch that case.
    semicolon_reserve = 1 if body is None else 0
    fit_threshold = _MAX_LINE - semicolon_reserve
    saved = emitter.snapshot()
    if type_parameters_node is not None:
        # Per spec B11: `<T>` comes BEFORE the return type, with
        # a single space after the closing `>`.
        _emit_node(emitter, source, type_parameters_node)
        emitter.write(" ")
    _emit_node(emitter, source, type_node)
    emitter.write(" ")
    _emit_node(emitter, source, name_node)
    _emit_node(emitter, source, parameters_node)

    if emitter.last_lines_max_width(saved[0]) > fit_threshold:
        emitter.restore(saved)
        # Bump `tail_reserve` by 1 for abstract/native/interface
        # methods so the inner param wrap engine's P1
        # single-line attempt also accounts for the trailing
        # `;` — without this, P1 sees the params fit on one
        # line and commits the same single-line shape that
        # tripped the outer check.
        prev_reserve = emitter.tail_reserve
        if body is None:
            emitter.set_tail_reserve(prev_reserve + 1)
        try:
            if type_parameters_node is not None:
                _emit_method_header_wrapped(
                    emitter,
                    source,
                    type_parameters_node,
                    type_node,
                    name_node,
                    parameters_node,
                    WrapContext.at(start_col),
                )
            else:
                # No type parameters — wrap only the parameter
                # list. Re-emit the return type + name and call
                # _emit_formal_parameters with force_wrap so the
                # P2 paren-aligned (or P3 next-line-indented)
                # form engages instead of the default
                # single-line.
                _emit_node(emitter, source, type_node)
                emitter.write(" ")
                _emit_node(emitter, source, name_node)
                _emit_formal_parameters(
                    emitter, source, parameters_node,
                    force_wrap=True,
                    p3_indent_col=start_col + 8,
                )
        finally:
            emitter.set_tail_reserve(prev_reserve)

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
    _emit_indented_member_list(
        emitter, source, list(body.named_children)
    )
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
    index = 0
    while index < len(remaining):
        stmt = remaining[index]
        if prev_stmt is not None:
            if stmt.start_point[0] - prev_stmt.end_point[0] > 1:
                emitter.newline()
        emitter.write_indent()
        _emit_node(emitter, source, stmt)
        # Spec C6 same-row side-comment attachment — see
        # `_attach_trailing_side_comments`.
        index, stmt = _attach_trailing_side_comments(
            emitter, source, remaining, index, stmt
        )
        emitter.newline()
        prev_stmt = stmt
        index += 1
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
        # Tier 1 is structurally eligible. Speculatively emit
        # the would-be single-line `if (cond) STMT;` form;
        # commit if the line fits and the condition/statement
        # didn't introduce any newlines. Per spec
        # "Short-Circuit Conditionals / Tier 2", an overflow
        # falls through to the braced form below.
        #
        # The speculative-emit approach measures rendered
        # widths (not source-text widths), so wrap decisions
        # are deterministic from the AST regardless of input
        # whitespace.
        tier1_saved = emitter.snapshot()
        emitter.write("if ")
        _emit_node(emitter, source, condition)
        emitter.write(" ")
        _emit_node(emitter, source, short_circuit)
        tier1_fits = (
            emitter.last_lines_max_width(tier1_saved[0])
            <= _MAX_LINE - emitter.tail_reserve
            and emitter.line_count == tier1_saved[0]
        )
        if tier1_fits:
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
            return
        # Roll back the Tier 1 attempt so the Tier 2 (braced)
        # path below emits cleanly from the original state.
        emitter.restore(tier1_saved)

    # Bump tail_reserve while emitting the condition so any
    # binary-expression wrap inside it accounts for the upcoming
    # `) {` / `) STMT` after the condition closes. Without this
    # an `if (cond)` that fits at exactly _MAX_LINE commits
    # inline and the brace pushes the line past the limit.
    #
    # Brace placement follows the spec's "Multi-line Conditions"
    # rule: when the condition's RENDERED output spans more than
    # one line (either because the source was multi-row, or
    # because the wrap engine broke a single-row source
    # condition across multiple lines), the opening `{` goes
    # Allman (on its own line at the if's indent column).
    # Single-line rendered condition → same-line `{`.
    #
    # Intentional asymmetry vs. `_emit_while_statement`: the
    # while-emitter takes a source-preserve fast path that emits
    # a developer-authored multi-row condition verbatim via
    # `write_raw_lines`. The if-emitter does NOT — it always
    # re-renders through `_emit_node`, which collapses a
    # multi-row source condition to single-line when it fits.
    # This matches the established 0.4.1 and earlier behavior
    # for if-conditions; we only added the Allman switch here.
    # A future release may reconcile by either teaching the
    # if-emitter to source-preserve, or removing the
    # while-emitter's source-preserve fast path.
    emitter.write("if ")
    cond_start_line_count = emitter.line_count
    prev_reserve = emitter.set_tail_reserve(
        emitter.tail_reserve + 2
    )
    try:
        _emit_node(emitter, source, condition)
    finally:
        emitter.set_tail_reserve(prev_reserve)
    if emitter.line_count > cond_start_line_count:
        emitter.newline()
        emitter.write_indent()
    else:
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


_JAVADOC_BLOCK_TOKENS: Final[tuple[str, ...]] = (
    "<p>", "<pre>", "</pre>", "<ul>", "</ul>", "<ol>", "</ol>",
    "<table>", "</table>", "<tr>", "</tr>", "<td>", "</td>",
    "<th>", "</th>",
)


_LINE_LENGTH_EXEMPT_MARKERS: Final[tuple[str, ...]] = (
    "a href",
    "href",
    "http://",
    "https://",
    "@snippet",
)
"""Substrings that make checkstyle's `LineLength` check skip a line.

Mirrors the `ignorePattern` in `checkstyle/senzing-checkstyle.xml`. The
formatter consults it before advising about a line it could not shorten:
warning about a line the build will not reject is noise, and noise in a
per-build advisory channel is how the channel stops being read.

A javadoc `@see <a href="...">` is the common case — an unbreakable URL
inside markup. Across the trial corpus 73 of 123 candidate advisories
were exactly that, all in one file, none of them actionable.

Kept as a literal list rather than parsed out of the checkstyle XML: the
formatter has no dependency on that file today, and reading it would mean
locating a consumer-specific config from inside a library module. The
cost is that the two can drift, which is why both sides name each other.
"""


def _line_length_exempt(text: str) -> bool:
    """True when checkstyle's `LineLength` check would skip `text`."""
    return any(m in text for m in _LINE_LENGTH_EXEMPT_MARKERS)


def _looks_like_snippet_file_attr(stripped: str) -> bool:
    """Return True when `stripped` looks like a `file="..."`
    attribute line in a `{@snippet}` directive (and therefore
    should NOT be reflowed as prose).

    Tightens the bare `startswith('file="')` check: a real
    snippet attribute is followed by snippet termination
    (closing `}`), another snippet attribute (`lang=`,
    `region=`, `id=`), or end-of-line. A prose sentence that
    begins `file="foo.txt" is the config...` continues with
    English text and is correctly classified as prose.
    """
    if not stripped.startswith('file="'):
        return False
    close = stripped.find('"', len('file="'))
    if close < 0:
        return False
    after = stripped[close + 1:].lstrip()
    if not after:
        return True
    if after.startswith("}"):
        return True
    return any(
        kw in after for kw in ("lang=", "region=", "id=")
    )


def _javadoc_is_prose_line(content: str) -> bool:
    """Return True when `content` (the post-`* ` part of a javadoc
    interior line) is plain prose eligible for paragraph reflow.

    Excludes: `@tag` descriptions (their own handler runs),
    list items (`<li>`), block-level HTML openers / closers,
    `{@snippet ...}` fragments (the checkstyle ignorePattern
    excludes them from line-length checks), and CSOFF / CSON
    suppressors.

    Source `* <li>` and `*   <li>` (any indented `<li>` —
    `<li>` items are commonly indented past `* ` for visual
    nesting under an `<ol>` or `<ul>`) both classify as list
    items. The check strips leading whitespace before testing
    for the structural marker, so a `<li>` line never gets
    folded into a surrounding prose paragraph regardless of
    its indent.

    An INDENT of its own is also structural, whatever follows it.
    Authors indent to show structure — a hanging indent under a list
    item, a continuation aligned beneath an introducing phrase — and
    reflowing those lines as ordinary prose discards the structure.

    Treating indent as structural is also what makes this classifier
    STABLE ACROSS PASSES, which it previously was not. Paragraph runs
    are split at non-prose lines, so an indented line divides the
    prose around it into separate sub-paragraphs. Reflow then rewrites
    every prose line to the bare `* ` prefix — erasing the indent that
    did the dividing. On the next pass the same comment grouped into
    FEWER, LARGER paragraphs and reflowed differently:

        pass 1  * Some ordinary prose that is long enough to need
                * reflowing
                *       and a hanging indented continuation of it
        pass 2  * Some ordinary prose that is long enough to need
                * reflowing and a hanging indented continuation of it

    Because a reflowed line never carries an indent and a preserved
    line always keeps the one it had, every line's answer here is now
    the same on pass 2 as on pass 1 — which is what convergence
    requires. This was the last non-idempotent construct in the trial
    corpus.
    """
    if not content:
        return False
    if content[:1].isspace():
        return False
    stripped = content.lstrip()
    if stripped.startswith("@"):
        return False
    if stripped.startswith("<li>"):
        return False
    for tok in _JAVADOC_BLOCK_TOKENS:
        if stripped.startswith(tok) and (
            len(stripped) <= len(tok) + 4
        ):
            return False
    if stripped == "*/":
        return False
    if "{@snippet" in stripped:
        return False
    if _looks_like_snippet_file_attr(stripped):
        return False
    if stripped.startswith("CSOFF") or stripped.startswith("CSON"):
        return False
    return True


_REFLOW_ORPHAN_MAX_WORDS: Final[int] = 3
"""A reflowed comment's last line is an orphan when it carries this
many words or fewer. Three matches `feedback_comment_reflow`'s "never
orphan 1-3 words on a continuation"; a fourth word makes the line read
as a clause of its own rather than a fragment left behind."""


def _balanced_reflow_words(
    words: list[str], max_content: int,
    only_when_orphaned: bool = False,
) -> list[str]:
    """Reflow `words` into lines of at most `max_content` chars,
    balanced so the last line is not left with a 1-3 word orphan.

    Two passes. The first is a plain greedy fill, which establishes
    the minimum number of lines `N` the content needs. The second
    rebuilds against a soft target of `total / N`, breaking once a
    line reaches the target rather than once it reaches the hard cap,
    so the N lines come out roughly even. Greedy alone packs line 1
    to the limit and strands the remainder:

        // pack the first line tight and this is what is left over
        // behind

    Per `feedback_comment_reflow`: pack the first line tight OR
    balance the breaks; never orphan 1-3 words on a continuation.
    Balancing is chosen because it reads better at the same line
    count — the rebuild can never need more lines than greedy, and
    falls back to the greedy result if it somehow does, which is what
    keeps the output idempotent.

    Shared by `_emit_reflowed_line_comment` (which has balanced its
    output since 0.6.0) and `_javadoc_reflow_words` (which was still
    greedy, so the same comment prose reflowed two different ways
    depending on whether it was written `//` or `/** */`).
    """
    if not words:
        return []
    # Pass 1 — greedy, to find the minimum line count. A single word
    # longer than the budget cannot be made to fit; it goes on its own
    # line and the overflow surfaces per spec C1 emit-and-warn rather
    # than looping forever trying to place it.
    greedy: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = current + " " + word
        if len(candidate) <= max_content:
            current = candidate
        else:
            greedy.append(current)
            current = word
    greedy.append(current)
    if len(greedy) <= 1:
        return greedy
    # Only rebalance when greedy actually orphaned. The rule is "pack
    # the first line tight OR balance the breaks" — packing tight is a
    # perfectly good answer, so a greedy fill whose last line carries a
    # real clause is left alone. Rebalancing unconditionally would
    # rewrite every wrapped comment in a code base to buy nothing:
    #
    #     // greedy, no orphan, left alone
    #     // The number of milliseconds to sleep between checks on the locks
    #     // required for tasks that have been postponed.
    if only_when_orphaned and (
        len(greedy[-1].split()) > _REFLOW_ORPHAN_MAX_WORDS
        or len(greedy) > 2
    ):
        # No orphan to fix, or more than two lines. The soft-target
        # rebuild balances the FIRST N-1 lines and lets the last take
        # whatever remains, which is only reliably an improvement at
        # N == 2. At N >= 3 it can hand the last line MORE than greedy
        # did and break an inline tag across rows on the way:
        #
        #   greedy    * Builds an {@link Arguments} triple for {@link
        #             * #testCreateSzException}: an error code, the
        #             * exception class it should map to, and a fresh
        #             * random message.
        #   rebuilt   * Builds an {@link Arguments} triple for {@link
        #             * #testCreateSzException}: an error code, the
        #             * exception class it should map to, and a fresh
        #             * random message.        <- last line now longest
        #
        # Fixing the N >= 3 distribution needs a real line-breaking
        # algorithm (and inline-tag atomicity) rather than a single
        # target width, so this stays scoped to the two-line case
        # where a 1-3 word orphan is both most glaring and cheaply
        # fixed. `//` comment reflow keeps its unconditional balance
        # from 0.6.0 and is unaffected.
        return greedy

    # Pass 2 — rebuild against the soft target.
    total_content = sum(len(ln) for ln in greedy)
    target = (total_content + len(greedy) - 1) // len(greedy)
    rebuilt: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = current + " " + word
        over_hard_cap = len(candidate) > max_content
        over_soft_target = len(candidate) > target
        can_still_break = len(rebuilt) + 1 < len(greedy)
        if over_hard_cap or (over_soft_target and can_still_break):
            rebuilt.append(current)
            current = word
        else:
            current = candidate
    rebuilt.append(current)
    # The rebuild must not cost a line, and target-driven fill can
    # overshoot the hard cap when a single word straddles a target
    # boundary. Either way, fall back to greedy.
    if (
        len(rebuilt) <= len(greedy)
        and all(len(ln) <= max_content for ln in rebuilt)
    ):
        return rebuilt
    return greedy


def _javadoc_reflow_words(
    words: list[str], prefix: str
) -> list[str]:
    """Reflow javadoc prose words to fit under
    `_MAX_LINE - len(prefix)`, balanced per
    `_balanced_reflow_words`. Returns content strings with no prefix
    and no trailing newline."""
    return _balanced_reflow_words(
        words, _MAX_LINE - len(prefix), only_when_orphaned=True
    )


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


def _has_orphan_continuation(
    line_widths: list[int],
    lines: list[str],
    cap: int = _MAX_LINE,
) -> bool:
    """Return True iff any line in the paragraph is short enough
    that the first word of the next line would have fit on it
    (with one space). `line_widths` is the rendered width of
    each line including its prefix; `lines` are the un-prefixed
    contents used to extract the next line's first word.

    Shared by `_javadoc_needs_reflow` (uniform-prefix prose
    paragraphs) and the @tag-continuation reflow decision in
    `_emit_javadoc_block` (variable-prefix descriptions where
    the first line sits at `* @tag NAME ` and continuations
    sit at the continuation column).
    """
    for i in range(len(line_widths) - 1):
        next_words = lines[i + 1].split()
        if not next_words:
            continue
        if line_widths[i] + 1 + len(next_words[0]) <= cap:
            return True
    return False


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
    if any(len(line) > max_content for line in lines):
        return True
    widths = [len(prefix) + len(line) for line in lines]
    return _has_orphan_continuation(widths, lines)


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
        # with the `* ` prefix. Detect BOTH the raw `<pre>` /
        # `</pre>` tags and their HTML-escaped `&lt;pre&gt;` /
        # `&lt;/pre&gt;` variants (used when the surrounding
        # javadoc must escape `<` to prevent it being parsed as
        # HTML, e.g. inside another HTML tag).
        if in_pre:
            emitter.newline()
            if line == "":
                emitter.write(indent + " *")
            else:
                emitter.write(star_prefix + line)
            if "</pre>" in line or "&lt;/pre&gt;" in line:
                in_pre = False
            i += 1
            continue

        has_open = "<pre>" in line or "&lt;pre&gt;" in line
        has_close = "</pre>" in line or "&lt;/pre&gt;" in line
        if has_open and not has_close:
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
            # Decide whether to reflow. The first description
            # line sits at `* @tag NAME ` (column = full_tag_col);
            # continuation lines sit at the continuation column
            # (= len(cont_prefix)). Reflow when any rendered line
            # would overflow 80 chars OR there's an orphan
            # continuation (the shared `_has_orphan_continuation`
            # helper handles the variable-prefix case).
            widths = [full_tag_col + len(desc_lines[0])]
            for k in range(1, len(desc_lines)):
                widths.append(len(cont_prefix) + len(desc_lines[k]))
            needs = (
                any(w > _MAX_LINE for w in widths)
                or _has_orphan_continuation(widths, desc_lines)
            )
            if not needs:
                # Emit original lines verbatim. `desc_lines` is
                # guaranteed non-empty here — the `if not
                # desc_lines: ... continue` guard above handled
                # the empty case.
                emitter.newline()
                emitter.write(
                    star_prefix + tag_prefix + desc_lines[0]
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
            # Structural line — a block tag (`<p>`, `<ul>`), a list
            # item, or anything the author indented. Emit verbatim.
            #
            # If it does not fit, say so. Reflowing it is not an
            # option: the indent and the markers are the structure,
            # and merging such a line into its neighbors is what the
            # structural classification exists to prevent. But the
            # formatter must not decline silently either — otherwise a
            # developer hits a checkstyle LineLength failure, runs the
            # formatter, gets no output and no change, and reasonably
            # concludes the formatter is broken. Spec C1's rule is
            # emit AND warn; this is the warn.
            emitter.newline()
            before = emitter.line_count
            emitter.write(star_prefix + line)
            full_line = star_prefix + line
            if (
                len(full_line) > _MAX_LINE
                and not _line_length_exempt(full_line)
            ):
                _fire_wrap_overflow_advisory(
                    emitter, node, before,
                    "javadoc structural line",
                    remedy=(
                        "The line is indented or carries markup, so "
                        "it is preserved rather than reflowed. "
                        "Shorten the text or reduce the indent."
                    ),
                )
            i += 1
            continue

        para_lines = [line]
        j = i + 1
        while j < len(interior):
            nxt = interior[j]
            if nxt == "":
                break
            if not _javadoc_is_prose_line(nxt):
                # Covers the indented case too: an indent alone makes
                # a line non-prose, so there is no separate
                # leading-whitespace test to make here.
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
    comments emit verbatim, with one exception: a `//` comment
    that starts at the current indent column and would render
    past `_MAX_LINE` is reflowed into multiple `// `-prefixed
    lines at the same indent (Phase D — line comment reflow).
    Directive comments (`// CSOFF`, `// CSON`, `// CHECKSTYLE:`,
    `// SUPPRESS`, `// @snippet`) and URL-bearing lines are
    exempt from reflow.

    Multi-line block comments dispatch based on whether they
    are javadoc (`/**` opener):

        - Javadoc — reflow paragraphs and `@tag` descriptions
          to fill lines near 80 chars per the Javadoc Reflow
          spec section. Handled by `_emit_javadoc_block`.
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
        if (
            text.startswith("//")
            and emitter.column == 4 * emitter.indent_level
            and emitter.column + len(text) > _MAX_LINE
            and not _is_directive_line_comment(text)
            and "://" not in text
        ):
            _emit_reflowed_line_comment(emitter, text)
            return
        emitter.write(text)
        return
    if text.startswith("/**"):
        _emit_javadoc_block(emitter, source, node, text)
        return
    # Non-javadoc block comments (`/* … */`) are source-preserved
    # but trailing whitespace inside them is never intentional
    # alignment (any deliberate ASCII-art alignment would be
    # inside a CSOFF region with its own preservation path).
    emitter.write_raw_lines(text, strip_trailing_ws=True)


_LINE_COMMENT_DIRECTIVE_PREFIXES: Final[tuple[str, ...]] = (
    "CSOFF", "CSON", "CHECKSTYLE", "SUPPRESS", "@",
)


def _is_directive_line_comment(text: str) -> bool:
    """Return True if a `//` comment carries a checkstyle /
    suppression directive or starts with a `@`-tag — these
    must not be reflowed because their meaning depends on
    a single-line shape.
    """
    # Strip leading `//` and any space(s); the directive
    # prefix sits immediately after the slashes (with or
    # without intervening whitespace).
    stripped = text[2:].lstrip()
    return stripped.startswith(_LINE_COMMENT_DIRECTIVE_PREFIXES)


def _emit_reflowed_line_comment(
    emitter: Emitter, text: str,
) -> None:
    """Balance-reflow an overlong `// ` comment into multiple
    `// `-prefixed lines at the current indent.

    Continuations sit at the same column as the original
    comment (recorded via `emitter.column` at entry). Each
    reflowed line carries `// ` as its prefix so the result
    re-parses as a sequence of `line_comment` nodes — that's
    what makes Phase D idempotent: pass 2 sees N individual
    short line comments, none of which trigger reflow.

    0.6.0: balanced fill replaces the pre-0.6 greedy fill.
    Greedy packed line 1 to `max_content` and left the
    remainder on line 2, which produced 1-3 word orphans when
    total content only slightly exceeded the per-line budget
    (per `feedback_comment_reflow`: "pack first line tight
    OR balance breaks; never orphan 1-3 words on a
    continuation"). Balanced fill:

      1. Runs greedy first to determine minimum line count `N`.
      2. Computes a soft `target` = total_content / N.
      3. Rebuilds greedily but breaks at word boundary once a
         line reaches `target`, so line lengths are
         roughly-equal across the N lines. Falls back to the
         hard `max_content` cap when the target would produce
         a line over the width limit; falls back to greedy
         output if the rebuild produces more than N lines
         (shouldn't happen for well-formed input, but the
         guard preserves idempotency).
    """
    indent_col = emitter.column
    # Strip leading `// ` or `//` to get the content words.
    if text.startswith("// "):
        content = text[3:]
    elif text.startswith("//"):
        content = text[2:]
    else:
        # Defensive — caller already verified the `//` start.
        emitter.write(text)
        return
    words = content.split()
    if not words:
        emitter.write(text)
        return
    prefix = "// "
    max_content = _MAX_LINE - indent_col - len(prefix)
    if max_content <= 0:
        # Indent eats the whole budget — emit verbatim and
        # let the C1 emit-and-warn behavior surface the
        # overflow.
        emitter.write(text)
        return
    lines = _balanced_reflow_words(words, max_content)

    indent_str = " " * indent_col
    emitter.write(prefix + lines[0])
    for line in lines[1:]:
        emitter.newline()
        emitter.write(indent_str + prefix + line)


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
    """Emit `COND ? CONSEQUENCE : ALTERNATIVE` with tier
    selection per the spec's "Line Continuation / Ternary
    Operator" section.

    Tiers:

        - **T1 (single line)**: `COND ? CONS : ALT` on one line.
        - **T2**: break before `?`, keep `? CONS : ALT` together
          on a continuation line at single-indent past the
          statement (`(indent_level + 1) * 4`).
        - **T3**: break before both `?` and `:`; each value on
          its own continuation line; `:` aligns with `?`
          vertically (same continuation column).

    Tier 4 (parenthesize long value branches) is not yet
    implemented — when T3 itself overflows, the formatter
    commits T3 anyway per the spec C1 emit + warn rule.

    Per "Whitespace and Operator Spacing", `?` and `:` each
    get single space on each side. The spec also requires
    nested ternaries to be wrapped in explicit grouping
    parentheses ("Miscellaneous Clarifications / Nested
    ternary"). If the source author wrote a nested ternary
    without parens, the formatter re-emits the same shape —
    the spec violation is the developer's, not the
    formatter's invention.
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

    cont_indent = " " * ((emitter.indent_level + 1) * 4)

    def emit_t1() -> None:
        _emit_node(emitter, source, cond)
        emitter.write(" ? ")
        _emit_node(emitter, source, consequence)
        emitter.write(" : ")
        _emit_node(emitter, source, alternative)

    def emit_t2_at(indent: str) -> None:
        _emit_node(emitter, source, cond)
        emitter.newline()
        emitter.write(indent)
        emitter.write("? ")
        consequence_start = emitter.line_count
        _emit_node(emitter, source, consequence)
        if emitter.line_count > consequence_start:
            # Item 8: consequence wrapped multi-line; break
            # before `:` so the alternative lands at the
            # same continuation column as `?` instead of
            # stranding `: alternative` on the consequence's
            # final wrapped line. Morphs T2 into a T2/T3
            # hybrid when the consequence forces it — the
            # spec's "Line Continuation / Ternary Operator"
            # rule about `:` aligning with `?` applies.
            emitter.newline()
            emitter.write(indent)
            emitter.write(": ")
        else:
            emitter.write(" : ")
        _emit_node(emitter, source, alternative)

    def emit_t3_at(indent: str) -> None:
        _emit_node(emitter, source, cond)
        emitter.newline()
        emitter.write(indent)
        emitter.write("? ")
        _emit_node(emitter, source, consequence)
        emitter.newline()
        emitter.write(indent)
        emitter.write(": ")
        _emit_node(emitter, source, alternative)

    def emit_t2() -> None:
        emit_t2_at(cont_indent)

    def emit_t3() -> None:
        emit_t3_at(cont_indent)

    # Spec C6 paren-aligned ternary: when an enclosing
    # grouping `(` is in scope, prefer aligning `?` / `:`
    # under the column immediately after the `(`. Same shape
    # as the binary-expression paren-aligned candidate
    # (`emit_paren_aligned` in `_emit_binary_expression`).
    #
    # Two paren-aligned candidates, tried in priority order
    # before falling back to the standard +4-indent T2/T3:
    #
    #   - `emit_paren_t2` — break before `?` only, with the
    #     `? consequence : alternative` continuation aligned
    #     under the paren column. Used when both value
    #     branches fit on one continuation line at that
    #     column.
    #   - `emit_paren_t3` — break before both `?` and `:`,
    #     each on its own line at the paren column. Used
    #     when the value branches are too long to share a
    #     line.
    align_col = emitter.paren_align_col
    paren_indent = " " * align_col if align_col is not None else ""

    def emit_paren_t2() -> None:
        # Item 9 (0.5.0): PRESERVE paren_align_col across the
        # recursive emit of consequence / alternative so an
        # inner binary chain that wraps multi-line aligns its
        # continuation operators under the same column as the
        # ternary's `?` / `:` (rather than landing at the
        # cumulative `+4` indent and producing a "staircase").
        # Nested grouping parens inside the consequence /
        # alternative still re-set paren_align_col
        # independently via `_emit_parenthesized_expression`,
        # and the binary wrap engine itself clears
        # paren_align_col before emitting individual operands
        # — so this doesn't leak the ternary's paren context
        # into operand-internal expressions.
        emit_t2_at(paren_indent)

    def emit_paren_t3() -> None:
        # Same paren_align_col inheritance as emit_paren_t2.
        emit_t3_at(paren_indent)

    # Item 8 invariant for ternary T1 — manually try T1 with
    # newline-detection gate. If the condition / consequence /
    # alternative emit produces ANY newlines internally, T1 is
    # NOT a true single-line shape and we must fall through to
    # T2 / T3 (which break before `?` or before both `?` and
    # `:`, properly signaling the multi-line shape). Same
    # anti-stranding principle as the binary P1 newline gate
    # at the top of `_emit_binary_expression`: a width-only
    # check accepts "looks single-line in total chars but
    # actually wrapped internally," which produces ugly
    # output where the inner construct's wrap point and the
    # outer construct's continuation collide visually.
    effective_max = _MAX_LINE - emitter.tail_reserve
    t1_saved = emitter.snapshot()
    emit_t1()
    t1_fits = (
        emitter.last_lines_max_width(t1_saved[0]) <= effective_max
        and emitter.line_count == t1_saved[0]
    )
    if t1_fits:
        return
    emitter.restore(t1_saved)

    # Fall-through cascade. When paren_align_col is set,
    # prefer the paren-aligned T2 / T3 shapes over the
    # +4-indent T2 / T3 (so a parenthesized ternary's
    # `?` / `:` line up under the open paren, not at the
    # cumulative `+4` column).
    cascade_start = t1_saved[0]
    if align_col is not None:
        try_priorities(
            emitter,
            [emit_paren_t2, emit_paren_t3, emit_t2, emit_t3],
        )
    else:
        try_priorities(emitter, [emit_t2, emit_t3])
    _fire_wrap_overflow_advisory(
        emitter, node, cascade_start, "ternary expression"
    )


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
    """Emit `{ … }` for an array initializer with wrap cascade.

    Per docs/java-coding-standards.md §"Array initializers":

        - Priority 1 (inline): `{ a, b, c }` on one line. Single
          space inside non-empty braces; `{}` for empty.
        - Priority 3 (greedy multi-line): `{` at end of the
          calling line, elements greedy-packed at block+4 with
          NO middle-line orphans (each middle continuation line
          carries ≥ 2 elements; the last line may carry 1),
          closing `};` on its own line at the calling context's
          indent.
        - Priority 4 (one per line): fires when Priority 3 would
          place a single element on a middle line, or when any
          element is too long to share its line.

    Multi-dimensional arrays (any child element is itself an
    `array_initializer`) skip Priority 3 for the outer array
    per the spec: sub-arrays land one-per-line for readability.
    Each sub-array then recursively runs its own cascade.

    Priority 2 (break BEFORE the `=`) is not a decision at this
    emitter's level — it lives at the caller
    (`_emit_variable_declarator` / `_emit_assignment_expression`)
    which speculatively emits with `Emitter._array_init_inline_only
    = True` before deciding whether to break at `=` or fall to
    this emitter's multi-line cascade.

    Applies uniformly to both `array_initializer` and
    `element_value_array_initializer` (annotation-value array
    literals) — the cascade owns the shape regardless of source
    layout, so a multi-row `@Foo(names = { "a", "b" })` is
    re-flowed to the canonical single-line or multi-line form
    the same as a variable initializer would be.
    """
    elements = [c for c in node.named_children]
    if not elements:
        emitter.write("{}")
        return

    if emitter._array_init_inline_only:
        # Caller (variable_declarator / assignment_expression
        # Step 1 or Step 2) is speculating a single-line shape.
        # Emit inline; if the width doesn't fit, the caller will
        # see the overflow and try the next tier.
        _emit_array_init_inline(emitter, source, node, elements)
        return

    # Cascade.
    effective_max = _MAX_LINE - emitter.tail_reserve
    is_multi_dim = any(
        c.type == "array_initializer" for c in elements
    )

    # Priority 1: try inline all.
    p1_saved = emitter.snapshot()
    _emit_array_init_inline(emitter, source, node, elements)
    if (
        emitter.line_count == p1_saved[0]
        and emitter.last_lines_max_width(p1_saved[0]) <= effective_max
    ):
        return
    emitter.restore(p1_saved)

    # Priority 3 (skipped for multi-dim per spec).
    if not is_multi_dim:
        p3_saved = emitter.snapshot()
        had_orphan = _emit_array_init_multiline(
            emitter, source, node, elements, one_per_line=False
        )
        p3_fits = (
            emitter.last_lines_max_width(p3_saved[0]) <= effective_max
            and not had_orphan
        )
        if p3_fits:
            return
        emitter.restore(p3_saved)

    # Priority 4: one element per line. Spec C1 emit-and-warn
    # fallback — commits unconditionally; the enclosing
    # variable_declarator / assignment_expression / statement
    # wrapper is responsible for firing the overflow advisory
    # if its own final shape still overflows.
    _emit_array_init_multiline(
        emitter, source, node, elements, one_per_line=True
    )


def _emit_array_init_inline(
    emitter: Emitter,
    source: bytes,
    node: Node,
    elements: list[Node],
) -> None:
    """Emit `{ a, b, c }` on one line (Priority 1)."""
    emitter.write("{ ")
    for index, e in enumerate(elements):
        if index > 0:
            emitter.write(", ")
        _emit_node(emitter, source, e)
    emitter.write(" }")


def _emit_array_init_multiline(
    emitter: Emitter,
    source: bytes,
    node: Node,
    elements: list[Node],
    one_per_line: bool,
) -> bool:
    """Emit the multi-line array shape used by Priority 3 (when
    `one_per_line=False`) and Priority 4 (when `one_per_line=True`).

    Layout:

        {
            <elements at block+4 indent>
        }

    Under Priority 3, elements greedy-pack across continuation
    lines, breaking to a new line when adding the next element
    would overflow `_MAX_LINE - tail_reserve` OR when the
    element's own emission spans multiple rows.

    Under Priority 4, each element gets its own continuation
    line.

    Returns `had_middle_line_orphan` — True when a middle
    continuation line (any line except the last) ended up
    carrying only one element. Only meaningful for the
    Priority 3 caller, which uses the signal to fall back to
    Priority 4. Priority 4 callers ignore the return value.
    """
    emitter.write("{")
    emitter.newline()
    emitter.push_indent()
    effective_max = _MAX_LINE - emitter.tail_reserve

    # Element-per-line counts across all continuation lines.
    # `line_element_counts[i]` = number of elements finalized
    # onto the i-th continuation line. Used post-emit to detect
    # middle-line orphans (Priority 3's guard rule).
    line_element_counts: list[int] = []
    cur_line_count = 0
    emitter.write_indent()

    for index, e in enumerate(elements):
        first_on_line = cur_line_count == 0
        if first_on_line:
            # First element on this line — emit as-is at the
            # current position (already at block+4 indent).
            _emit_node(emitter, source, e)
            cur_line_count = 1
            continue
        if one_per_line:
            # P4 mode — no need to speculate a pack; break
            # unconditionally to a fresh continuation line.
            emitter.write(",")
            emitter.newline()
            line_element_counts.append(cur_line_count)
            cur_line_count = 0
            emitter.write_indent()
            _emit_node(emitter, source, e)
            cur_line_count = 1
            continue
        # P3 mode — try packing "next element" on the current
        # line, backtrack + break-before if it doesn't fit.
        pack_saved = emitter.snapshot()
        emitter.write(", ")
        _emit_node(emitter, source, e)
        pack_ok = (
            emitter.last_lines_max_width(pack_saved[0])
            <= effective_max
            and emitter.line_count == pack_saved[0]
        )
        if pack_ok:
            cur_line_count += 1
            continue
        emitter.restore(pack_saved)
        emitter.write(",")
        emitter.newline()
        line_element_counts.append(cur_line_count)
        cur_line_count = 0
        emitter.write_indent()
        _emit_node(emitter, source, e)
        cur_line_count = 1

    line_element_counts.append(cur_line_count)

    emitter.pop_indent()
    emitter.newline()
    emitter.write_indent()
    emitter.write("}")

    had_middle_orphan = False
    if not one_per_line and len(line_element_counts) > 1:
        for count in line_element_counts[:-1]:
            if count == 1:
                had_middle_orphan = True
                break
    return had_middle_orphan


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
    emitter.write("new ")
    for child in node.named_children:
        # Spec "Whitespace and Operator Spacing": single space
        # before the opening `{` of an array initializer that
        # follows `[]` (or `[N]`) dimensions. `new Type[] { X }`
        # is canonical; `new Type[]{ X }` is a 0.5.0 bug where
        # the emitter walked `dimensions` then `array_initializer`
        # back-to-back without inserting the required separator.
        if child.type == "array_initializer":
            emitter.write(" ")
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
    # Brace placement per the standards' "Switch Statements and
    # Expressions": the opening brace goes on the SAME line
    # (control-flow style), i.e. `switch (value) {`. Pre-0.7.0 this
    # emitted an unconditional newline, giving every switch an
    # Allman brace — 98 sites across the four consumer trees, and
    # the same-line form was never produced at all. Checkstyle does
    # not gate brace placement on `LITERAL_SWITCH`, so it went
    # unnoticed.
    #
    # The "Multi-line Conditions" exception still applies: when the
    # condition's RENDERED output spans more than one line, the
    # brace drops to its own line at the switch's indent so the
    # condition stays visually separate from the body. Mirrors
    # `_emit_if_statement`, including the +2 tail reserve for the
    # `) {` that follows the condition.
    emitter.write("switch ")
    cond_start_line_count = emitter.line_count
    prev_reserve = emitter.set_tail_reserve(
        emitter.tail_reserve + 2
    )
    try:
        _emit_node(emitter, source, cond)
    finally:
        emitter.set_tail_reserve(prev_reserve)
    if emitter.line_count > cond_start_line_count:
        emitter.newline()
        emitter.write_indent()
    else:
        emitter.write(" ")
    _emit_node(emitter, source, block)


def _emit_switch_block(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `{ CASES }` for a switch's case body.

    Caller positions the emitter at the column where `{`
    starts. Case rules (`switch_rule` or `switch_block_-
    statement_group`) are emitted at indent_level + 1.
    `line_comment` and `block_comment` children that
    tree-sitter parks at the `switch_block` level (typically
    a comment sitting between two `case` groups, which the
    grammar can't unambiguously attach to either side) are
    emitted at the same indent so the comment is preserved
    rather than silently dropped.
    """
    items = [
        c for c in node.named_children
        if c.type in (
            "switch_rule",
            "switch_block_statement_group",
            "line_comment",
            "block_comment",
        )
    ]
    emitter.write("{")
    emitter.newline()
    _emit_indented_member_list(emitter, source, items)
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
        emitter.write_raw_lines(
            _node_source_text(source, node), strip_trailing_ws=True
        )
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
    """Emit `yield VALUE;` (Java 14+ switch-expression yield).

    `yield` always requires a value in valid Java — bare `yield;`
    is semantically invalid even though tree-sitter's error-
    tolerant grammar may accept it. Refuse rather than emit
    broken output so the caller sees a clear diagnostic.
    """
    children = list(node.named_children)
    if not children:
        raise NotImplementedError(
            "yield_statement missing value — bare `yield;` is "
            "semantically invalid Java; the input likely has a "
            "syntax error the grammar recovered past."
        )
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

    Header wrapping follows the priorities in the spec's
    "Record Declarations" section. Priority 1 is the whole header on one line.
    When that overflows, priority 2 moves the `implements`
    clause to its own single-indented continuation line and
    leaves the components where they are — the components only
    break (priority 3 paren-aligned, priority 4 double-indented)
    if they still do not fit once `implements` has moved out of
    their way. That ordering is why the components are emitted
    with no tail reserve for the `implements` clause: reserving
    for it would break the component list to make room for text
    that priority 2 is about to relocate, producing the partially
    broken shape the spec's "Anti-pattern" section forbids.
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
    # Column where `record` (or the modifiers preceding it)
    # begins — the anchor for the single-indent continuation
    # used by priority 2 and beyond.
    start_col = emitter.column
    if modifiers_node is not None:
        _emit_node(emitter, source, modifiers_node)
    emitter.write("record ")
    _emit_node(emitter, source, name)
    if type_parameters_node is not None:
        _emit_node(emitter, source, type_parameters_node)

    # `force_wrap=True` engages the spec's parameter cascade
    # (single-line, then paren-aligned one-per-line, then next-line
    # double-indent) and, importantly, suppresses
    # `_emit_formal_parameters`' default source-preservation. Without
    # it a component list that spanned rows in the original was
    # replayed verbatim, so an author's packed layout was re-indented
    # rather than re-flowed and could land well over the limit —
    # `SzAddressByParts` came out at 88 columns that way. Records get
    # the same treatment as method parameters, from the same code.
    def emit_components() -> None:
        _emit_formal_parameters(
            emitter, source, params_node,
            force_wrap=True,
            p3_indent_col=start_col + 8,
        )

    # Priority 1 — the entire header on one line.
    saved = emitter.snapshot()
    emit_components()
    # A component list that wrapped itself puts the closing `)` on a
    # continuation row, and an `implements` clause written after it
    # then trails that row — a shape none of the record-header
    # priorities produce (3 and 4 both give `implements` its own
    # line). Width alone does not catch it: once the components have
    # broken, every row can sit under the limit, so the check below
    # would pass and commit. Reject it explicitly, the same way the
    # argument-list cascade rejects an argument that wrapped.
    params_wrapped = emitter.line_count > saved[0]
    if super_interfaces_node is not None:
        emitter.write(" ")
        _emit_node(emitter, source, super_interfaces_node)
    if super_interfaces_node is not None and (
        emitter.last_lines_max_width(saved[0]) > _MAX_LINE
        or params_wrapped
    ):
        # Priority 2+ — re-emit with the `implements` clause on
        # its own continuation line. The component list runs its
        # own cascade unchanged, so a list that fits inline stays
        # inline (priority 2) and one that does not falls to
        # paren-aligned one-per-line (priority 3) or next-line
        # double-indent (priority 4) on its own terms.
        #
        # `last_lines_max_width` rather than `emitter.column`
        # because the component list may itself have rendered
        # multi-line, in which case the overflow is on a row the
        # final column no longer reflects.
        emitter.restore(saved)
        emit_components()
        _emit_extends_implements_p2_p3(
            emitter,
            source,
            None,
            super_interfaces_node,
            " " * (start_col + 4),
        )
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
    _emit_indented_member_list(
        emitter, source, list(body.named_children)
    )
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
        emitter.write_raw_lines(
            _node_source_text(source, cond), strip_trailing_ws=True
        )
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
    named child followed by an `argument_list`. Per the
    statement-emission contract (each statement writes its
    own trailing terminator), this emitter writes the closing
    `;` itself.
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
    # Reserve 1 char for the trailing `;` while the arg list
    # wraps — without this, P1 could commit args ending at
    # column 80 and the trailing `;` would push the line to
    # 81. Mirrors the throw / return / expression_statement
    # convention.
    prev_reserve = emitter.set_tail_reserve(
        emitter.tail_reserve + 1
    )
    try:
        _emit_node(emitter, source, args)
    finally:
        emitter.set_tail_reserve(prev_reserve)
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
    prev_reserve = emitter.set_tail_reserve(
        emitter.tail_reserve + 1
    )
    try:
        _emit_node(emitter, source, expr)
    finally:
        emitter.set_tail_reserve(prev_reserve)
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
    """Emit `catch (PARAM) { ... }` with multi-catch wrap.

    Single-type catch (`catch (Ex e)`) emits inline
    unconditionally.

    Multi-type catch (`catch (A | B | C e)`) tries two shapes:

      - Priority 1 — inline: `catch (A | B | C e) {`. Committed
        when the whole header fits within 80 chars including
        the trailing ` {` that opens the body block.
      - Priority 2 — paren-aligned one-type-per-line. First
        type stays on the `catch (` line. Each subsequent `|
        Type` breaks to its own continuation line with `|`
        aligned under the column right after `(`. The
        parameter name and closing `) ` sit on the final type's
        line. Example:

            } catch (ClassNotFoundException
                     | NoSuchMethodException
                     | InvocationTargetException
                     | IllegalAccessException e) {

    Pre-0.7.0 the catch_type emitter had no wrap logic and
    long multi-catch clauses (e.g. `WrapperMain.java:66` with
    four exception types) collapsed to a single 125-char
    line with no `FormatterWarning`.
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

    # Look for a multi-type catch. Refuse annotations /
    # modifiers on the parameter here (same rule as
    # `_emit_catch_formal_parameter`); reserved for a future
    # annotation-aware pass.
    catch_type: Node | None = None
    for child in cfp.named_children:
        if child.type == "modifiers":
            raise NotImplementedError(
                "catch_formal_parameter with modifiers or "
                "annotations is not yet supported."
            )
        if child.type == "catch_type":
            catch_type = child
    name_node = cfp.child_by_field_name("name")
    types: list[Node] = []
    if catch_type is not None:
        types = [c for c in catch_type.children if c.is_named]

    if catch_type is None or name_node is None or len(types) < 2:
        # Single-type catch (or grammar shape the wrap engine
        # doesn't handle) — emit inline via the standard
        # dispatch path. Pre-existing behavior preserved.
        emitter.write("catch (")
        _emit_node(emitter, source, cfp)
        emitter.write(") ")
        _emit_node(emitter, source, body)
        return

    # Multi-type catch cascade.
    cascade_start = emitter.line_count
    # Priority 1 — inline: `catch (A | B | C e) {`. The `+ 1`
    # accounts for the `{` that `_emit_block` writes on the
    # current line right after `) `. Wider tail context (e.g.
    # a trailing `finally` on the same source row — rare) is
    # already covered by `emitter.tail_reserve`.
    p1_saved = emitter.snapshot()
    emitter.write("catch (")
    for index, t in enumerate(types):
        if index > 0:
            emitter.write(" | ")
        _emit_node(emitter, source, t)
    emitter.write(" ")
    _emit_node(emitter, source, name_node)
    emitter.write(") ")
    p1_fits = (
        emitter.column + 1 + emitter.tail_reserve <= _MAX_LINE
    )
    if p1_fits:
        _emit_node(emitter, source, body)
        return
    emitter.restore(p1_saved)

    # Priority 2 — paren-aligned one-type-per-line.
    emitter.write("catch (")
    paren_align_col = emitter.column
    for index, t in enumerate(types):
        if index > 0:
            emitter.newline()
            emitter.write(" " * paren_align_col)
            emitter.write("| ")
        _emit_node(emitter, source, t)
    emitter.write(" ")
    _emit_node(emitter, source, name_node)
    emitter.write(") ")
    # Spec C1 emit-and-warn: if a single type name is itself
    # too long to fit at the paren-aligned column, the C1
    # advisory fires here so the developer sees a
    # first-class signal to shorten the type name.
    _fire_wrap_overflow_advisory(
        emitter, node, cascade_start, "multi-catch"
    )
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
    # name. `child_by_field_name(...)` returns only the first;
    # we collect ALL siblings sharing each field name so the
    # `for (i = 0, j = 0; ...; i++, j++)` shape emits with all
    # init / update expressions preserved.
    inits: list[Node] = []
    updates: list[Node] = []
    for index, child in enumerate(node.children):
        fn = node.field_name_for_child(index)
        if fn == "init":
            inits.append(child)
        elif fn == "update":
            updates.append(child)

    condition = node.child_by_field_name("condition")

    # 0.5.0 item 5 — when the source had the for-header
    # spanning multiple rows, the developer chose to break
    # init / cond / update onto separate lines (typically
    # because the single-line form was too long). Earlier
    # behavior emitted the source TEXT verbatim, which
    # preserved the developer's source columns even when
    # surrounding context had shifted the for-statement to
    # a different block depth — producing the
    # `for (int x = …;\n    x >= 0;\n    x = …)` staircase
    # where the continuation cols don't match the
    # `for (` open paren's `paren_col` for the new context.
    #
    # Fix: re-emit the header at the current `paren_col`,
    # paren-aligning the semicolon-separated parts. The
    # actual emission is identical to the single-line→too-
    # wide fallback below (the paren-aligned cascade is the
    # canonical multi-row for-header shape); just skip the
    # single-line attempt and go straight to paren-aligned
    # when the source was already multi-row.
    source_was_multi_row = (
        body.start_point[0] != node.start_point[0]
    )

    # Single-row source: build the header inline. After
    # emission, check whether wrapping inside the
    # init / condition / update introduced any newlines —
    # if so, switch the brace to Allman per the spec's
    # "Brace Placement / Exception: Multi-Line Conditions"
    # rule (the brace decision must reflect the FINAL
    # rendered shape, not the source's input shape).
    header_start = emitter.snapshot()

    def emit_for_init_section() -> None:
        """Init expression(s) + trailing `;`.

        `local_variable_declaration` (the C-style declaring
        form `for (int i = 0; ...; ...)`) carries its own
        trailing `;`. Bare-expression init lists and
        comma-separated init expressions need an explicit
        `;` after the last init.
        """
        if not inits:
            emitter.write(";")
        elif (
            len(inits) == 1
            and inits[0].type == "local_variable_declaration"
        ):
            _emit_node(emitter, source, inits[0])
        else:
            for index, init in enumerate(inits):
                if index > 0:
                    emitter.write(", ")
                _emit_node(emitter, source, init)
            emitter.write(";")

    emitter.write("for (")
    paren_col = emitter.column

    def emit_header_paren_aligned() -> None:
        """Emit init / cond / update with paren-aligned semicolon
        separators — each clause on its own line, continuation
        col = `paren_col`. Used both when the single-line
        attempt overflows AND when the source had the for-
        header multi-row to begin with (0.5.0 item 5).
        """
        cont_indent = " " * paren_col
        prev_reserve = emitter.set_tail_reserve(
            emitter.tail_reserve + 2
        )
        try:
            emit_for_init_section()
            if condition is not None:
                emitter.newline()
                emitter.write(cont_indent)
                _emit_node(emitter, source, condition)
            emitter.write(";")
            if updates:
                emitter.newline()
                emitter.write(cont_indent)
                for index, update in enumerate(updates):
                    if index > 0:
                        emitter.write(", ")
                    _emit_node(emitter, source, update)
        finally:
            emitter.set_tail_reserve(prev_reserve)

    if source_was_multi_row:
        # Spec "Brace Placement / Exception: Multi-Line
        # Conditions" — a multi-row `for` header is itself the
        # signal that triggers Allman brace placement. Preserve
        # the developer's multi-row layout (re-anchored at the
        # paren column per item 5) rather than collapsing to
        # single-line, since collapsing would lose the
        # Allman-trigger and visually re-pack a header the
        # developer deliberately spread across lines.
        emit_header_paren_aligned()
        emitter.write(")")
    else:
        # Single-row source: try single-line first, fall to
        # paren-aligned only if the rendered text overflows
        # _MAX_LINE.
        prev_reserve = emitter.set_tail_reserve(
            emitter.tail_reserve + 2
        )
        try:
            emit_for_init_section()
            if condition is not None:
                emitter.write(" ")
                _emit_node(emitter, source, condition)
            emitter.write(";")
            for index, update in enumerate(updates):
                if index == 0:
                    emitter.write(" ")
                else:
                    emitter.write(", ")
                _emit_node(emitter, source, update)
        finally:
            emitter.set_tail_reserve(prev_reserve)
        emitter.write(")")

        # If the header ended up too wide on a single line —
        # no inner wrap fired (e.g. no `&&`/`||` for the
        # condition wrap to break at) but the rendered text
        # still exceeds `_MAX_LINE` — backtrack and emit a
        # paren-aligned wrap at the `for (` column.
        effective_max = _MAX_LINE - emitter.tail_reserve
        single_line_header = (
            emitter.line_count == header_start[0]
        )
        header_too_wide = (
            emitter.last_lines_max_width(header_start[0])
            > effective_max
        )
        if single_line_header and header_too_wide:
            emitter.restore(header_start)
            emitter.write("for (")
            emit_header_paren_aligned()
            emitter.write(")")
    # Three reasons to switch to Allman brace placement:
    #   (1) the header itself emitted newlines (multi-row
    #       source or wrap inside the header),
    #   (2) the body block opens on a different source row
    #       than the `for` keyword (developer-authored Allman
    #       in the source), or
    #   (3) the inline form `for (...) {` would push the line
    #       past _MAX_LINE — appending ` {` adds 2 chars, so
    #       a header line at column > _MAX_LINE - 2 forces
    #       Allman to keep the header within budget.
    body_on_new_row = body.start_point[0] != node.start_point[0]
    inline_form_overflows = (
        emitter.column + 2 > _MAX_LINE
    )
    if (
        emitter.line_count > header_start[0]
        or body_on_new_row
        or inline_form_overflows
    ):
        emitter.newline()
        emitter.write_indent()
        _emit_node(emitter, source, body)
    else:
        emitter.write(" ")
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

    # 0.7.0 — enhanced-for header wrapping. Pre-0.7.0 the header was
    # written straight out with no cascade at all, so a long one simply
    # overflowed (25 sites across the four consumer trees, up to 103
    # chars). Basic `for` already wrapped; this was a missing node type
    # rather than a policy gap.
    #
    # Primary break is BEFORE the `:`, with the colon leading the
    # continuation line so the iterable stays visually attached to it:
    #
    #     for (Map.Entry<String, Map<String, SzFlagMetaData>> entry
    #             : parent.entrySet())
    #     {
    #
    # When the header breaks, the opening brace goes Allman — the same
    # "Multi-line Conditions" exception that already governs `if`,
    # `while` and (since 0.7.0) `switch`, so a wrapped header stays
    # visually separate from the body.
    saved = emitter.snapshot()
    emitter.write("for (")
    _emit_node(emitter, source, type_node)
    emitter.write(" ")
    _emit_node(emitter, source, name_node)
    # Reserve the `) {` that follows the iterable on the inline form.
    prev_reserve = emitter.set_tail_reserve(emitter.tail_reserve + 3)
    try:
        emitter.write(" : ")
        _emit_node(emitter, source, value_node)
    finally:
        emitter.set_tail_reserve(prev_reserve)
    # Match the `+ 3` budgeted above: the reserve the value emitted
    # under was `inherited + 3`, so the fit test has to account for
    # the inherited part too or the two disagree by exactly that
    # amount. Nonzero inherited reserve is reachable — inside a
    # lambda block or anonymous-class body, or within a `throw`
    # argument — which otherwise let an identical header at an
    # identical indent wrap or not purely by enclosing context.
    inline_fits = (
        emitter.line_count == saved[0]
        and emitter.column + 3 + emitter.tail_reserve <= _MAX_LINE
    )
    if inline_fits:
        emitter.write(") ")
        _emit_node(emitter, source, body)
        return
    emitter.restore(saved)

    emitter.write("for (")
    _emit_node(emitter, source, type_node)
    emitter.write(" ")
    _emit_node(emitter, source, name_node)
    emitter.newline()
    emitter.push_indent()
    emitter.push_indent()
    emitter.write_indent()
    emitter.write(": ")
    # Reserve the `)` this path still has to write after the value.
    # `emitter.restore(saved)` above also restored `_tail_reserve`,
    # so the inline path's `+ 3` is gone and without this the value
    # emits against the bare limit and the `)` lands in column 81 —
    # silently, idempotent on re-run, and so beyond the reach of a
    # reformat.
    # Every sibling construct reserves for its own closer: basic
    # `for` and `if` reserve 2 for `) {`, this path needs 1 because
    # the Allman brace moves to the next line.
    prev_close_reserve = emitter.set_tail_reserve(
        emitter.tail_reserve + 1
    )
    try:
        _emit_node(emitter, source, value_node)
    finally:
        emitter.set_tail_reserve(prev_close_reserve)
    emitter.write(")")
    emitter.pop_indent()
    emitter.pop_indent()
    emitter.newline()
    emitter.write_indent()
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
        emitter.write_raw_lines(
            _node_source_text(source, condition),
            strip_trailing_ws=True,
        )
        emitter.newline()
        emitter.write_indent()
        _emit_node(emitter, source, body)
    else:
        # Single-row source: emit the condition inline and
        # check whether wrapping inside it introduced newlines.
        # If so, switch to Allman brace — the rendered output
        # has a multi-row header even though the source didn't.
        # Bump tail_reserve so the condition's wrap engine
        # accounts for the upcoming `) {` (3 chars: `)`, ` `,
        # `{`) when deciding to wrap.
        cond_start_line_count = emitter.line_count
        prev_reserve = emitter.set_tail_reserve(
            emitter.tail_reserve + 2
        )
        try:
            _emit_node(emitter, source, condition)
        finally:
            emitter.set_tail_reserve(prev_reserve)
        if emitter.line_count > cond_start_line_count:
            emitter.newline()
            emitter.write_indent()
            _emit_node(emitter, source, body)
        else:
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
        prev_reserve = emitter.set_tail_reserve(
            emitter.tail_reserve + 1
        )
        try:
            _emit_node(emitter, source, value)
        finally:
            emitter.set_tail_reserve(prev_reserve)
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
    # Reserve 1 char for the trailing `;` so any binary or
    # call-arg wrap inside the expression accounts for it.
    prev_reserve = emitter.set_tail_reserve(
        emitter.tail_reserve + 1
    )
    try:
        _emit_node(emitter, source, expr)
    finally:
        emitter.set_tail_reserve(prev_reserve)
    emitter.write(";")


def _rhs_has_array_literal(rhs_node: Node) -> bool:
    """Return True when the RHS of an `=`/declarator is an
    array-literal shape whose emission is subject to the array
    initializer's own P1/P3/P4 cascade.

    Two cases:

      - Bare `array_initializer` (`{ a, b, c }`): valid only
        as a `variable_declarator`'s value. `assignment
        _expression` never sees this shape because bare
        reassignment `x = { … }` is not legal Java.
      - `array_creation_expression` (`new Type[] { a, b, c }`)
        that contains an `array_initializer` child. The bare
        `new Type[N]` form (dimensions but no `{ … }`) is not
        an array-literal shape — the wrap engine treats it as
        an ordinary expression.
    """
    if rhs_node.type == "array_initializer":
        return True
    if rhs_node.type == "array_creation_expression":
        for child in rhs_node.named_children:
            if child.type == "array_initializer":
                return True
    return False


def _rhs_is_new_type_array(rhs_node: Node) -> bool:
    """Return True when the RHS is `new Type[] { … }` — the
    variant that skips the break-before-`=` (Priority 2) tier
    per the "Array initializers" spec section. Bare
    `array_initializer` RHS still uses Priority 2 when it
    doesn't fit inline.
    """
    return (
        rhs_node.type == "array_creation_expression"
        and any(
            c.type == "array_initializer"
            for c in rhs_node.named_children
        )
    )


def _emit_assignment_with_array_rhs(
    emitter: Emitter,
    source: bytes,
    node: Node,
    right_node: Node,
    op_text: str,
    cascade_start: int,
    effective_max: int,
    emit_inline_rhs: Callable[[], None],
) -> None:
    """Cascade for `LHS = <array-literal>` assignment_expression.

    Per docs/java-coding-standards.md §"Array initializers":

      - Priority 1: `LHS = { … };` all on one line.
      - Priority 2: SKIPPED for assignment_expression because
        the only valid array-RHS shape here is `new Type[]
        { … }`, and moving `= new Type[] {` onto a
        continuation line at block+4 consumes too much
        horizontal budget for the elements themselves to fit.
        (Priority 2 remains available in
        `_emit_variable_declarator` for the bare `Type x
        = { … }` form.)
      - Priority 3+: no break before `=` — dispatch into the
        array_initializer whose own cascade emits multi-line
        greedy (P3) or one-per-line (P4).

    The Priority 1 attempt sets `emitter._array_init_inline_only`
    so the nested array emits its own P1 inline shape rather
    than committing to a multi-line P3/P4 that we would only
    have discarded.
    """
    # Priority 1: inline all — force array inline.
    saved = emitter.snapshot()
    prev_flag = emitter._array_init_inline_only
    emitter._array_init_inline_only = True
    try:
        emit_inline_rhs()
    finally:
        emitter._array_init_inline_only = prev_flag
    p1_fits = (
        emitter.line_count == saved[0]
        and emitter.last_lines_max_width(saved[0]) <= effective_max
    )
    if p1_fits:
        _fire_wrap_overflow_advisory(
            emitter, node, cascade_start, "assignment"
        )
        return
    emitter.restore(saved)

    # Priority 3+: no break-at-`=`, dispatch and let the array's
    # own cascade choose P3 or P4. Priority 2 is skipped for
    # assignment_expression per the docstring rationale above.
    emit_inline_rhs()
    _fire_wrap_overflow_advisory(
        emitter, node, cascade_start, "assignment"
    )


def _emit_assignment_expression(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `LHS OP RHS` with space-space around the operator.

    Per the "Whitespace and Operator Spacing" spec section's
    assignment-operator row, every assignment operator
    (`=`, `+=`, `-=`, `*=`, `/=`, `%=`, `&=`, `|=`, `^=`,
    `<<=`, `>>=`, `>>>=`) gets exactly one space on each side.
    Grammar fields: `left`, `operator`, `right`.

    Wrap-priority (parallels `_emit_variable_declarator`):

      (1) Inline single-line: if `LHS OP RHS` fits within the
          effective line budget (accounting for any trailing
          tokens the parent will emit via `tail_reserve`),
          use it.
      (2) Break-at-operator single-line: if `LHS\\n    OP RHS`
          at the continuation column fits, use the break form.
          The RHS renders single-line on the continuation; the
          LHS gets its own line up through the identifier.
      (3) Inline with value-wrap: fall back to letting the RHS
          emit its own wrap (arg-list, binary-wrap, method-
          chain, etc.). If the resulting shape still overflows,
          backtrack to the break-at-operator form so the RHS
          gets more horizontal room at the continuation.

    Introduced in 0.6.0 (P1). Before this the assignment
    expression emitted `LHS OP RHS` verbatim with no wrap
    consideration — bare reassignments like
    `x = new String[]{ … };` at deep indent could silently
    overflow 80 chars with no advisory.
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

    # Emit LHS on the current line unconditionally — the wrap
    # is between LHS and RHS (never inside LHS in this emitter;
    # LHS is typically an identifier / field-access / array-
    # access that fits on one line).
    cascade_start = emitter.line_count
    _emit_node(emitter, source, left_node)

    effective_max = _MAX_LINE - emitter.tail_reserve

    def emit_inline_rhs() -> None:
        # Shared inline emission for Step 1 and Step 3 — both
        # emit `" OP RHS"` continuing the LHS line. Kept as a
        # closure so the two steps stay byte-identical
        # regardless of future op-text or spacing changes.
        emitter.write(" ")
        emitter.write(op_text)
        emitter.write(" ")
        _emit_node(emitter, source, right_node)

    # 0.6.0: array-literal RHS gets its own cascade per the
    # spec's "Array initializers" section: P1 inline → SKIP P2
    # for `new Type[] { … }` → array's internal P3/P4 cascade.
    # `_rhs_has_array_literal` returns True for
    # `array_creation_expression` containing an
    # `array_initializer` — the only array-literal shape valid
    # as an assignment RHS (bare `x = { … }` is not legal Java;
    # it only appears in variable declarations).
    if _rhs_has_array_literal(right_node):
        _emit_assignment_with_array_rhs(
            emitter, source, node, right_node, op_text,
            cascade_start, effective_max, emit_inline_rhs,
        )
        return

    # Step 1: try inline emission. Commit when every line
    # (including the LHS + op + RHS-start line AND any lines
    # the RHS's own wrap engine produced internally) fits
    # under `effective_max`.
    #
    # This admits shapes like:
    #     this.env = MyFactory.newBuilder()
    #                         .step1(a)
    #                         .step2(b);
    # where the RHS is a method chain that itself wraps
    # multi-line — the first line (`this.env = MyFactory.new
    # Builder()`) fits under 80, and each chain continuation
    # emitted by the chain wrap engine also fits. Breaking at
    # `=` in this case would just add a redundant newline.
    #
    # Fall through to Step 2 (break-at-`=`) only when the
    # inline shape produces at least one line past
    # `effective_max` — typically because the LHS + op +
    # RHS-start is itself too wide (a long cast + call, e.g.
    # `this.proxyEnvironment = (SzEnvironment) Reflection
    # Utilities.restrictedProxy(` at 88 chars from the 0.6.0
    # consumer trial). In those cases Step 2's break-at-`=`
    # shortens the first line to just `<LHS>`.
    saved = emitter.snapshot()
    emit_inline_rhs()
    inline_fits = (
        emitter.last_lines_max_width(saved[0]) <= effective_max
    )
    if inline_fits:
        return
    emitter.restore(saved)

    # Step 2: try break-at-operator with the RHS at block+4.
    # Continuation indent is one level deeper than the
    # surrounding statement — matches the variable_declarator
    # break-at-`=` shape. The RHS is allowed to wrap
    # internally (nested arg-list / binary chain / method
    # chain that itself wraps) as long as every line stays
    # under `effective_max`. Requiring the RHS to fit on a
    # single line is too strict — a cast-and-call RHS like
    # `(Type) obj.method(a, b)` may fit on line 2 with args
    # at block+4 even if the inline shape overflows. The
    # 0.6.0 consumer trial surfaced this at
    # `SzReplicator.java:994` (a ~88-char assignment_expression
    # committed inline because Step 2 rejected a multi-row
    # RHS whose max-line-width was actually 71).
    p2_saved = emitter.snapshot()
    emitter.newline()
    emitter.push_indent()
    emitter.write_indent()
    emitter.write(op_text)
    emitter.write(" ")
    _emit_node(emitter, source, right_node)
    p2_fits = (
        emitter.last_lines_max_width(p2_saved[0]) <= effective_max
    )
    if p2_fits:
        emitter.pop_indent()
        return
    # `restore()` resets `self._indent` to the snapshot's
    # captured value, so the `push_indent()` above is undone.
    emitter.restore(p2_saved)

    # Step 3: inline + backtrack-on-overflow. Mirrors
    # `_emit_variable_declarator`'s canonical pattern
    # (see its Step 3 for the fuzz-harness rationale that
    # justifies the backtrack). Emit inline first; if any
    # line overflows, restore and commit break-at-`=`
    # unconditionally — even if the break form also
    # overflows, because:
    #
    #   - Consistency with `variable_declarator`: a
    #     `Type x = <long RHS>;` and its bare-reassignment
    #     twin `x = <same long RHS>;` should format
    #     identically (both break at `=`) rather than
    #     diverging on whether the LHS carries a type.
    #   - Idempotency: an earlier inline-unconditional
    #     variant was fuzz-flagged in the sibling
    #     construct — a multi-line source RHS collapsed
    #     to a long single line on pass 1, then broke at
    #     `=` on pass 2 once the value was single-line.
    #     Committing break-at-`=` when inline overflows
    #     converges both passes to the same shape.
    saved = emitter.snapshot()
    emit_inline_rhs()
    inline_overflow = (
        emitter.last_lines_max_width(saved[0]) > _MAX_LINE
        or emitter.column + emitter.tail_reserve > _MAX_LINE
    )
    if not inline_overflow:
        _fire_wrap_overflow_advisory(
            emitter, node, cascade_start, "assignment"
        )
        return
    emitter.restore(saved)
    emitter.newline()
    emitter.push_indent()
    emitter.write_indent()
    emitter.write(op_text)
    emitter.write(" ")
    _emit_node(emitter, source, right_node)
    emitter.pop_indent()
    # Spec C1 emit-and-warn: the break-at-`=` shape may itself
    # overflow when the RHS cannot be broken further (long
    # literal or single-token identifier). Fire the advisory so
    # checkstyle-adjacent tooling and adopters get a first-class
    # signal to hand-split the value — matches every other C1
    # emit-and-warn site (arg-list, binary, chain, ternary).
    _fire_wrap_overflow_advisory(
        emitter, node, cascade_start, "assignment"
    )


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
    # For a single-resource try with a same-line body brace
    # (` {` after the closing `)`), bump `tail_reserve` by
    # 2 so the resource's inline-fit check accounts for the
    # two trailing chars the parent will append after the
    # resource closes. The resource emitter already reserves
    # 1 char for its own `)`; without this bump the ` {`
    # falls outside the budget and a borderline-fit resource
    # lands at 81 chars on disk. Multi-resource breaks Allman,
    # so the body brace lands on its own line and no extra
    # reserve is needed.
    prev_reserve = emitter.tail_reserve
    if len(resources) == 1:
        emitter.set_tail_reserve(prev_reserve + 2)
    try:
        for index, resource in enumerate(resources):
            if index > 0:
                emitter.write(";")
                emitter.newline()
                emitter.write(" " * align_col)
            _emit_node(emitter, source, resource)
    finally:
        emitter.set_tail_reserve(prev_reserve)
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
    # Spec B8 ("Try-with-resources / Single-resource form,
    # P2+"): when `TYPE NAME = VALUE` would overflow the line,
    # break BEFORE `=`. The `=` lands at the start of a
    # continuation line at +4 past the resource's start column.
    #
    # Preference order (matches `_emit_variable_declarator`):
    #   (1) Inline single-line: `TYPE NAME = VALUE` all on one
    #       line with VALUE rendered without internal wrap.
    #   (2) Break-at-`=`: `TYPE NAME` on one line, `= VALUE` on
    #       a continuation line with VALUE single-line. Spec B8
    #       calls this the first fallback — preferred over
    #       letting the value wrap internally.
    #   (3) Inline with value-wrap: emit inline and let VALUE
    #       handle its own multi-line wrap.
    #
    # Detecting "value didn't internally wrap" uses
    # `emitter.line_count` — a clean inline emission produces no
    # additional finalized lines.
    start_col = emitter.column
    effective_max = _MAX_LINE - emitter.tail_reserve

    # Step 1: try inline with no value-wrap.
    saved = emitter.snapshot()
    _emit_node(emitter, source, type_node)
    emitter.write(" ")
    _emit_node(emitter, source, name_node)
    emitter.write(" = ")
    _emit_node(emitter, source, value_node)
    value_introduced_newlines = emitter.line_count > saved[0]
    inline_fits = (
        emitter.last_lines_max_width(saved[0]) <= effective_max
        and emitter.column < effective_max
    )
    if inline_fits and not value_introduced_newlines:
        return

    # Step 2: try break-at-`=`. The value emits on the
    # continuation line; if IT fits within the budget there
    # we prefer this shape over Step 3.
    emitter.restore(saved)
    p2_saved = emitter.snapshot()
    _emit_node(emitter, source, type_node)
    emitter.write(" ")
    _emit_node(emitter, source, name_node)
    emitter.newline()
    emitter.write(" " * (start_col + 4))
    emitter.write("= ")
    _emit_node(emitter, source, value_node)
    value_introduced_newlines_p2 = (
        emitter.line_count > p2_saved[0] + 1
    )
    p2_fits = (
        emitter.last_lines_max_width(p2_saved[0]) <= effective_max
        and emitter.column < effective_max
    )
    if p2_fits and not value_introduced_newlines_p2:
        return

    # Step 3: fall back. Prefer inline-with-value-wrap when it
    # actually fits within the budget; otherwise keep the
    # break-at-`=` form already emitted (which at least bounds
    # the LHS to its own line).
    #
    # `saved` is the pre-Step-1 snapshot. Step 2 already called
    # `restore(saved)` once to start its attempt cleanly, so
    # restoring `saved` here from the post-Step-2 buffer state
    # rewinds to the same pre-Step-1 starting point — exactly
    # what the inline form needs.
    if inline_fits:
        emitter.restore(saved)
        _emit_node(emitter, source, type_node)
        emitter.write(" ")
        _emit_node(emitter, source, name_node)
        emitter.write(" = ")
        _emit_node(emitter, source, value_node)
        return
    # Break-at-`=` with value-wrap is already in the buffer
    # from the Step 2 attempt — leave it committed.


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

    0.6.0 defect-5 fix (Option A): when the body is a block
    and the arrow lands on a line whose leading col DIFFERS
    from the caller's `_indent * 4` (typically because the
    arrow sits on a chain-continuation or paren-aligned
    continuation), align the block body's indent to
    `arrow_line_leading + 4` (rounded up to the 4-space grid)
    rather than the caller's block indent. Also aligns the
    closing `}` to the arrow line's leading col so it visually
    reconnects with the segment that opened the block. Keeps
    body statements visually contained inside the enclosing
    chain segment (site: `EntityDelta.java:1133, 2102`) rather
    than orphaning them at outer-statement indent.

    For non-chain lambdas (arrow-line-leading == caller's
    `_indent * 4`), the target indent equals the current
    `_indent + 1`, so `_emit_block` runs unchanged.
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
    if body.type == "block" and _lambda_uses_chain_cascade_indent(
        emitter
    ):
        _emit_lambda_block_body(emitter, source, body)
    elif body.type == "block":
        _emit_node(emitter, source, body)
    else:
        _emit_node(emitter, source, body)


def _lambda_uses_chain_cascade_indent(emitter: Emitter) -> bool:
    """Return True when the current emit position sits on a
    chain-continuation line (`.<method>(<params> -> `), so
    defect-5's Option A body-indent rule should fire.

    Detection: leftmost non-space char on the current
    in-progress line is `.`. That's the sig for a chain-
    cascade segment where the arrow lives on its OWN line
    at a chain-continuation col rather than being packed on
    the caller's line. Packed-arrow cases (single-line chain
    with an inline `.execute(() -> {` fragment) return False
    so the standard `_emit_block` path emits body statements
    at the outer statement's block indent — matching the
    pre-0.6 behavior and preserving idempotency of the
    surrounding paren-aligned / source-preserved layout.
    """
    current = emitter._current
    stripped = current.lstrip(" ")
    if not stripped:
        return False
    return stripped[0] == "."


def _emit_lambda_block_body(
    emitter: Emitter, source: bytes, body: Node
) -> None:
    """Emit a lambda's block body per defect-5 Option A —
    body-statement indent = arrow-line-leading + 4, closing
    `}` at arrow-line-leading.

    The arrow-line-leading col is captured BEFORE writing the
    opening `{` (so the emitter's in-progress line still
    reflects the caller's chain-cascade or paren-align
    context). Body statements land at
    `ceil(arrow_line_leading / 4) * 4 + 4` (nearest 4-space-
    grid boundary at or above the arrow, plus one indent
    level). The closing `}` writes at
    `ceil(arrow_line_leading / 4) * 4`, so it aligns with the
    line that opened the block rather than the outer
    statement's indent.

    When the arrow-leading col already matches the caller's
    block indent (`_indent * 4`), the target simplifies to
    `(_indent + 1) * 4` — identical to `_emit_block`'s
    behavior — and this helper produces the same output as
    the pre-0.6 code path.
    """
    arrow_leading = _current_line_leading_spaces(emitter)
    # Round arrow_leading UP to the 4-space grid so
    # body-indent-and-close-brace-indent both land on a
    # multiple of 4 (matches the formatter's canonical
    # indent grid used everywhere else).
    close_indent_units = (arrow_leading + 3) // 4
    body_indent_units = close_indent_units + 1
    close_indent = 4 * close_indent_units
    body_indent = 4 * body_indent_units
    statements = list(body.named_children)
    brace_row = body.start_point[0]
    emitter.write("{")
    # Consume any leading side-comment on the brace line —
    # same rule as `_emit_block`.
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
    remaining = statements[consumed:]
    # Preserve one leading blank line if source has one —
    # same rule as `_emit_block`.
    if remaining and remaining[0].start_point[0] - brace_row > 1:
        emitter.newline()
    # Set `_indent` for the duration of statement emission so
    # any nested emissions that read `_indent` (block-relative
    # continuations, further nested `_emit_block` bodies) see
    # the body-indent level as their outer block. Restored
    # before the closing `}`.
    outer_indent = emitter._indent
    emitter._indent = body_indent_units
    prev_stmt: Node | None = None
    index = 0
    while index < len(remaining):
        stmt = remaining[index]
        if prev_stmt is not None:
            if stmt.start_point[0] - prev_stmt.end_point[0] > 1:
                emitter.newline()
        emitter.write(" " * body_indent)
        _emit_node(emitter, source, stmt)
        index, stmt = _attach_trailing_side_comments(
            emitter, source, remaining, index, stmt
        )
        emitter.newline()
        prev_stmt = stmt
        index += 1
    emitter._indent = outer_indent
    emitter.write(" " * close_indent)
    emitter.write("}")


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
    types = _require_type_list(node, "extends_interfaces")
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
    types = _require_type_list(node, "super_interfaces")
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
    if name is None:
        raise NotImplementedError(
            "enum_declaration missing 'name' field — grammar "
            "shape unexpected."
        )

    # Capture the enum declaration's start column so the
    # implements-wrap continuation indent lands at
    # `start_col + 4` — mirrors `_emit_class_declaration`.
    start_col = emitter.column

    if modifiers_node is not None:
        _emit_node(emitter, source, modifiers_node)
    emitter.write("enum ")
    _emit_node(emitter, source, name)

    # Try-emit the single-line enum header. If the
    # `implements ...` clause pushes past 80 chars,
    # backtrack and wrap. Enums have no `type_parameters`
    # or `extends` (both refused above), so this only
    # feeds `super_interfaces_node` to the shared wrap
    # helper. Long-typed enum headers typically land on
    # the P2 shape (`implements X, Y` on a single
    # continuation line at `start_col + 4`); single
    # interfaces wider than the continuation budget
    # commit at P3-terminal per spec C1 emit-and-warn.
    saved = emitter.snapshot()
    if super_interfaces_node is not None:
        emitter.write(" ")
        _emit_node(emitter, source, super_interfaces_node)
    if emitter.last_lines_max_width(saved[0]) > _MAX_LINE:
        # When `super_interfaces_node is None`, nothing was
        # emitted since the snapshot, so this check cannot
        # trip — matching the unconditional style used in
        # the sibling `_emit_class_declaration`.
        emitter.restore(saved)
        _emit_class_header_wrapped(
            emitter,
            source,
            None,
            None,
            super_interfaces_node,
            WrapContext.at(start_col),
        )
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
    exposes such Javadoc comments as `block_comment` siblings
    of `enum_constant` in the enum_body. Collect leading
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

    # Capture the interface declaration's start column for the
    # type-parameter-wrap continuation indent (single-indent past
    # the interface start = start_col + 4). Mirrors the same
    # bookkeeping in `_emit_class_declaration`.
    start_col = emitter.column

    if modifiers_node is not None:
        _emit_node(emitter, source, modifiers_node)
    emitter.write("interface ")
    if name is not None:
        _emit_node(emitter, source, name)

    # Try-emit the single-line interface header. If the result
    # overflows 80 chars (long generic bounds, long extends
    # clause, etc.), backtrack and emit with type-parameter wrap.
    # Without this check, an over-80 header silently lands in the
    # output and the consumer's checkstyle gate fails on LineLength.
    saved = emitter.snapshot()
    if type_parameters_node is not None:
        _emit_node(emitter, source, type_parameters_node)
    if extends_interfaces_node is not None:
        emitter.write(" ")
        _emit_node(emitter, source, extends_interfaces_node)
    if emitter.last_lines_max_width(saved[0]) > _MAX_LINE:
        emitter.restore(saved)
        # Reuse the class-header wrap helper; interfaces have no
        # `superclass` so pass `None` there. `extends_interfaces`
        # plays the same trailing-clause role as `super_interfaces`
        # — both are dispatched through `_emit_node`, which writes
        # the correct keyword (`implements` vs `extends`) per the
        # node type.
        _emit_class_header_wrapped(
            emitter,
            source,
            type_parameters_node,
            None,
            extends_interfaces_node,
            WrapContext.at(start_col),
        )

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
    index = 0
    while index < len(members):
        member = members[index]
        if prev is not None:
            if member.start_point[0] - prev.end_point[0] > 1:
                emitter.newline()
        emitter.write_indent()
        _emit_node(emitter, source, member)
        # 0.7.0: same-row side-comment attachment (see
        # `_emit_class_body_members` for rationale).
        index, member = _attach_trailing_side_comments(
            emitter, source, members, index, member
        )
        emitter.newline()
        prev = member
        index += 1
    emitter.pop_indent()


def _emit_annotation_type_declaration(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `@interface NAME { ... }` (Java annotation type
    declaration) with Allman brace placement.

    Same shape as `interface` declarations, except the keyword
    is `@interface`. Annotation types cannot have type
    parameters or `extends` / `permits` clauses — their bodies
    consist of `annotation_type_element_declaration` members
    (each defining one annotation attribute) and the usual
    nested-type / constant declarations.
    """
    modifiers_node: Node | None = None
    for child in node.named_children:
        if child.type == "modifiers":
            modifiers_node = child
            break

    name = node.child_by_field_name("name")
    body = node.child_by_field_name("body")

    if modifiers_node is not None:
        _emit_node(emitter, source, modifiers_node)
    emitter.write("@interface ")
    if name is not None:
        _emit_node(emitter, source, name)
    emitter.newline()
    emitter.write_indent()
    emitter.write("{")
    emitter.newline()
    if body is not None:
        _emit_interface_body_members(emitter, source, body)
    emitter.write_indent()
    emitter.write("}")


def _emit_annotation_type_element_declaration(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `[modifiers] TYPE NAME() [default VALUE];` — an
    annotation type's element (attribute).

    Annotation elements look like method declarations but
    they're never given parameters or bodies, and they may
    carry a `default` clause specifying the value used when
    the attribute is omitted at the use site.

    Grammar fields: optional `modifiers`, required `type`,
    required `name`. The optional `default value` shows up as
    an anonymous `default` keyword child followed by a value
    expression carrying the field name `value`.
    """
    modifiers_node: Node | None = None
    for child in node.named_children:
        if child.type == "modifiers":
            modifiers_node = child
            break

    type_node = node.child_by_field_name("type")
    name_node = node.child_by_field_name("name")
    default_value = node.child_by_field_name("value")
    if type_node is None or name_node is None:
        raise NotImplementedError(
            "annotation_type_element_declaration missing 'type' "
            "or 'name' — grammar shape unexpected."
        )

    if modifiers_node is not None:
        _emit_node(emitter, source, modifiers_node)
    _emit_node(emitter, source, type_node)
    emitter.write(" ")
    _emit_node(emitter, source, name_node)
    emitter.write("()")
    if default_value is not None:
        emitter.write(" default ")
        _emit_node(emitter, source, default_value)
    emitter.write(";")


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
    _emit_indented_member_list(
        emitter, source, list(body.named_children)
    )
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
    _emit_indented_member_list(
        emitter, source, list(block.named_children)
    )
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

    # P1: try comma-space single-line. Speculative emission
    # measures the actual rendered widths (avoids the
    # source-text-width pitfall when the throws clause carries
    # types with weird internal whitespace in source). If P1
    # overflows we backtrack and emit P2 — one type per line,
    # continuation-aligned with the first type's column.
    saved = emitter.snapshot()
    emitter.write("throws ")
    cont_col = emitter.column
    for index, t in enumerate(types):
        if index > 0:
            emitter.write(", ")
        _emit_node(emitter, source, t)
    effective_max = _MAX_LINE - emitter.tail_reserve
    if emitter.last_lines_max_width(saved[0]) <= effective_max:
        return

    # P2: one type per line, continuation aligned at the
    # column immediately after `throws `.
    emitter.restore(saved)
    emitter.write("throws ")
    for index, t in enumerate(types):
        if index > 0:
            emitter.newline()
            emitter.write(" " * cont_col)
        _emit_node(emitter, source, t)
        if index < len(types) - 1:
            emitter.write(",")


def _emit_formal_parameter_prefix(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit a formal parameter's `[MODIFIERS] TYPE`, stopping before
    the name. Shared by the aligned and width-measuring paths so the
    two cannot disagree about what the prefix contains.
    """
    for child in node.named_children:
        if child.type == "modifiers":
            for c in child.children:
                if c.is_named:
                    _emit_node(emitter, source, c)
                else:
                    emitter.write(c.type)
                emitter.write(" ")
            break
    _emit_node(emitter, source, node.child_by_field_name("type"))


def _formal_param_name_col_offset(
    emitter: Emitter, source: bytes, params: list[Node]
) -> int | None:
    """Offset from the type column to the name column for a
    multi-line parameter list, or None when the list cannot be
    column-aligned.

    Spec "Parameters aligned to opening parenthesis": types are
    left-aligned, and names start at the first 4-space tab stop
    **strictly past** the longest type prefix. Verified against both
    spec examples — a longest type of 14 puts names at 16, and one of
    32 puts them at 36.

    Returns None (meaning "emit unaligned") when any parameter is not
    a plain `formal_parameter` with both a type and a name, or when a
    prefix's own emission wraps. Varargs and receiver parameters take
    that path: their prefix is not a bare type, so a single measured
    width would not describe them. Padding a list the measurement
    does not fully model is worse than leaving it unaligned.
    """
    # Alignment forms a column, and one parameter has nothing to form
    # it with — padding a lone name just pushes it right for no
    # reason, and on a next-line P3 emit it reads as a mistake:
    #
    #     private static Map<Long, SzRelatedEntity> getRelatedEntities(
    #             SzResolvedEntity    entity)   <- gutter to nowhere
    if len(params) < 2:
        return None
    widths: list[int] = []
    for p in params:
        if p.type != "formal_parameter":
            return None
        if (
            p.child_by_field_name("type") is None
            or p.child_by_field_name("name") is None
        ):
            return None
        saved = emitter.snapshot()
        start_line, start_col = saved[0], emitter.column
        _emit_formal_parameter_prefix(emitter, source, p)
        wrapped = emitter.line_count != start_line
        width = emitter.column - start_col
        emitter.restore(saved)
        if wrapped or width <= 0:
            return None
        widths.append(width)
    if not widths:
        return None
    return ((max(widths) // 4) + 1) * 4


def _emit_formal_parameter_aligned(
    emitter: Emitter, source: bytes, node: Node, name_col: int
) -> None:
    """Emit one parameter with its name padded out to `name_col`.

    Falls back to a single space when the prefix already reaches or
    passes `name_col` — that only happens if the caller measured a
    different set of parameters than it is emitting, but a parameter
    running into its own name would be worse than a lost column.
    """
    _emit_formal_parameter_prefix(emitter, source, node)
    pad = name_col - emitter.column
    emitter.write(" " * pad if pad > 0 else " ")
    _emit_node(emitter, source, node.child_by_field_name("name"))


def _emit_formal_parameters(
    emitter: Emitter, source: bytes, node: Node,
    force_wrap: bool = False,
    p3_indent_col: int | None = None,
) -> None:
    """Emit `(p1, p2, ...)`.

    Default behavior: source-preservation. When the source has
    the parameter list spanning multiple rows, the developer-
    authored multi-line layout is preserved verbatim; otherwise
    a single-line emit.

    `force_wrap=True` (used by `_emit_method_header_wrapped`)
    overrides source-preservation and engages the spec's
    parameter-wrap priority order (P1 single-line → P2 paren-
    aligned with the first parameter → P3 next-line one-per-
    line at `p3_indent_col`). Each priority is tried by
    speculative emit; on overflow the buffer is restored and
    the next priority emitted.

    `p3_indent_col` (required when `force_wrap=True` AND the
    parameter list is long enough that P2 paren-alignment would
    itself overflow): the absolute column at which P3 places
    each parameter line. Convention is `start_col + 8` — double-
    indent from the method declaration's first non-modifier
    column — matching the spec's "Method and Constructor
    Declarations / Parameter Placement / P3" example.

    Varargs (`Type... name`) are supported via
    `_emit_spread_parameter`; they are excluded from name
    alignment because their prefix is not a bare type.

    Receiver parameters (`Foo this`) are NOT supported and,
    worse, are silently DROPPED: the `params` filter below keeps
    only `formal_parameter` and `spread_parameter`, and no
    emitter is registered for `receiver_parameter`. A method
    declaring one would lose it from the output. Pre-existing
    and not yet fixed; recorded here so the next reader finds it
    rather than trusting the filter.
    """
    if not force_wrap and _node_spans_multiple_rows(node):
        # Preserve developer-authored multi-line params from
        # source. Includes opening `(` and closing `)`.
        emitter.write_raw_lines(
            _node_source_text(source, node), strip_trailing_ws=True
        )
        return
    params = [
        c for c in node.children
        if c.type in (
            "formal_parameter", "spread_parameter",
            "receiver_parameter",
        )
    ]
    if not force_wrap:
        # Default single-line emit (caller's responsibility to
        # have checked for overflow upstream).
        emitter.write("(")
        for index, param in enumerate(params):
            if index > 0:
                emitter.write(", ")
            _emit_node(emitter, source, param)
        emitter.write(")")
        return
    # P1/P2 fit checks honor `tail_reserve` so callers that
    # know about trailing tokens beyond `)` (e.g. the abstract-
    # method `;` reserve set by `_emit_method_declaration`) can
    # force the priority engine past a borderline P1.
    effective_max = _MAX_LINE - emitter.tail_reserve
    # P1: try single-line.
    saved = emitter.snapshot()
    emitter.write("(")
    paren_col = emitter.column
    for index, param in enumerate(params):
        if index > 0:
            emitter.write(", ")
        _emit_node(emitter, source, param)
    emitter.write(")")
    if emitter.last_lines_max_width(saved[0]) <= effective_max:
        return
    # P2: paren-aligned, one per line at paren_col, with names
    # column-aligned at the first 4-space tab stop past the longest
    # type. `None` means this list cannot be aligned (varargs,
    # receiver params) and each parameter falls back to a single
    # space, which is what every wrapped list looked like before.
    emitter.restore(saved)
    saved2 = emitter.snapshot()
    name_col_offset = _formal_param_name_col_offset(
        emitter, source, params
    )
    cont_p2 = " " * paren_col

    def emit_p2(name_col: int | None) -> None:
        emitter.write("(")
        for index, param in enumerate(params):
            if index > 0:
                emitter.write(",")
                emitter.newline()
                emitter.write(cont_p2)
            if name_col is None:
                _emit_node(emitter, source, param)
            else:
                _emit_formal_parameter_aligned(
                    emitter, source, param, name_col
                )
        emitter.write(")")

    p2_name_col = (
        None if name_col_offset is None else paren_col + name_col_offset
    )
    emit_p2(p2_name_col)
    if emitter.last_lines_max_width(saved2[0]) <= effective_max:
        return
    # P3: next-line, one per line at p3_indent_col. Falls back
    # to paren_col when no p3_indent_col was supplied (the
    # caller is presumably comfortable with the resulting layout
    # — the formatter still emits the wrap so any remaining
    # overflow surfaces as a checkstyle LineLength rather than
    # silent under-formatting).
    p3_col = p3_indent_col if p3_indent_col is not None else paren_col
    if p3_col >= paren_col:
        # Priority 3 exists to escape a paren column pushed far right by
        # a long return type and method name. When the paren column is
        # already at or left of `start_col + 8`, breaking after the `(`
        # moves every parameter FURTHER right and cannot help — so
        # priority 2 is the narrowest shape available and becomes the
        # terminal candidate:
        #
        #     void m(SomeExtremelyLongQualifiedTypeName a,      <- P2, 11
        #            int aParameterWithAnExtremelyLongName)
        #
        #     void m(                                           <- P3, 12
        #             SomeExtremelyLongQualifiedTypeName a,
        #             int aParameterWithAnExtremelyLongName)
        #
        # Commit priority 2, dropping the name alignment first if that
        # is what costs the width, and warn if it still does not fit.
        aligned_width = emitter.last_lines_max_width(saved2[0])
        if p2_name_col is not None:
            emitter.restore(saved2)
            emit_p2(None)
            if emitter.last_lines_max_width(saved2[0]) >= aligned_width:
                emitter.restore(saved2)
                emit_p2(p2_name_col)
        _fire_wrap_overflow_advisory(
            emitter, node, saved2[0], "parameter list",
            remedy=(
                "Breaking after the opening parenthesis would indent "
                "the parameters further right than they already are, "
                "so there is no narrower shape. Shorten a type or "
                "parameter name."
            ),
        )
        return
    emitter.restore(saved2)
    cont_p3 = " " * p3_col

    def emit_p3(name_col: int | None) -> None:
        emitter.write("(")
        for index, param in enumerate(params):
            emitter.newline()
            emitter.write(cont_p3)
            if name_col is None:
                _emit_node(emitter, source, param)
            else:
                _emit_formal_parameter_aligned(
                    emitter, source, param, name_col
                )
            if index < len(params) - 1:
                emitter.write(",")
        emitter.write(")")

    # P3 is the terminal candidate, so this is the spec C1 emit-and-warn
    # exit for a parameter list. It had no advisory at all: a parameter
    # wider than the whole budget was written out at any width in total
    # silence, so a developer chasing a checkstyle LineLength failure
    # got no output from the formatter and nothing to act on.
    def emit_p3_and_warn(name_col: int | None) -> None:
        before = emitter.line_count
        emit_p3(name_col)
        _fire_wrap_overflow_advisory(
            emitter, node, before, "parameter list",
            remedy=(
                "Every parameter is already on its own line at the "
                "deepest available indent. Shorten a type or "
                "parameter name."
            ),
        )

    if name_col_offset is None:
        emit_p3_and_warn(None)
        return
    # Alignment must not be what pushes a line over the limit. P3 is
    # the terminal candidate — there is no further tier to catch an
    # overflow here — so an aligned emit that does not fit yields to
    # the unaligned one rather than committing a line no reformat will
    # ever repair. The pathological shape is a SHORT type paired with a
    # long one, because the short type's name is padded out to the long
    # type's column while still carrying its own full length:
    #
    #     void m(
    #             SomeExtremelyLongQualifiedTypeName  a,
    #             int                                 aParameterWithALongName)
    #                                                 ^ 82 cols aligned,
    #                                                   50 unaligned
    #
    # The two candidates are COMPARED rather than the aligned one being
    # tested against the cap on its own. `last_lines_max_width` starts
    # at the row that was already open when the parameters began — the
    # signature row — and that row is frequently the widest thing in
    # the emit and has nothing to do with alignment. Measuring the
    # aligned form alone therefore stripped alignment from parameter
    # lists whose own rows were nowhere near the limit, purely because
    # the method name above them reached column 80. Both measurements
    # span the same rows, so the shared one cancels out, and alignment
    # is given up only when doing so actually buys width back.
    #
    # The comparison runs on plain `emit_p3` so a rolled-back candidate
    # cannot leave an advisory behind; only the shape that survives is
    # re-emitted through `emit_p3_and_warn`.
    p3_snap = emitter.snapshot()
    emit_p3(p3_col + name_col_offset)
    aligned_width = emitter.last_lines_max_width(p3_snap[0])
    if aligned_width <= effective_max:
        emitter.restore(p3_snap)
        emit_p3_and_warn(p3_col + name_col_offset)
        return
    emitter.restore(p3_snap)
    emit_p3(None)
    if emitter.last_lines_max_width(p3_snap[0]) >= aligned_width:
        # Unaligned is no narrower — the overflow is inherent to the
        # parameters, not to the padding. Keep the aligned form, which
        # is the shape the spec asks for.
        emitter.restore(p3_snap)
        emit_p3_and_warn(p3_col + name_col_offset)
        return
    emitter.restore(p3_snap)
    emit_p3_and_warn(None)


def _emit_receiver_parameter(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `[ANNOTATIONS] TYPE [Outer.] this` verbatim.

    A receiver parameter exists only to give annotations somewhere to
    attach; it declares no name and must come first. Emitting the
    source text unchanged preserves any annotations exactly and keeps
    the construct out of the name-alignment machinery, which has
    nothing to align here — `_formal_param_name_col_offset` already
    declines a list containing one, because its prefix is not a bare
    type and a single measured width would not describe it.

    Before this existed the parameter was simply DROPPED: the
    parameter-list filter kept only `formal_parameter` and
    `spread_parameter`, so `void m(T this, String s)` emitted as
    `void m(String s)`. Dropping a bare `T this` is semantically
    inert, but dropping an annotated one discards the annotation,
    which is not.
    """
    emitter.write(_node_source_text(source, node))


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


_COMPUTED_RECEIVER_TYPES: Final[frozenset[str]] = frozenset({
    "method_invocation",
    "array_access",
    "object_creation_expression",
    "parenthesized_expression",
    "cast_expression",
})
"""Receiver forms whose value is computed rather than named.

Only these may be split from a trailing `.field`. Everything else a
`field_access` can carry — a bare identifier, or a nested
`field_access` over identifiers — is part of a qualified name or a
constant reference, where the dots belong to the name.
"""


def _field_access_receiver_is_computed(node: Node) -> bool:
    """True when `node` is a computed value rather than a name."""
    if node.type in _COMPUTED_RECEIVER_TYPES:
        return True
    if node.type == "field_access":
        inner = node.child_by_field_name("object")
        return inner is not None and _field_access_receiver_is_computed(
            inner
        )
    return False


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
    # Propagate tail_reserve to the object emit so any nested
    # wrap engine inside the receiver accounts for the
    # trailing `.field` (and whatever surrounds us above).
    # Uses source-text width for the field — for identifiers
    # the source matches the rendered width exactly.
    field_text = _node_source_text(source, field_node)

    def emit_inline() -> None:
        prev = emitter.set_tail_reserve(
            emitter.tail_reserve + 1 + len(field_text)
        )
        try:
            _emit_node(emitter, source, object_node)
        finally:
            emitter.set_tail_reserve(prev)
        emitter.write(".")
        _emit_node(emitter, source, field_node)

    saved = emitter.snapshot()
    line_start_col = _current_line_leading_spaces(emitter)
    effective_max = _MAX_LINE - emitter.tail_reserve
    emit_inline()
    inline_width = emitter.last_lines_max_width(saved[0])
    if inline_width <= effective_max:
        return
    # Only a COMPUTED receiver may be broken away from its field. The
    # `field_access` node also spells qualified names and constant
    # references, where the dots are part of one name and breaking them
    # is meaningless:
    #
    #     java                      Boolean
    #         .util                     .FALSE.equals(...)
    #         .Objects.requireNonNull(...)
    #
    # A receiver that is itself an identifier, or a field access over
    # identifiers, is such a name. A call, an array index, a cast or a
    # parenthesized expression is a value that was computed, and there
    # the dot is a real operator.
    if not _field_access_receiver_is_computed(object_node):
        return

    # The inline form does not fit. Break before the `.`, which the
    # spec's "Operators on continuation lines" rule already names as a
    # break-before operator, and put the field at single indentation
    # from the start of this line.
    #
    # `field_access` previously had no wrap tier at all. The receiver
    # emitted under a correct reserve, exhausted its own cascade, and
    # committed its terminal candidate — after which the field was
    # appended to a row that was already full:
    #
    #     int n = methodBeingCalled(
    #             argumentOne,
    #             argumentTwo).someFieldNameHere;    <- 85 cols
    #
    # even though breaking the dot fits comfortably. The receiver is
    # re-emitted at the ORIGINAL reserve, since the field no longer
    # shares its last row.
    emitter.restore(saved)
    _emit_node(emitter, source, object_node)
    emitter.newline()
    push_count, extra = _push_indent_to_col(emitter, line_start_col + 4)
    _emit_p4_write_target_indent(emitter, push_count, extra)
    emitter.write(".")
    _emit_node(emitter, source, field_node)
    for _ in range(push_count):
        emitter.pop_indent()
    if emitter.last_lines_max_width(saved[0]) >= inline_width:
        # Breaking the dot bought nothing — the receiver overflows on
        # its own, and moving the field off its last row cannot help.
        # Prefer the inline form, which costs one line fewer.
        emitter.restore(saved)
        emit_inline()


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


def _push_indent_to_col(
    emitter: "Emitter", target_col: int
) -> tuple[int, int]:
    """Bump `emitter._indent` toward `target_col` and return
    `(push_count, extra_spaces)`.

    `push_count`: number of `push_indent()` calls made. The
    caller MUST match with `pop_indent()` calls to restore
    the emitter's indent state.
    `extra_spaces`: spaces to write in addition to
    `write_indent()` to reach `target_col` exactly. Non-zero
    only when `target_col` isn't aligned to the 4-space grid
    (e.g. paren-aligned to a chain-tail `.` col that isn't
    a multiple of 4).

    Rationale (0.6.0): arg-list P4 candidates want a
    continuation anchor derived from `current_line_start_col
    + 4`, not `block + 4`. But inner emissions (a binary
    arg's `+`-continuation, a lambda body's block indent)
    read `_indent` to compute THEIR own indent. Direct
    space-writing at `target_col` without touching `_indent`
    leaves those inner emissions computing off the outer
    block indent, producing shallow orphans.

    This helper bumps `_indent` by `(target_col - 4 *
    current_indent) // 4` (floored), then reports `extra`
    for the caller to write directly. For target cols that
    are multiples of 4 (the common case — statement-top-
    level, paren-aligned to statement-level parens), `extra
    == 0`. For irregular cases, `extra` is 1-3 spaces and
    inner `_indent`-based continuations will be off by up
    to `extra` cols — an accepted trade-off.

    Edge case: when `target_col <= 4 * emitter._indent` (the
    target is at or shallower than the current block indent),
    this helper returns `(0, 0)` and the caller's subsequent
    `write_indent()` emits at the CURRENT (deeper) indent,
    not the requested `target_col`. That's a deliberate
    fall-through — the callers today (arg-list P4 candidates
    computing `line_start_col + 4`) always pass a `target_col`
    at or past the current indent because `line_start_col` is
    itself derived from the current line's leading spaces
    which are typically at or past the block indent. A future
    caller with a genuinely-shallower target would need to
    `pop_indent()` on its own before calling.
    """
    current_indent_col = 4 * emitter._indent
    delta = target_col - current_indent_col
    if delta <= 0:
        return (0, max(0, delta))
    push_count = delta // 4
    extra = delta % 4
    for _ in range(push_count):
        emitter.push_indent()
    return (push_count, extra)


def _emit_p4_write_target_indent(
    emitter: "Emitter", push_count: int, extra: int
) -> None:
    """Write the leading indent for an arg-list P4 continuation
    line. `push_count` and `extra` come from
    `_push_indent_to_col`. Emits `4 * _indent` spaces via
    `write_indent()`, then `extra` additional spaces to reach
    the exact target col.
    """
    emitter.write_indent()
    if extra:
        emitter.write(" " * extra)


def _current_line_leading_spaces(emitter: "Emitter") -> int:
    """Return the count of leading space characters in the
    emitter's current in-progress line (`_current`).

    Used by `_emit_argument_list`'s P4 candidates
    (`emit_p4_multi_arg`, `emit_p4_single_arg_block_indent`)
    to compute their continuation anchor: `line_start_col + 4`
    where `line_start_col` is the 0-based column of the first
    non-space character on the current in-progress line.

    Rationale (0.6.0): the pre-0.6 `push_indent + write_indent`
    approach uses `_indent`-based tracking (in 4-space
    units) relative to the enclosing block. That produces
    the correct col for statement-top-level P4 emissions
    but orphans nested emissions to shallow cols. Consumer
    trial 2026-07-09 surfaced this as defect 3. The
    line-start-col + 4 rule keeps nested emissions
    visually contained inside their enclosing context.

    The binary wrap engine's `paren_inner_wrap` check
    (which relied on the OLD anchor producing shallow
    lines to reject paren-align in favor of compact
    +4-greedy) is now backed by
    `Emitter._arg_list_p4_fired` — a direct signal that an
    operand's emission cascaded through arg-list P4 —
    rather than the indirect shallow-line heuristic.
    """
    current = emitter._current
    stripped = current.lstrip(" ")
    if not stripped:
        return len(current)
    return len(current) - len(stripped)


def _max_source_preserve_line_width(
    lines: list[str],
    prefix_col: int,
    tail_reserve: int,
) -> int:
    """Return the max on-disk width of a source-preserved
    block, matching the per-line accounting in
    `_fire_wrap_overflow_advisory`.

    - Line 0 is prefixed by `prefix_col` chars of emit-line
      context (whatever the emitter already wrote before the
      arg list) — mirrors `emitter.column + len(lines[0])`.
    - The LAST line receives `tail_reserve` chars for the
      parent's trailing tokens (`;`, `)`, etc.).
    - Intermediate lines render verbatim, no adjustment.
    - Single-line inputs treat that line as both first AND
      last, so `prefix_col + len(lines[0]) + tail_reserve`.

    Shared between the 0.5.2 F shift-up-overflow guard and
    the post-emit overflow advisory in `_emit_argument_list`
    so both use identical width math.
    """
    if not lines:
        return 0
    first_width = prefix_col + len(lines[0])
    if len(lines) == 1:
        return first_width + tail_reserve
    last_width = len(lines[-1]) + tail_reserve
    return max(
        first_width, last_width,
        *(len(ln) for ln in lines[1:-1]),
    )


def _arg_list_takes_source_preserve_path(
    emitter: Emitter, source: bytes, node: Node
) -> bool:
    """Return True when `_emit_argument_list` would emit `node`
    verbatim from source (`write_raw_lines`) instead of falling
    through to the wrap engine.

    Preservation fires when the arg list spans multiple source rows
    AND one of:

      - It contains interleaved `//` / `/* */` comments. The wrap
        engine has no concept of an inter-argument comment and would
        corrupt the output.
      - It sits inside a `// CSOFF` / `// CSON` region, where the
        spec's "Formatted Log and Diagnostic Messages" rule opts out
        of reflow explicitly.

    Both are CORRECTNESS reasons — things reflow would break. There
    is deliberately no third, width-based trigger; 0.7.0 removed the
    "the source's first line fits, so keep the author's layout"
    fallback and everything that existed to carve exceptions out of
    it. Consequently this predicate is now column-insensitive, and
    the `column` parameter its callers used to pass is gone.

    See the `building/source-preservation-history` FAQ before adding
    anything here.
    """
    # Interleaved comments preserve REGARDLESS of row span. The wrap
    # engine treats every named child as an argument, and tree-sitter
    # exposes a comment as a named child, so a comment inside an
    # argument list is counted as an argument and given a separator —
    # which emits Java that does not parse:
    #
    #     in   outer.call(inner(alphaValue, /* note */ betaValue), tag);
    #     out  outer.call(inner(alphaValue, /* note */, betaValue), tag);
    #
    # Preserving is the existing answer to "the wrap engine has no
    # concept of an inter-argument comment"; it was simply gated behind
    # the multi-row test below, so the single-row case fell through to
    # the engine and corrupted the source. No file in the 504-file
    # trial corpus contains such a list, which is why this survived.
    has_comment = any(
        c.type in ("line_comment", "block_comment")
        for c in node.children
        if c.is_named
    )
    if has_comment:
        return True

    if not _node_spans_multiple_rows(node):
        return False
    if _is_inside_csoff_region(source, node):
        return True

    # Nothing else preserves. Every other multi-row argument list
    # goes to the wrap engine, so layout is a function of the AST
    # alone.
    #
    # Releases through 0.6.0 ended this function with a fallback:
    # "the source spans rows and its first line fits at the emission
    # column, so keep the author's layout". That was deference, not
    # correctness — and on any file the formatter had already
    # touched, the layout it deferred to was whatever an EARLIER
    # VERSION of the formatter wrote, which made this gate a
    # propagation channel for its own past mistakes and made output
    # depend on how a file happened to be typed. Several further
    # rules (a single-line width opt-out, a semantic multi-row-arg
    # opt-out, nested-call and wrapped-argument declines) existed
    # only to carve exceptions out of that fallback; when it went,
    # they all reduced to the `return False` below and were removed
    # in 0.7.0 rather than left as branches that compute an answer
    # nobody can observe.
    #
    # Their intent, the subtleties worth keeping (including the
    # string-literal-safe width estimator and the rejected geometric
    # predicate), and the idempotency trap they all shared are
    # recorded in the `building/source-preservation-history` FAQ.
    # Read it before adding a rule here: preservation is for things
    # the wrap engine would CORRUPT, never for things it would
    # merely lay out differently than the author did.
    return False


def _is_block_body_lambda(arg_node: Node) -> bool:
    """Return True when `arg_node` is a `lambda_expression`
    whose body is a `block` (`(params) -> { … }`).

    Used by `_emit_argument_list`'s single-arg cascade (0.7.0
    item A) to detect the idiomatic Java lambda-arg pattern.
    Block-body lambdas own their own indent decisions inside
    the body; the arg-list's fit check for such a lambda-arg
    should look only at the CALL LINE and CLOSING LINE, not
    at body-statement widths (which the body's own wrap
    engine controls).

    Expression-body lambdas (`x -> x + 1`) emit single-line
    and don't need this special-case handling — they're
    covered by the standard P1 fit check.
    """
    if arg_node.type != "lambda_expression":
        return False
    body = arg_node.child_by_field_name("body")
    return body is not None and body.type == "block"


def _is_anonymous_class(node: Node) -> bool:
    """Return True for `new Foo() { … }` — an object creation
    carrying an anonymous class body.

    Structurally a call, but its body spans rows by nature rather
    than because anything wrapped, so it belongs with block-bodied
    lambdas and text blocks: the nested-call rules must not break
    before it, and the "argument that wraps gets its own line"
    rule must not count it. Spec C8 fixes the idiomatic shape —

        service.execute(new Runnable() {
            public void run()
            {
                y();
            }
        });

    — with the closing `}` at the statement indent followed by the
    call's own `);`. Breaking before the argument would push the
    whole body one level deeper for no benefit.
    """
    if node.type != "object_creation_expression":
        return False
    return any(c.type == "class_body" for c in node.named_children)


def _arg_owns_its_rows(arg: Node) -> bool:
    """True when `arg` spanning rows is inherent, not a wrap.

    Block-bodied lambdas, text blocks and anonymous classes occupy
    several rows by their nature; every other construct occupies
    several rows only because something wrapped it. That distinction
    is what the 0.7.0 "if an argument breaks, the argument list
    breaks" rule keys on.

    Deliberately tests only STRUCTURAL properties of the node —
    never `_node_spans_multiple_rows`, which reads the source
    layout. Using the source makes the answer depend on whether a
    previous pass already wrapped the argument: pass 1 sees a
    single-row source and rejects the packed shape, pass 2 sees the
    wrapped output, treats it as inherently multi-row, and packs it
    again. That oscillated
    `arguments(Rectangle.class, Set.of(...), ...)` between two
    shapes on alternate passes.
    """
    return (
        _is_block_body_lambda(arg)
        or arg.type == "text_block"
        or _is_anonymous_class(arg)
    )


def _is_nested_or_chained_call(arg_list: Node) -> bool:
    """Return True when `arg_list`'s owning call is embedded.

    "Embedded" means the `method_invocation` that owns this
    `argument_list` is either:

      1. a positional argument of ANOTHER call, or
      2. the receiver of a method chain — i.e. one or more
         `.segment()` calls follow it.

    0.7.0 nested-call wrap (rule 2): in both positions the
    P2 "two-line paren-aligned comma-packed" shape reads
    badly, because the reader has to track a half-packed
    argument list AND the enclosing construct at the same
    time:

        reportUpdates.add(builder(DATA_SOURCE_SUMMARY, ENTITY_COUNT,
                                  entityId).records(-1)
            .build());

    Skipping P2 in these positions sends the cascade to P3
    (one arg per line), which keeps the argument list a
    single readable column:

        reportUpdates.add(
            builder(DATA_SOURCE_SUMMARY,
                    ENTITY_COUNT,
                    entityId)
                .records(-1)
                .build());

    The rule is deliberately arity-independent — it fires
    whether the enclosing call has one argument or several,
    because the unreadable shape is the same either way.
    Rule 1 (forcing the enclosing call to break) applies only
    to the single-argument case; see `_emit_argument_list`.
    """
    call = arg_list.parent
    # `object_creation_expression` (`new Foo(a, b)`) counts as a
    # call here: it owns an `argument_list` and reads identically
    # at a call site, so a `new Foo(…)` sitting in an argument
    # list gets the same treatment as `foo(…)`. It can also be a
    # chain receiver — `new Foo(a).bar()` parses as a
    # `method_invocation` whose `object` field IS the
    # `object_creation_expression` — so the receiver-identity
    # branch below reaches constructors too, which is intended.
    if call is None or call.type not in (
        "method_invocation",
        "object_creation_expression",
    ):
        return False
    outer = call.parent
    if outer is None:
        return False
    if outer.type == "argument_list":
        return True
    if outer.type == "method_invocation":
        # A chain tail follows only when this call is the
        # RECEIVER of the enclosing invocation. When it is
        # instead the enclosing call's argument, the
        # `argument_list` branch above already caught it.
        receiver = outer.child_by_field_name("object")
        return receiver is not None and receiver.id == call.id
    return False


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

    Wrap selection is driven by `try_priorities` — each
    candidate thunk emits the complete `(args)` form (parens
    included); the engine commits the first one whose
    rendered output stays within `_MAX_LINE`, or falls back
    to the last candidate per spec C1 emit + warn.

    Current implementation: P1, P2-greedy, and P4 are wired
    as candidates. The multi-line source-preservation path
    (when the source already wraps to multiple rows) covers
    cases that would otherwise need P3 by emitting the
    developer-authored layout verbatim. P3-via-explicit-
    emission (paren-aligned one-per-line, generated rather
    than preserved) lands when a fixture surfaces it.
    """
    args = [c for c in node.children if c.is_named]
    if not args:
        emitter.write("()")
        return

    # Source-preservation for already-wrapped argument lists.
    # When the source spans multiple rows, preserve the
    # developer-authored layout verbatim if EITHER:
    #
    #   (1) the first source line still fits at the current
    #       emission column (the common case — broken-for-
    #       readability messages keep their author-chosen
    #       break points), OR
    #   (2) the surrounding code is wrapped in a `// CSOFF` /
    #       `// CSON` region — the spec's "Formatted Log and
    #       Diagnostic Messages" rule explicitly opts out of
    #       reflow inside these markers to preserve aligned
    #       multi-line output.
    #
    # When neither condition holds (e.g. JDT's 2-space indent
    # source emitted into AST's 4-space context pushes the
    # first line past 80 chars and there's no CSOFF marker),
    # fall through to the wrap engine, which picks fresh
    # break points appropriate to the new column.
    if _arg_list_takes_source_preserve_path(emitter, source, node):
        src_text = _node_source_text(source, node)
        # 0.5.0 item 4 — context-aware source-preservation
        # with no-fallback policy.
        #
        # Column rule:
        #   - With governing paren (innermost
        #     `parenthesized_expression` ancestor — captured by
        #     `emitter.paren_align_col`): target =
        #     `paren_align_col + 4`. The `+4` separates the
        #     continuation from the outer paren's direct
        #     contents (which themselves start at
        #     `paren_align_col`).
        #   - Without governing paren: target = `block + 4`
        #     (canonical "one indent past the owning
        #     statement" continuation).
        #
        # No-fallback policy: emit at target unconditionally.
        # Fire an advisory. If the resulting line exceeds 80,
        # let it overflow — checkstyle's LineLength check
        # surfaces the overflow and the developer manually
        # splits the literal. Breaking the propagation cycle
        # where source-preserved verbatim layouts silently
        # re-appeared each format pass.
        #
        # CSOFF / has_comment cases are handled by the
        # predicate above — they emit verbatim without
        # column-remap (semantic columns are part of their
        # meaning).
        comments_present = any(
            c.type in ("line_comment", "block_comment")
            for c in node.children
            if c.is_named
        )
        if comments_present or _is_inside_csoff_region(
            source, node
        ):
            emitter.write_raw_lines(
                src_text, strip_trailing_ws=True
            )
            return
        if emitter.paren_align_col is not None:
            target_col = emitter.paren_align_col + 4
        else:
            target_col = emitter.indent_level * 4 + 4
        lines = src_text.split("\n")

        def _shift(rows: list[str], delta: int) -> list[str]:
            """Shift every continuation row by `delta` columns.

            The first row is untouched — it continues the current
            in-progress line, whose column the caller already set.
            Internal alignment (paren-aligned operators, dot-aligned
            chains inside the preserved block) survives because every
            row moves by the same amount.
            """
            out: list[str] = [rows[0]]
            for row in rows[1:]:
                stripped = row.lstrip()
                if not stripped:
                    out.append("")
                    continue
                leading = len(row) - len(stripped)
                out.append(" " * max(0, leading + delta) + stripped)
            return out

        # Find the source's first non-empty continuation col.
        source_first_cont_col = None
        for line in lines[1:]:
            if line.lstrip():
                source_first_cont_col = len(line) - len(
                    line.lstrip()
                )
                break
        if source_first_cont_col is None:
            # No continuation lines to shift.
            final_lines = lines
        else:
            # Shift every continuation line by one delta so internal
            # alignment (paren-aligned operators, dot-aligned chains
            # inside the preserved block) survives the move.
            #
            # The delta is the larger of two candidates:
            #
            #  - RE-ANCHOR: the construct's own displacement,
            #    `emit column - source column`. The author's
            #    continuation column was chosen relative to where the
            #    construct sat in the source, so preserving that
            #    relationship is what keeps a deliberately-deeper
            #    indent meaningful. Preserving the ABSOLUTE column
            #    instead leaves it aligned with nothing once the
            #    statement is re-indented:
            #
            #        // source: statement col 20, paren-align 33
            #        // emitted at col 16 -> paren-align is now 29,
            #        // but the continuation kept its absolute 33
            #        assertEquals(customersConfig, configJson,
            #                         "Unexpected definition.");
            #
            #  - TO-TARGET: whatever lands the first continuation on
            #    the canonical target column.
            #
            # Taking the max makes TO-TARGET a floor: a deeper author
            # indent is respected and merely re-anchored, but a large
            # negative displacement can never drag continuations left
            # of the canonical column (and never to column 0, which a
            # re-anchor without that floor did produce).
            #
            # Idempotency holds by construction: on a later pass the
            # source column IS the emit column, so RE-ANCHOR is 0 and
            # TO-TARGET is <= 0 for an already-deep continuation —
            # the max is 0 and nothing moves.
            delta = max(
                emitter.column - node.start_point[1],
                target_col - source_first_cont_col,
            )
            shifted = _shift(lines, delta)
            # 0.5.2 F — shift-overflow guard. When the shift pushes a
            # line past 80 (the source's indent had it fitting, the
            # new column does not), decline source-preserve entirely
            # so the wrap engine can pick a layout that fits. Without
            # this the formatter mechanically shifts a fitting source
            # into an overflowing shape and only reports it via the
            # post-emit advisory, leaving a LineLength violation the
            # wrap engine would have avoided.
            shifted_max = _max_source_preserve_line_width(
                shifted, emitter.column, emitter.tail_reserve,
            )
            if shifted_max > _MAX_LINE:
                # Signal fall-through to wrap engine.
                final_lines = None
            else:
                final_lines = shifted
        if final_lines is not None:
            # Width-check fires per-line so the advisory matches
            # what checkstyle's LineLength will actually see on
            # disk. Per-line accounting mirrors
            # `_fire_wrap_overflow_advisory`; without it, an
            # intermediate line at exactly `_MAX_LINE` chars
            # (≤ 80 on disk) but `> _MAX_LINE - tail_reserve`
            # would spuriously fire an advisory.
            max_line_width = _max_source_preserve_line_width(
                final_lines,
                emitter.column,
                emitter.tail_reserve,
            )
            if max_line_width > _MAX_LINE:
                emitter.warnings.append(FormatterWarning(
                    line=node.start_point[0] + 1,
                    column=node.start_point[1] + 1,
                    message=(
                        "source-preserved arg list overflows 80 "
                        f"chars (max line width {max_line_width}). "
                        "Split the contained literal or expression "
                        "into smaller chunks so the formatter can "
                        "re-indent within the line limit."
                    ),
                ))
            emitter.write_raw_lines(
                "\n".join(final_lines),
                strip_trailing_ws=True,
            )
            return
        # Fall through to wrap engine — shift-up would have
        # overflowed, so let the wrap engine choose a shape.
    # Source-preserved first line wouldn't fit and there
    # are no comments — fall through. The wrap engine
    # below picks a layout that fits at the new column.

    # 0.5.0 item 10 — spec C6 extension to method/constructor
    # call parens, restricted to single-arg calls whose only
    # argument is itself a `binary_expression`. The call's `(`
    # becomes a governing paren for the inner binary so its
    # operator continuations paren-align under the column after
    # `(`, matching the spec C6 grouping-paren behavior.
    #
    # Scope is deliberately narrow: applying this to lambdas,
    # method chains, or object creations as single args
    # interacts with `try_priorities`' speculative emits in
    # ways that break idempotency (a single-arg `.execute(
    # lambda)` chain whose paren-aligned candidate fires on
    # the first pass but not the second can re-emit at a
    # different column). Multi-arg calls keep the existing
    # P2-greedy / P4 cascade unchanged — spec C6's extension
    # to call parens applies only when there is a single arg
    # to anchor.
    single_arg_binary = (
        len(args) == 1
        and args[0].type == "binary_expression"
    )

    def _emit_arg_with_optional_paren_align(arg: Node) -> None:
        # Binary positional arg paren-align: when a positional
        # arg is a binary expression, set `paren_align_col` to
        # the arg's start column so the binary's continuation
        # operators paren-align under the arg's first operand
        # instead of falling back to the `block + 4`
        # cumulative indent. This produces:
        #
        #     assertTrue(cond,
        #                "msg "
        #                    + var
        #                    + " more");
        #
        # instead of:
        #
        #     assertTrue(cond,
        #                "msg "
        #         + var + " more");      // `+` at col 8
        #
        # Narrow to direct binary_expression (no paren unwrap)
        # to avoid the idempotency drift that originally
        # narrowed the single-arg call-paren extension to
        # binary args only.
        if arg.type == "binary_expression":
            arg_col = emitter.column
            prev_align = emitter.set_paren_align_col(arg_col)
            try:
                _emit_node(emitter, source, arg)
            finally:
                emitter.set_paren_align_col(prev_align)
        else:
            _emit_node(emitter, source, arg)

    # 0.7.0: set by emit_p1 when an argument's emission introduced
    # newlines and that argument is NOT one that legitimately owns
    # multiple rows. A block-bodied lambda or a text block spans
    # rows by nature, and P1 is the right shape for them — that is
    # what the single-arg lambda fix relies on. But an ordinary
    # argument that had to WRAP means P1 is producing the partial
    # break the standards' "Anti-pattern" section forbids: some
    # arguments on the call line, the rest beneath at a different
    # column.
    p1_invalid_wrap = [False]

    def emit_p1() -> None:
        p1_invalid_wrap[0] = False
        emitter.write("(")
        if single_arg_binary:
            arg_col = emitter.column
            prev_align = emitter.set_paren_align_col(arg_col)
            try:
                _emit_node(emitter, source, args[0])
            finally:
                emitter.set_paren_align_col(prev_align)
        else:
            cont_col = emitter.column
            prev_arg_multi_row = False
            for index, arg in enumerate(args):
                if index > 0:
                    if prev_arg_multi_row:
                        # Item 8 invariant in arg-list P1:
                        # when the previous arg emitted
                        # multi-row (a nested call / lambda /
                        # binary wrapped), break before this
                        # arg so it doesn't jam onto the
                        # wrapped construct's tail line. The
                        # break lands at the call's post-`(`
                        # column.
                        emitter.write(",")
                        emitter.newline()
                        emitter.write(" " * cont_col)
                    else:
                        emitter.write(", ")
                operand_start = emitter.line_count
                _emit_arg_with_optional_paren_align(arg)
                prev_arg_multi_row = (
                    emitter.line_count > operand_start
                )
                if prev_arg_multi_row and not _arg_owns_its_rows(arg):
                    p1_invalid_wrap[0] = True
        emitter.write(")")

    def emit_p4_single_arg_block_indent() -> None:
        # P4 "line-start + 4" candidate — line-break before
        # the only arg; the arg lands at
        # `current_line_start_col + 4`.
        #
        # 0.6.0 anchor rule: args continue at "col of first
        # non-space on the current line + 4", NOT `block + 4`
        # relative to the enclosing statement. Keeps nested
        # emissions visually contained inside their
        # enclosing context.
        #
        # Uses `_push_indent_to_col` to bump `_indent` so
        # inner emissions that themselves compute continuation
        # cols from `_indent` (e.g. binary_expression's
        # +4-greedy `p2_col = 4 * (indent_level + 1)`) land at
        # the correct anchor-relative col. When the target
        # col isn't aligned to the 4-space grid (rare —
        # paren-align to a receiver whose length isn't a
        # multiple of 4), we push to the nearest lower
        # multiple and pad with a few extra spaces; inner
        # `_indent`-based emissions will be off by up to 3
        # cols in that edge case, an accepted trade-off.
        #
        # Sets `emitter._arg_list_p4_fired = True` so the
        # binary-expression wrap engine can detect
        # "operand's emission cascaded through arg-list P4"
        # and reject paren-align in that case (see 0.6.0
        # design note on `_arg_list_p4_fired`).
        emitter._arg_list_p4_fired = True
        line_start_col = _current_line_leading_spaces(emitter)
        target_col = line_start_col + 4
        emitter.write("(")
        emitter.newline()
        push_count, extra = _push_indent_to_col(emitter, target_col)
        _emit_p4_write_target_indent(emitter, push_count, extra)
        # Reserve 1 char for the `)` written below. Without it the
        # argument's own cascade measures only up to its last token
        # and can commit an inline shape that this closer then pushes
        # past 80 — e.g. `result.add(\n    arguments(a, b, c, d));`
        # where the inner list measured 79 and `));` made it 81.
        # The inner list has to see the closer to reject its P1.
        prev_reserve = emitter.set_tail_reserve(
            emitter.tail_reserve + 1
        )
        try:
            _emit_node(emitter, source, args[0])
        finally:
            emitter.set_tail_reserve(prev_reserve)
        emitter.write(")")
        for _ in range(push_count):
            emitter.pop_indent()

    def emit_p4_single_arg_paren_defer() -> None:
        # Paren-defer candidate (0.6.0 Option D). Continuation
        # column = `paren_expr_col + 3` (= "col of enclosing
        # `(` + 4"), when a `parenthesized_expression`
        # (grouping OR control-flow) set `paren_expr_col`.
        # Without an enclosing group, mirrors block+4.
        #
        # This candidate is the LAST in the arg-list cascade so
        # `try_priorities`' spec C1 emit-and-warn fallback
        # commits it when NO earlier candidate fit. That gives
        # us the right behavior for the canary (literal that
        # can't be split — both block+4 and paren-defer
        # overflow, paren-defer wins as last) and for Case 5
        # long identifiers (identifier too long to fit at any
        # column — paren-defer wins for the semantic-alignment
        # reason). Short args that fit at block+4 win block+4
        # earlier in the cascade, so we don't destabilize outer
        # emissions that expect the shallower shape (e.g. the
        # `arg_list_wrap/03` binary chain's `.asList(timers)`).
        #
        # `paren_expr_col` is set ONLY by
        # `_emit_parenthesized_expression` — never by item 10's
        # extension in `emit_p1`. That discrimination is what
        # keeps this rule tied to grouping/control-flow parens
        # rather than method-call parens.
        emitter.write("(")
        emitter.newline()
        if emitter.paren_expr_col is not None:
            emitter.write(" " * (emitter.paren_expr_col + 3))
            _emit_node(emitter, source, args[0])
            emitter.write(")")
        else:
            # Block-relative, and therefore unmoored from this call's
            # `(`. Flag it so callers that can reposition the whole
            # construct get the chance to avoid reaching this tier.
            emitter._anchor_escaped = True
            emitter.push_indent()
            emitter.write_indent()
            _emit_node(emitter, source, args[0])
            emitter.write(")")
            emitter.pop_indent()

    def emit_p2_greedy() -> None:
        # P2: two-line paren-aligned comma-packed. Per spec
        # "Method Call Arguments / Priority 2": break on a
        # comma as late as possible (pack as many args as fit
        # on the call line) and continue the rest on a
        # SINGLE continuation line aligned to the first
        # column after `(`.
        #
        # The two-line constraint distinguishes P2 from P3
        # (paren-aligned one-per-line): P2 must fit the
        # ENTIRE arg list on the call line + one continuation
        # line, otherwise the wrap engine escalates to P3
        # (each arg on its own line). This is what the spec
        # calls out in "Method Call Arguments" as the "two-
        # line comma-packed form ... fits on exactly two
        # lines." A pre-0.6 bug allowed N-line packed shapes;
        # 0.6.0 tightens to two-line strict.
        #
        # If P2 would spill onto a third line, `try_priorities`
        # sees the emission failed the two-line invariant via
        # `p2_committed_lines > 2` and falls through to
        # `emit_p3_paren_one_per_line`.
        emitter.write("(")
        cont_col = emitter.column
        effective_max = _MAX_LINE - emitter.tail_reserve
        prev_arg_multi_row = False
        # Start-of-P2 line count for the two-line check. P2
        # is committed only if `emitter.line_count -
        # p2_start_line_count <= 1` (== 0 → all inline on
        # the call line, == 1 → one continuation line, > 1
        # → three or more lines, rejected).
        p2_start_line_count = emitter.line_count
        for index, arg in enumerate(args):
            if index == 0:
                operand_start = emitter.line_count
                _emit_arg_with_optional_paren_align(arg)
                prev_arg_multi_row = (
                    emitter.line_count > operand_start
                )
                continue
            if prev_arg_multi_row:
                # Item 8 invariant for arg lists: the previous
                # arg's emission introduced newlines (a nested
                # call / lambda / binary wrapped multi-row),
                # so force break before this arg. Otherwise
                # the next arg lands at whatever column the
                # prior arg's wrap tail ended on, jamming
                # `arg)` onto the same line as the wrapped
                # construct's closing.
                emitter.write(",")
                emitter.newline()
                emitter.write(" " * cont_col)
                operand_start = emitter.line_count
                _emit_arg_with_optional_paren_align(arg)
                prev_arg_multi_row = (
                    emitter.line_count > operand_start
                )
                continue
            saved = emitter.snapshot()
            emitter.write(", ")
            operand_start = emitter.line_count
            prev_p4 = emitter._arg_list_p4_fired
            emitter._arg_list_p4_fired = False
            _emit_arg_with_optional_paren_align(arg)
            widths_ok = (
                emitter.last_lines_max_width(saved[0])
                <= effective_max
            )
            if index == len(args) - 1:
                # Reserve 1 char of slack on the final arg
                # for the trailing `)` that follows.
                #
                # Asymmetry-justification: `widths_ok` above is
                # a multi-line check (`last_lines_max_width`),
                # while this final-arg check is column-only
                # (`emitter.column`, the in-progress line's
                # width). The combined gate is still correct
                # because the multi-line check has already
                # rejected any speculative emit whose
                # intermediate wrapped line overflows; only the
                # last line's tail (current column) still needs
                # to leave room for the `)`. If a future
                # refactor splits the gate, preserve that
                # invariant: any intermediate line's width must
                # be `<= effective_max`, only the final line
                # needs the `< effective_max` (strict) cap.
                widths_ok = (
                    widths_ok
                    and emitter.column < effective_max
                )
            # 0.6.0: reject the packed emission when the
            # arg's own emission cascaded through arg-list
            # P4 (leaf-arg wrap) — packing `arg1, deepCall(`
            # then wrapping deepCall's args produces the
            # "split call on same line as previous arg"
            # shape (line 1 has `arg1, deepCall(`, line 2
            # has `<indent>innerArg)`). Same line count as
            # break-before-then-inline-emit, but the latter
            # is cleaner. Same detection mechanism as
            # binary emit's `paren_inner_wrap` — see
            # `Emitter._arg_list_p4_fired`.
            arg_wrapped_via_p4 = emitter._arg_list_p4_fired
            emitter._arg_list_p4_fired = prev_p4 or arg_wrapped_via_p4
            # 0.7.0: same reasoning as P1's `p1_invalid_wrap`. Packing
            # this arg onto the call line "fits" only because the arg
            # itself wrapped internally — every emitted line is under
            # the cap, so the width check passes and P2 commits a
            # partial break. Break before the arg instead, which
            # usually leaves it room to render whole. Arguments that
            # inherently own multiple rows are exempt.
            arg_invalid_wrap = (
                emitter.line_count > operand_start
                and not _arg_owns_its_rows(arg)
            )
            if not widths_ok or arg_wrapped_via_p4 or arg_invalid_wrap:
                emitter.restore(saved)
                emitter._arg_list_p4_fired = prev_p4
                emitter.write(",")
                emitter.newline()
                emitter.write(" " * cont_col)
                operand_start = emitter.line_count
                _emit_arg_with_optional_paren_align(arg)
                emitter._arg_list_p4_fired = (
                    prev_p4 or emitter._arg_list_p4_fired
                )
            prev_arg_multi_row = (
                emitter.line_count > operand_start
            )
        emitter.write(")")

    # Closure-shared out-parameter: emit_p3 records whether
    # its ARG 0 emission caused arg-list P4 to fire. The
    # multi-arg cascade reads this to distinguish "arg 0
    # packed with `(` fires P4 (defect-3 pathology — shallow
    # anchor from outer line's leading spaces)" from "args 1+
    # fire P4 at deeper paren-align cols (spec-compliant)".
    p3_arg0_fired_p4 = [False]
    # 0.7.0 — set when any argument's P3 emission left a
    # line starting left of the paren-align column. Read at the
    # commit check to escalate the whole list to P4.
    p3_arg_escaped = [False]
    # 0.7.0 — an ordinary argument that WRAPPED inside the
    # paren-aligned shape. Same rule P1 and P2 already enforce: if an
    # argument breaks, the argument list breaks.
    p3_arg_invalid_wrap = [False]

    def emit_p3_paren_one_per_line() -> None:
        # P3: paren-aligned, one argument per line. Per spec
        # "Method Call Arguments / Priority 3": each arg on
        # its own line, all args left-aligned to the first
        # column after `(`. Fires when P2's two-line packed
        # shape can't accommodate the arg list.
        #
        # Distinct from P4 (block+4 one-per-line, which
        # anchors relative to the CALL LINE'S start, not
        # relative to `(`): P3 wins when args fit at the
        # deeper paren-align col; P4 is the fallback when
        # any arg's own width exceeds what fits at
        # paren-align.
        emitter.write("(")
        cont_col = emitter.column
        for index, arg in enumerate(args):
            if index > 0:
                emitter.write(",")
                emitter.newline()
                emitter.write(" " * cont_col)
            if index == 0:
                # 0.6.0 defect-3 detection: track whether arg 0's
                # emission cascades through arg-list P4. Arg 0 is
                # packed with `(` on the caller's line, so its
                # P4 anchor derives from the OUTER line's leading
                # spaces — potentially much shallower than
                # `cont_col`. The cascade uses this signal to
                # fall to P4 (block+4 one-per-line) in that case.
                saved_p4 = emitter._arg_list_p4_fired
                emitter._arg_list_p4_fired = False
            arg_start_line = emitter.line_count
            prev_raw = emitter._raw_rows_emitted
            emitter._raw_rows_emitted = False
            _emit_arg_with_optional_paren_align(arg)
            arg_used_raw_rows = emitter._raw_rows_emitted
            emitter._raw_rows_emitted = prev_raw or arg_used_raw_rows
            # 0.7.0 — "if an argument breaks, the argument list
            # breaks", applied at P3 as it already is at P1 and P2.
            # A paren-aligned argument that wrapped internally puts
            # its own continuation at the column its SIBLINGS use, so
            # the continuation reads as another argument:
            #
            #     multilineFormat(rr.getFormat()
            #                     + " record not as expected:",
            #                     "RECORDS TEXT: ",
            #
            # Breaking the whole list moves the arguments to their own
            # column and leaves the continuation clearly subordinate.
            # Arguments that inherently own rows are exempt, as
            # everywhere else this rule is applied.
            if (
                emitter.line_count > arg_start_line
                and not _arg_owns_its_rows(arg)
                and not arg_used_raw_rows
            ):
                p3_arg_invalid_wrap[0] = True
            # 0.7.0 — whole-list escalation. If ANY argument
            # cannot render at `cont_col` without either overflowing
            # or escaping to a shallower anchor, the paren-aligned
            # shape is wrong for the WHOLE list: every argument
            # behaves as if the first had not fit, and the cascade
            # falls to P4 (break before the first argument).
            #
            # Testing every argument is the point. The old code chose
            # paren-alignment because the EARLY arguments fit, then
            # discovered a later one could not and orphaned it —
            # which is why the same construct renders correctly at
            # one argument and wrong at the next:
            #
            #     new SzInterestingEntity(100L,
            #                             1,
            #                             Arrays.asList(
            #                                 "FLAG"),      <- correct
            #                             Arrays.asList(
            #         createSampleRecord("DS", "R")));      <- orphan
            #
            # An argument that "escapes" is one whose emission left a
            # line starting LEFT of `cont_col`. That happens when the
            # argument's own cascade runs out of tiers and commits its
            # block-relative C1 fallback, whose anchor has nothing to
            # do with this argument list.
            # Start one row PAST `arg_start_line`. `line_count`
            # excludes the in-progress line, so `_lines[
            # arg_start_line]` is the row that was already open when
            # this argument began — not a row the argument created.
            # For `index == 0` that is the call line itself, whose
            # indent is the statement indent and so is ALWAYS left of
            # `cont_col`; scanning it made every wrapping first
            # argument report an escape, so the signal fired on
            # evidence that was never about the argument at all.
            #
            # Note the escape signal is not what decides this shape
            # any more. The argument-breaks rule below escalates a
            # wrapping first argument to P4 on its own, for a
            # different and valid reason, so correcting this scan
            # no longer restores the paren-aligned form — see the
            # `18_arg0_wraps_so_whole_list_breaks` fixture. What the
            # correction still buys is that the ESCAPE signal means
            # what it says: a row anchored somewhere this list did
            # not choose.
            #
            # For `index > 0` the skipped row is the argument's own
            # first row, which the arg list opened at exactly
            # `cont_col`, so it can never be an escape either.
            # Exempt the same arguments the wrap flag exempts. A row
            # left of `cont_col` is evidence of an escape only when the
            # ARGUMENT LIST is what put it there. A text block's content
            # starts wherever the author wrote it — often column 0 — and
            # a source-preserved argument replays its own columns; in
            # neither case did this list's cascade choose the anchor, so
            # neither is evidence about this list.
            if not _arg_owns_its_rows(arg) and not arg_used_raw_rows:
                rows = list(emitter._lines[arg_start_line + 1:])
                if emitter.line_count > arg_start_line:
                    rows.append(emitter._current)
                for row in rows:
                    if not row.strip():
                        continue
                    if len(row) - len(row.lstrip()) < cont_col:
                        p3_arg_escaped[0] = True
                        break
            if index == 0:
                if emitter._arg_list_p4_fired:
                    p3_arg0_fired_p4[0] = True
                emitter._arg_list_p4_fired = (
                    saved_p4 or emitter._arg_list_p4_fired
                )
        emitter.write(")")

    def emit_p4_multi_arg() -> None:
        # P4 fallback: line-break before the first arg; each
        # arg on its own line at "current line's start col
        # + 4". Uses `_push_indent_to_col` so inner
        # `_indent`-based emissions (e.g. a binary_expression
        # arg's p2_col continuation) align relative to the
        # anchor col rather than the outer block indent.
        # See `emit_p4_single_arg_block_indent` for the
        # detailed design note.
        #
        # Uses `_emit_arg_with_optional_paren_align` (the item-10
        # helper) rather than a bare `_emit_node` so that a
        # `binary_expression` arg (e.g. `a || b || c` as a
        # positional arg) sees `paren_align_col` = arg's start
        # col. Without this, the binary's cascade falls to the
        # +4 fallback (`emit_p2` boolean-leftmost-break) which
        # can pack multiple `||` operands on a single line and
        # then let the LAST operand's inner call arg-list wrap
        # internally — producing the "wrap inside `matches(`
        # instead of at `||`" pathology surfaced by
        # `data-mart-replicator/BuildInfoTest.java:51-55` in the
        # 0.6.0 consumer trial.
        emitter._arg_list_p4_fired = True
        line_start_col = _current_line_leading_spaces(emitter)
        target_col = line_start_col + 4
        emitter.write("(")
        push_count, extra = _push_indent_to_col(emitter, target_col)
        for index, arg in enumerate(args):
            emitter.newline()
            _emit_p4_write_target_indent(emitter, push_count, extra)
            # Reserve the one character this loop appends after the
            # argument — `,` for every argument but the last, `)` for
            # the last. Without it the argument measures itself against
            # the bare limit, commits at exactly 80, and the separator
            # lands in column 81. The overflow is invisible to the
            # argument (which fits) and to this function (which has
            # already committed), so it survives every reformat.
            #
            # The INHERITED reserve is dropped for every argument but
            # the last. It stands for characters the parent appends
            # after this whole construct — the `;` of the enclosing
            # statement, say — and those land on the construct's final
            # line only. A middle argument's row is finalized with just
            # its comma, so carrying the parent's reserve there makes
            # the budget one char too tight and splits an argument
            # whose row would have measured 80 columns, comma
            # included, which is legal:
            #
            #     SzConfigManager.class.getMethod("registerConfig",
            #                                     String.class),
            # where
            #     SzConfigManager.class.getMethod("registerConfig", String.class),
            # is 80 columns and legal.
            is_last = index == len(args) - 1
            prev_sep = emitter.set_tail_reserve(
                (emitter.tail_reserve + 1) if is_last else 1
            )
            try:
                _emit_arg_with_optional_paren_align(arg)
            finally:
                emitter.set_tail_reserve(prev_sep)
            if index < len(args) - 1:
                emitter.write(",")
        emitter.write(")")
        for _ in range(push_count):
            emitter.pop_indent()

    def emit_p4_packed() -> None:
        # 0.7.0 — "P4-packed": break right after `(` and put EVERY
        # argument on a single continuation line at `line_start + 4`.
        #
        # This is the zero-args-on-the-first-line member of the greedy
        # family. The rule for that family is two lines maximum: zero
        # or more arguments on the call line, and ALL remaining
        # arguments on one continuation line. P2 covers the "one or
        # more on the call line" case; this covers "none on the call
        # line", which arises when the call's own prefix is already so
        # wide that the paren-align column has no useful room left:
        #
        #     BadOptionParametersException ex = new BadOptionParametersException(
        #         COMMAND_LINE, CONFIG, "--config", List.of());
        #
        # Without this tier the cascade skips straight to one argument
        # per line, which costs three extra lines here for no gain.
        # Because `line_start + 4` is far shallower than the
        # paren-align column, this tier frequently fits where P2
        # cannot.
        emitter._arg_list_p4_fired = True
        line_start_col = _current_line_leading_spaces(emitter)
        target_col = line_start_col + 4
        emitter.write("(")
        push_count, extra = _push_indent_to_col(emitter, target_col)
        emitter.newline()
        _emit_p4_write_target_indent(emitter, push_count, extra)
        for index, arg in enumerate(args):
            if index > 0:
                emitter.write(", ")
            _emit_arg_with_optional_paren_align(arg)
        emitter.write(")")
        for _ in range(push_count):
            emitter.pop_indent()

    # P1 is the AST-deterministic single-line candidate, but
    # may emit a multi-row layout when an intermediate arg
    # wraps multi-row and item-8 forces a break before
    # subsequent args. try_priorities still
    # measures actual rendered widths, so a P1 emit that
    # blows past 80 chars falls through to the next
    # candidate. Letting P1 try keeps the decision
    # deterministic from the AST — earlier code
    # short-circuited P1 when any arg's SOURCE was multi-row,
    # which made the decision flip between formatter passes.
    cascade_start = emitter.line_count
    if len(args) == 1:
        # 0.7.0 fix (item A): when the single arg is a
        # block-body lambda (`.method(() -> { body })`), the
        # lambda body's own line widths are the body's
        # responsibility — they're wrapped by the block's own
        # emission logic, not by the enclosing arg-list. But
        # `try_priorities`' default fit check computes
        # `last_lines_max_width` across EVERY emitted line
        # including the body, so a source-code line inside
        # the lambda body that exceeds 80 chars (already a
        # pre-existing overflow) rejects P1 and cascades to
        # P4 (break before the arrow). P4 doesn't fix the
        # body-line overflow — it just adds `\n<indent>()
        # -> {` before the lambda, pushing every body line
        # +4 cols deeper (which typically creates NEW
        # overflows and cascading advisories). Pre-0.7.0
        # sites: `sz-sdk-java-grpc` had 22 idiomatic
        # `this.performTest(() -> { … })` calls rewritten
        # to the P4 shape purely because unrelated body
        # lines were >80 chars.
        #
        # For block-body-lambda single-arg calls, run a
        # manual cascade: try P1 with a fit check that
        # excludes the lambda body's lines. Only the CALL
        # LINE (up through `() -> {`) and the CLOSING LINE
        # (`})`) need to fit at the enclosing widths. Body
        # lines are the body's own concern.
        if _is_block_body_lambda(args[0]):
            saved = emitter.snapshot()
            emit_p1()
            effective_max = _MAX_LINE - emitter.tail_reserve
            # The call/opener line — first finalized line since
            # the P1 emit began, or the in-progress line if
            # nothing was finalized yet (defensive; the block
            # body always emits at least one newline).
            opener_ok = True
            if saved[0] < len(emitter._lines):
                opener_ok = (
                    len(emitter._lines[saved[0]]) <= _MAX_LINE
                )
            # The closer line — the in-progress line at the
            # end of P1 emit, containing `})` plus tail
            # context the parent will append.
            closer_ok = (
                emitter.column + emitter.tail_reserve <= _MAX_LINE
            )
            if opener_ok and closer_ok:
                _fire_wrap_overflow_advisory(
                    emitter, node, cascade_start, "argument list"
                )
                return
            emitter.restore(saved)
        # 0.7.0 nested-call wrap (rule 1): when the sole argument
        # is itself a method invocation — plain, or the head of a
        # `.a().b()` chain — that cannot stay on one line, break
        # BEFORE it instead of letting it wrap in place.
        #
        # P1's ordinary width check is not enough here. A nested
        # call that wraps internally still "fits", because every
        # emitted line lands under the cap — so P1 commits and
        # produces a shape where the argument list starts at the
        # enclosing call's paren column and its continuation
        # lines march far to the right:
        #
        #     reportUpdates.add(builder(DATA_SOURCE_SUMMARY,
        #                               ENTITY_COUNT,
        #                               entityId).records(-1)
        #         .build());
        #
        # Rejecting P1 whenever the nested call did not stay
        # inline sends the cascade to `line_start + 4`, which
        # gives the nested arg list a far roomier column and
        # anchors the chain tail on the 4-space grid:
        #
        #     reportUpdates.add(
        #         builder(DATA_SOURCE_SUMMARY,
        #                 ENTITY_COUNT,
        #                 entityId)
        #             .records(-1)
        #             .build());
        #
        # The test is "did it stay on one line", NOT "which
        # column fits better". That matters: a comparative
        # two-column fit probe is what made
        # `builder(...).records(-1).build()` non-idempotent
        # before 0.7.0, because the two columns could rank
        # differently on the second pass. A single monotone
        # did-it-wrap check has no such failure mode.
        if args[0].type in (
            "method_invocation",
            "object_creation_expression",
        ) and not _is_anonymous_class(args[0]):
            saved = emitter.snapshot()
            emit_p1()
            effective_max = _MAX_LINE - emitter.tail_reserve
            stayed_inline = emitter.line_count == saved[0]
            if not (
                stayed_inline
                and emitter.last_lines_max_width(saved[0])
                <= effective_max
            ):
                emitter.restore(saved)
                try_priorities(
                    emitter,
                    [
                        emit_p4_single_arg_block_indent,
                        emit_p4_single_arg_paren_defer,
                    ],
                )
        else:
            # Standard single-arg cascade: P1 inline → P4 block+4
            # → P4 paren-defer (last-committed).
            candidates: list[Callable[[], None]] = [
                emit_p1,
                emit_p4_single_arg_block_indent,
                emit_p4_single_arg_paren_defer,
            ]
            try_priorities(emitter, candidates)
    else:
        # Multi-arg cascade — manual snapshot/restore because
        # P2's two-line constraint (per spec "Method Call
        # Arguments / Priority 2 — Two-line, paren-aligned,
        # comma-packed") cannot be expressed as a pure
        # width check inside `try_priorities`. The cascade:
        #
        #   - P1 (inline all): every operand on the call line.
        #   - P2 (two-line packed): args pack onto call line
        #     + one continuation line. Fits ONLY when the
        #     entire arg list needs at most one continuation
        #     line. If P2 would spill to a third line,
        #     reject.
        #   - P2b (two-line, none on the call line): break
        #     after `(` and put EVERY arg on one continuation
        #     line at `line_start + 4`. Same two-line
        #     invariant as P2 — the other member of the greedy
        #     family, tried immediately after it and BEFORE
        #     P3. Named `emit_p4_packed` for historical
        #     reasons; the spec calls it priority 2b.
        #   - P3 (paren-aligned one-per-line): each arg on
        #     its own line at the paren-align column.
        #   - P4 (block+4 one-per-line): each arg on its own
        #     line at the line-start-col + 4 anchor. Spec
        #     C1 emit-and-warn fallback.
        initial = emitter.snapshot()
        effective_max = _MAX_LINE - emitter.tail_reserve
        # P1. Reset the arg-list-P4 flag before the speculative
        # emit so the post-emit check detects only P4 firings
        # caused by THIS emit_p1(), not sticky True from a prior
        # statement's leftover state. The pre-existing value is
        # captured in `prev_p4` and restored on rollback or
        # OR-merged forward on commit — matching the ownership
        # rule for the flag ("readers save-reset-check-restore").
        #
        # 0.6.0 defect-3 fix: reject P1's mixed-shape commit
        # when any arg's own emission cascaded through arg-list
        # P4. Without this check, P1's item-8 break-before-arg
        # invariant (used when a previous arg wrapped multi-row)
        # produces the "arg1 packed on call line with own args
        # wrapped at line-start+4, args2+ paren-aligned" mixed
        # shape — see `SzFlagTest.java:551` in the 0.6.0
        # consumer trial audit. Falling through to P2/P3
        # produces the spec-compliant paren-aligned shape.
        #
        # Note: this catches only arg-list-P4 firings, NOT
        # source-preserve or chain/binary wraps. Pre-existing
        # bad source that source-preserve echoes may still
        # produce a mixed shape; adopters upgrading from
        # 0.5.x should manually re-flow those sites (or the
        # width opt-out will catch them when the developer
        # collapses the wrap).
        prev_p4 = emitter._arg_list_p4_fired
        emitter._arg_list_p4_fired = False
        emit_p1()
        p1_p4_fired = emitter._arg_list_p4_fired
        # 0.7.0: reject P1 when an ordinary argument had to WRAP.
        # P1's item-8 invariant lets an argument wrap internally and
        # then breaks before the NEXT argument, producing exactly the
        # partial break the standards' "Anti-pattern" section forbids
        # — some arguments on the call line, the rest beneath at a
        # different column:
        #
        #     assertThrows(IllegalStateException.class, () -> mapB.put("k",
        #                                                             "v"));
        #
        # Rejecting sends it to P2, which puts each argument in one
        # column and leaves the wrapped argument room to fit whole:
        #
        #     assertThrows(IllegalStateException.class,
        #                  () -> mapB.put("k", "v"));
        #
        # Arguments that legitimately own multiple rows (block-bodied
        # lambdas, text blocks) do NOT trip this — P1 is the correct
        # shape for `performTest(() -> { … })` and rejecting it there
        # would undo the single-arg lambda fix. `_arg_owns_its_rows`
        # draws that line.
        if (
            emitter.last_lines_max_width(initial[0]) <= effective_max
            and not p1_p4_fired
            and not p1_invalid_wrap[0]
        ):
            emitter._arg_list_p4_fired = prev_p4 or p1_p4_fired
            _fire_wrap_overflow_advisory(
                emitter, node, cascade_start, "argument list"
            )
            return
        emitter.restore(initial)
        emitter._arg_list_p4_fired = prev_p4
        # P2 (two-line packed).
        #
        # 0.7.0 nested-call wrap (rule 2): skipped entirely when
        # this call is a positional arg of another call or the
        # receiver of a chain. The half-packed shape P2 produces
        # is hard to read once it has to be tracked alongside an
        # enclosing construct, so the cascade goes straight to
        # P3's one-arg-per-line column. See
        # `_is_nested_or_chained_call`.
        if not _is_nested_or_chained_call(node):
            p2_snap = emitter.snapshot()
            emit_p2_greedy()
            p2_line_count = emitter.line_count - p2_snap[0]
            p2_fits = (
                emitter.last_lines_max_width(p2_snap[0])
                <= effective_max
                and p2_line_count <= 1
            )
            if p2_fits:
                _fire_wrap_overflow_advisory(
                    emitter, node, cascade_start, "argument list"
                )
                return
            emitter.restore(p2_snap)
            # 0.7.0 — spec priority 2b ("P4-packed" here for
            # historical reasons): the other member of the two-line
            # greedy family, with ZERO arguments on the call line.
            # Tried immediately after P2 and BEFORE P3 — hence 2b
            # rather than 3b in the spec — because it costs two
            # lines where P3 costs one per argument, and because
            # `line_start + 4` has room the paren-align column
            # often does not.
            #
            # Inside the same rule-2 guard as P2, and for the same
            # reason: this is a GREEDY tier, and rule 2 withdraws the
            # greedy family from embedded calls. Outside the guard it
            # re-introduced exactly the packed-inside-an-enclosing-
            # construct shape rule 2 removed, e.g.
            # `builder(\n    A, B, C, D)` as a positional argument.
            #
            # Same two-line invariant as P2: reject if the emission
            # spills past one continuation line, so this stays greedy
            # rather than becoming a second one-per-line shape.
            packed_snap = emitter.snapshot()
            emit_p4_packed()
            packed_line_count = emitter.line_count - packed_snap[0]
            if (
                emitter.last_lines_max_width(packed_snap[0])
                <= effective_max
                and packed_line_count <= 1
            ):
                _fire_wrap_overflow_advisory(
                    emitter, node, cascade_start, "argument list"
                )
                return
            emitter.restore(packed_snap)
        # P3 (paren-aligned one-per-line).
        # 0.6.0 defect-3 fix (extends the P1 reject): P3 packs
        # arg 0 with the opening `(`. If arg 0's own emission
        # cascades through arg-list P4, its anchor derives from
        # the OUTER line's leading spaces (shallow) rather than
        # `cont_col` — same "deep-orphan" shape P1 produces.
        # Reject P3 in that specific case; args 1+ firing P4
        # is fine because each is on its own line at cont_col
        # (P4 anchor = cont_col + 4, deeper than cont_col).
        #
        # Falling through hits P4 (block+4 one-per-line), which
        # puts arg 0 on its own line at line-start + 4 where
        # the anchor is well-defined and inner nesting stays
        # visually contained inside the enclosing context.
        p3_snap = emitter.snapshot()
        p3_arg0_fired_p4[0] = False
        p3_arg_escaped[0] = False
        p3_arg_invalid_wrap[0] = False
        emit_p3_paren_one_per_line()
        if (
            emitter.last_lines_max_width(p3_snap[0]) <= effective_max
            and not p3_arg0_fired_p4[0]
            and not p3_arg_escaped[0]
            and not p3_arg_invalid_wrap[0]
        ):
            _fire_wrap_overflow_advisory(
                emitter, node, cascade_start, "argument list"
            )
            return
        emitter.restore(p3_snap)
        # P4 (block+4 one-per-line) — spec C1 fallback,
        # commits unconditionally.
        emit_p4_multi_arg()
    _fire_wrap_overflow_advisory(
        emitter, node, cascade_start, "argument list"
    )


def _collect_method_chain(
    node: Node,
) -> tuple[Node | None, list[Node]]:
    """Flatten a `method_invocation` chain into head + segments.

    For source like `a.b().c().d()`, tree-sitter exposes a nested
    structure where the outermost `method_invocation` is `d(...)`,
    its `object` field is the `c(...)` call, whose `object` is
    the `b(...)` call, whose `object` is the `a` identifier.

    This helper walks down the `object`-field chain and returns:

        - `head`: the leftmost non-`method_invocation` expression
          (the receiver of the chain), or `None` if the leftmost
          call itself has no receiver (a bare static-style call
          like `foo()` chained as `foo().bar().baz()`).
        - `segments`: the chain in left-to-right textual order
          (`[b, c, d]` in the example above).

    Caller checks `len(segments) >= 2` to decide whether chain
    wrapping is warranted; a single-segment chain is just a
    plain call and falls back to simple emission.
    """
    segments: list[Node] = []
    current: Node | None = node
    while current is not None and current.type == "method_invocation":
        segments.append(current)
        current = current.child_by_field_name("object")
    segments.reverse()
    return current, segments


def _is_method_chain_inner(node: Node) -> bool:
    """Return True if `node` is the `object` of another
    `method_invocation` — i.e. an inner segment whose enclosing
    chain root will emit it. Used to suppress redundant chain
    detection inside an outer chain's recursive emission.
    """
    parent = node.parent
    if parent is None or parent.type != "method_invocation":
        return False
    obj = parent.child_by_field_name("object")
    return (
        obj is not None
        and obj.start_byte == node.start_byte
        and obj.end_byte == node.end_byte
    )


def _chain_segments_share_method_name(
    source: bytes, segments: list[Node]
) -> bool:
    """Return True when every chain segment calls the same
    method name. Gates `emit_p2_greedy_dot_aligned` (0.5.0 item 2b):
    same-method chains like `sb.append(a).append(b)…` benefit
    from horizontal greedy packing because each call is
    semantically equivalent; mixed-name chains like
    `.builder().setReader().get()` keep one-per-line P2 because
    each call is a distinct semantic step worth its own line.

    Requires at least 2 segments — a single-segment "chain" is
    just a plain call with no wrap candidates beyond P1.
    """
    if len(segments) < 2:
        return False
    first_name_node = segments[0].child_by_field_name("name")
    if first_name_node is None:
        return False
    first_name = _node_source_text(source, first_name_node)
    for seg in segments[1:]:
        name_node = seg.child_by_field_name("name")
        if name_node is None:
            return False
        if _node_source_text(source, name_node) != first_name:
            return False
    return True


def _emit_method_chain_wrapped(
    emitter: Emitter,
    source: bytes,
    head: Node | None,
    segments: list[Node],
) -> None:
    """Emit a method chain with spec "Method Chains" wrap rules.

    Wrap priorities (per `docs/java-coding-standards.md` §
    "Method Chains"):

        - P1: single line `head.s1().s2()...sN()`.
        - P2: head + first segment on line 1 (or, when
          `head is None`, the first two segments on line 1);
          subsequent segments on their own lines, `.` chars
          vertically aligned to the first `.` of the chain.
          The head=None shape mirrors the head=Some shape so
          the first wrap point is consistently at the second
          `.` of the chain regardless of whether the chain has
          an explicit receiver.
        - P3: head alone on line 1 (or first segment alone if
          `head is None`); each remaining segment on its own
          continuation line at single-indent past the
          statement (`4 * (indent_level + 1)`). Used when P2's
          dot-alignment column would itself push lines past
          80 chars.

    Type-arguments on any segment (`obj.<T>method(...)`) are
    refused for now — matches `_emit_method_invocation`'s
    refusal of the same shape.
    """
    for seg in segments:
        if seg.child_by_field_name("type_arguments") is not None:
            raise NotImplementedError(
                "method_invocation with explicit type arguments "
                "(`obj.<Type>method(...)`) is not yet supported."
            )

    # Is this chain a positional argument of another call?
    # Governs the rule-3 tail anchor below. `segments` is always
    # non-empty here — the sole call site gates on
    # `len(segments) >= 2`.
    chain_parent = segments[-1].parent
    chain_is_positional_arg = (
        chain_parent is not None
        and chain_parent.type == "argument_list"
    )

    # 0.7.0 nested-call wrap (rule 3): anchor the chain tail to
    # "the chain's own start column + 4" when the chain is a
    # positional argument, rather than the block-relative
    # `4 * (indent_level + 1)`.
    #
    # Scoped to the positional-argument case on purpose. A chain
    # that is an assignment RHS (`String x = foo.bar()…`) also
    # starts mid-line, but its canonical tail column IS the
    # block-relative one — anchoring to its start column would
    # push the tail out under the `=`. Inside an argument list the
    # block-relative form instead pulls the tail back to the
    # enclosing STATEMENT's indent, far left of the chain it
    # belongs to:
    #
    #     record(source, builder(DATA_SOURCE_SUMMARY,
    #                            ENTITY_COUNT,
    #                            entityId)
    #         .build());              <-- col 12, orphaned
    #
    # Anchoring to the chain's start keeps the tail visually
    # attached to its own chain, which is what rule 3 specifies.
    # Additionally requires `head is None` — a HEADLESS chain, whose
    # first segment is itself the call (`builder(a, b).records(-1)`).
    # That is the shape rule 3 is about: segments following an
    # embedded CALL, whose own argument list is what wrapped.
    #
    # When the chain has an explicit receiver
    # (`SzGrpcServices.inferStatus(x).getCode()`), the receiver is
    # typically a bare identifier sitting deep in an argument list,
    # and anchoring the tail to its column strands the segments far
    # to the right of everything:
    #
    #     assertEquals(Status.UNIMPLEMENTED.getCode(), SzGrpcServices
    #                                                      .inferStatus(
    #         new UnsupportedOperationException())
    #                                                      .getCode(),
    #
    # Three unrelated columns for one argument. The block-relative
    # anchor keeps that case readable, so it is retained.
    # The block-relative value is a FLOOR, not an alternative: a
    # chain sitting at a shallower column than its own statement
    # indent (possible when an enclosing construct emitted it at a
    # shallower position) would otherwise anchor its tail left of
    # the statement it belongs to. `max` keeps the tail at or
    # right of the canonical continuation column in every case.
    p3_col = 4 * (emitter.indent_level + 1)
    if chain_is_positional_arg and head is None:
        p3_col = max(p3_col, emitter.column + 4)

    # 0.7.0 nested-call wrap (rule 3): True when this chain is the
    # SOLE argument of its enclosing call — the exact position in
    # which rule 1 has already broken the argument out onto its
    # own line. Rules 1 and 3 travel together: once the chain owns
    # a line, its tail goes one-segment-per-line, so the tiers
    # that hang the first segment off the receiver's closing paren
    # and dot-align the rest (P1F, P3F, P2, P2-greedy) are
    # suppressed — they produce shape "C", which 0.7.0
    # deliberately removed from the vocabulary.
    #
    # Deliberately NOT "any positional argument". A chain that is
    # one of several arguments has not been broken out by rule 1,
    # and its receiver is typically a short identifier where the
    # dot-aligned shape reads well:
    #
    #     assertEquals("expected", actualMethod.replaceAll("\\s", "")
    #                                          .replaceAll("\\n", " ")
    #                                          .trim());
    #
    # Suppressing the hung tiers there would force a needless
    # one-per-line rewrite of a perfectly readable chain.
    # 0.7.0 review finding 8: additionally require `head is None`.
    # The suppression exists for chains rule 1 broke out because their
    # RECEIVER is itself a wrapping call, so the hung/dot-aligned tiers
    # anchor to a column derived from that call's arguments. When the
    # chain has an explicit receiver that is a bare identifier, the
    # dot-aligned two-line form is both readable and compact, and
    # suppressing it turned a very common test idiom into four lines
    # for no benefit:
    #
    #     assertTrue(someReceiverObject.methodOne(alphaArgument)
    #                                  .methodTwo(betaArgument));
    #
    # Matches the `head is None` condition `p3_col` already uses, so
    # the tail anchor and the tier gate now key on the same shape.
    chain_is_sole_arg = False
    if chain_is_positional_arg and head is None:
        sibling_args = [
            c for c in chain_parent.children
            if c.is_named
            and c.type not in ("line_comment", "block_comment")
        ]
        chain_is_sole_arg = len(sibling_args) == 1

    def emit_segment(seg: Node) -> None:
        name = seg.child_by_field_name("name")
        args = seg.child_by_field_name("arguments")
        if name is None or args is None:
            raise NotImplementedError(
                "method_invocation missing 'name' or "
                "'arguments' — grammar shape unexpected."
            )
        _emit_node(emitter, source, name)
        _emit_node(emitter, source, args)

    # When emit_p1 runs, this list records "did a segment's emit
    # introduce newlines because the wrap engine had to break
    # something to fit (vs. because the source itself was
    # multi-row or the body is an intrinsically multi-line
    # construct like a lambda block body)". Only the wrap-engine
    # case actually breaks chain integrity; the
    # source-preserved / intrinsically-multi-line cases leave
    # the chain ending at its natural closing position with
    # subsequent segments appended cleanly.
    #
    # Discriminator: if the segment's `arguments` node spans
    # multiple source rows (so the arg-list emitter takes the
    # source-preserve path) OR the arg list contains a lambda
    # whose body block spans multiple source rows (the lambda
    # is intrinsically multi-line in the developer's authored
    # form), newlines introduced by the segment's emit are
    # legitimate and do NOT mark the chain as broken. Newlines
    # introduced by anything else mean the wrap engine had to
    # break to fit, which DOES strand subsequent segments on
    # continuation lines mid-call — that's the regression Bug 1
    # in 0.4.2 was meant to catch.
    #
    # The head is always allowed to wrap (it can itself be
    # another chain that legitimately wraps to P2/P3); chain P1
    # only claims to keep the *segments* on whichever line the
    # head finished on.
    p1_segment_break_seen = [False]

    def _segment_emit_is_legitimately_multi_line(
        seg: Node, args_emit_column: int
    ) -> bool:
        """Predict at the segment's pre-emit position whether
        any newlines its emit introduces will come from a
        legitimate source-preservation path (developer's
        authored multi-row arg list, or a lambda body
        intrinsically multi-line in source) vs. from the
        wrap engine breaking to fit. Only the wrap-engine
        case actually strands subsequent chain segments
        mid-call.

        `args_emit_column` is the emitter column at the moment
        the segment's args open — captured BEFORE the segment
        emits, since the source-preserve gate is column-
        sensitive and the emitter's column is already past
        the args by the time the post-emit discriminator
        runs.
        """
        args = seg.child_by_field_name("arguments")
        if args is None:
            return False
        # Consult the same predicate `_emit_argument_list`
        # itself uses, evaluated at the chain segment's
        # arg-list emission column. Sharing the predicate is
        # what keeps the discriminator and the arg-list
        # emitter in agreement — without that agreement, an
        # arg list whose source-preserve gate declines (e.g.
        # because the Bug 4 width opt-out fires) but whose
        # wrap-engine P1 then overflows ends up multi-line
        # via P2/P3/P4, and a discriminator that didn't share
        # the predicate would mistakenly call that "legit",
        # stranding subsequent chain segments — the Bug 1
        # shape.
        # Note: `_arg_list_takes_source_preserve_path` reads
        # `emitter.tail_reserve` to compute `effective_max`.
        # At the chain-discriminator call site that reserve
        # belongs to the OUTER emit context (post-segment), not
        # what it will be when the inner arg list actually
        # emits. In practice this is acceptable as an
        # approximation: tail_reserve is small (single-digit
        # chars) and the source-preserve gate's width check is
        # already an under-estimate-safe bound (the actual emit
        # either matches the gate's decision, in which case it
        # fits, or overflows to the wrap engine, in which case
        # the chain's P1-newline-rejection picks it up). If a
        # future change introduces a case where the
        # discriminator and the arg-list emitter disagree on
        # the source-preserve decision due to tail_reserve
        # drift, the right fix is to thread the expected
        # tail_reserve through the predicate's signature, not
        # to defer the prediction until inside the arg list's
        # own emit (which is when the chain has already
        # committed to P1).
        if _arg_list_takes_source_preserve_path(
            emitter, source, args
        ):
            return True
        # An argument that OWNS its rows still emits multi-line
        # after opting out of source-preservation, and so still
        # strands subsequent chain segments. Mirror that here so
        # the discriminator's "will-be-multi-line" answer stays
        # consistent with what `_emit_argument_list` does.
        #
        # 0.7.0 — this tests `_arg_owns_its_rows`, a STRUCTURAL
        # predicate, where it once asked whether a lambda, binary
        # expression or method invocation argument spanned rows in
        # the SOURCE. That older question became wrong when the
        # width-based source-preservation fallback was retired.
        # Before the retirement, a multi-row `method_invocation`
        # argument was likely to be re-emitted multi-row, so the
        # source was a fair predictor. Now every such argument goes
        # to the wrap engine, which will happily pull it back onto
        # one line — so "it spans rows in the source" predicts
        # nothing except how the file was last written, and reading
        # it made this predicate the last channel by which stale
        # layout steered a live decision. At an indent deep enough
        # that the argument overflows the paren-aligned column but
        # still fits one level in:
        #
        #     // pass 1 — inner call on one source row, so the
        #     // segment reads as wrap-engine multi-line and the
        #     // chain backs off
        #     boolean usePg = Boolean.TRUE.toString().equals(
        #         System.getProperty(LONG_PROPERTY_KEY_LITERAL));
        #
        #     // pass 2 — the inner call now spans rows, reads as
        #     // "legitimate", no back-off, one segment per line
        #     boolean usePg = Boolean.TRUE
        #         .toString()
        #         .equals(
        #             System.getProperty(LONG_PROPERTY_KEY_LITERAL));
        #
        # Those two shapes alternated forever. Structurally-owned
        # rows (block-bodied lambda, text block, anonymous class)
        # are the only rows the wrap engine cannot reclaim, so they
        # are the only ones that legitimately strand a chain tail.
        for child in args.named_children:
            inner = child
            while inner.type == "parenthesized_expression":
                # Filter comments out — tree-sitter-java exposes
                # leading `//` / `/* */` as named children, so
                # `named[0]` could otherwise unwrap to a comment
                # instead of the inner expression and miss a
                # multi-row binary / chain / lambda.
                named = [
                    c for c in inner.children
                    if c.is_named
                    and c.type not in ("line_comment", "block_comment")
                ]
                if not named:
                    break
                inner = named[0]
            if _arg_owns_its_rows(inner):
                return True
        return False

    def emit_p1() -> None:
        p1_segment_break_seen[0] = False

        def emit_seg_strict(seg: Node) -> None:
            before = emitter.line_count
            # Capture the column AT the segment's args open
            # (one past the `name` token). emit_segment writes
            # name + args; the args open at `emitter.column +
            # len(name)`. Source-preserve's first_line_fits
            # check needs that column, not the post-emit
            # column.
            name_node = seg.child_by_field_name("name")
            name_text = (
                _node_source_text(source, name_node)
                if name_node is not None
                else ""
            )
            args_emit_column = emitter.column + len(name_text)
            emit_segment(seg)
            if emitter.line_count > before:
                # Newlines introduced. Acceptable only if BOTH:
                #   (1) the discriminator says the source itself
                #       drove the multi-line layout (multi-row
                #       args that take the source-preserve path
                #       at this column, or a lambda body that's
                #       multi-row in source), AND
                #   (2) the total chain has at most TWO segments.
                #
                # The 2-segment cap reflects the design
                # preference "break on method chaining (greedily)
                # before breaking on parameter names for a method
                # in the chain": a 3+ segment chain whose
                # middle segment has multi-line args should
                # wrap at the dots (chain P2), not pile the
                # trailing segments onto the continuation line
                # that starts with the closing `)` of the
                # multi-line args. The cap of TWO matches the
                # user's preferred layout for short chains like
                # `cls.getResource(\n    arg).toString()` (2
                # segments) while rejecting longer chains like
                # `obj.builder().setReader(r).setFormat(\n  fmt)
                # .get()` (4 segments) which read better as a
                # dot-aligned wrap.
                legit = _segment_emit_is_legitimately_multi_line(
                    seg, args_emit_column
                )
                if (not legit) or len(segments) > 2:
                    p1_segment_break_seen[0] = True

        if head is not None:
            _emit_node(emitter, source, head)
            for seg in segments:
                emitter.write(".")
                emit_seg_strict(seg)
        else:
            emit_seg_strict(segments[0])
            for seg in segments[1:]:
                emitter.write(".")
                emit_seg_strict(seg)

    # 0.6.0 P2 Q-CHAIN-4 backoff signal. Set to True when any
    # chain segment's emit inside emit_p2 introduces newlines
    # that are NOT from a legitimately multi-line source
    # (multi-row lambda body, multi-row text block, source-
    # preserved arg list). Consulted at the try_priorities
    # commit-check to reject P2 even if widths fit — Q-CHAIN-4
    # says "back off to a shallower tier when a chain method's
    # own args wrap." The shape produced when P2 emits but a
    # chain method's args wrap mid-emit is visually confused
    # (dot-align chain col + deeper args col mixed) — cleaner
    # to fall through to P4F block+4 (emit_p3) so args AND
    # chain-tail land at a consistent shallower indent.
    p2_segment_wrapped = [False]

    def emit_p2() -> None:
        p2_segment_wrapped[0] = False

        def emit_seg_track_wrap(seg: Node) -> None:
            before = emitter.line_count
            name_node = seg.child_by_field_name("name")
            name_text = (
                _node_source_text(source, name_node)
                if name_node is not None
                else ""
            )
            args_emit_column = emitter.column + len(name_text)
            emit_segment(seg)
            if emitter.line_count > before:
                # Newlines introduced. Only flag as
                # wrap-engine-driven (worth backing off) when
                # the args aren't legitimately multi-line in
                # source (lambda body / text block / developer-
                # authored source-preserved layout). Reuses the
                # same discriminator emit_p1 uses so P2's
                # backoff decision matches P1's newline-based
                # rejection.
                legit = _segment_emit_is_legitimately_multi_line(
                    seg, args_emit_column
                )
                if not legit:
                    p2_segment_wrapped[0] = True

        if head is not None:
            _emit_node(emitter, source, head)
            first_dot_col = emitter.column
            emitter.write(".")
            emit_seg_track_wrap(segments[0])
            wrap_from = 1
        else:
            emit_seg_track_wrap(segments[0])
            first_dot_col = emitter.column
            emitter.write(".")
            emit_seg_track_wrap(segments[1])
            wrap_from = 2
        for seg in segments[wrap_from:]:
            emitter.newline()
            emitter.write(" " * first_dot_col)
            emitter.write(".")
            emit_seg_track_wrap(seg)

    # 0.6.0 P3F/P2C — outer-parenthesized-expression chain
    # cascade. When the entire method chain is wrapped in a
    # `parenthesized_expression` (grouping paren, e.g.
    # `(SomeFactory.newBuilder(args).chain1().chain2())`),
    # the chain-tail segments align at `paren_expr_col + 4`
    # per Q-CHAIN-1 (= "col of enclosing `(` + 5",
    # consistent with the enum/class-header wrap convention
    # used in 0.5.3).
    #
    # Shape by receiver kind:
    #   - Factory / instance (head is an identifier or field
    #     access): head + `.` + segments[0] stays on line 1;
    #     segments[1:] each on their own continuation line
    #     at `paren_expr_col + 4`.
    #   - Constructor (head is `object_creation_expression`):
    #     head alone on line 1; ALL segments break to
    #     continuation lines at `paren_expr_col + 4`. This
    #     matches the P2C example in the scope doc (all
    #     chain methods on their own line).
    #
    # Q-CHAIN-4 backoff also applies: if any segment's emit
    # in P3F introduces mid-args wrap, reject P3F even if
    # widths fit; fall through to P4F (block+4).
    p3f_segment_wrapped = [False]

    def emit_p3f_paren_indent() -> None:
        # 0.6.0 P3F/P2C outer-parenthesized chain candidate.
        # Requires `paren_expr_col` set by an enclosing
        # `_emit_parenthesized_expression`. Called after the
        # cascade dispatcher checks `emitter.paren_expr_col
        # is not None`.
        assert emitter.paren_expr_col is not None, (
            "emit_p3f_paren_indent requires paren_expr_col set; "
            "call site gates on this."
        )
        p3f_segment_wrapped[0] = False
        tail_col = emitter.paren_expr_col + 4

        def emit_seg_track_wrap(seg: Node) -> None:
            before = emitter.line_count
            emit_segment(seg)
            if emitter.line_count > before:
                p3f_segment_wrapped[0] = True

        is_constructor = (
            head is not None
            and head.type == "object_creation_expression"
        )
        if head is not None:
            _emit_node(emitter, source, head)
            if is_constructor:
                # Constructor P2C: all chain segments break to
                # continuation lines. Line 1 is just `head`
                # (= `new SomeClass(args)`).
                wrap_from = 0
            else:
                # Factory / instance P3F: segments[0] stays on
                # line 1 with head; segments[1:] break.
                emitter.write(".")
                emit_seg_track_wrap(segments[0])
                wrap_from = 1
        else:
            # Headless chain — treat first segment as
            # "receiver-equivalent"; break rest.
            emit_seg_track_wrap(segments[0])
            wrap_from = 1
        for seg in segments[wrap_from:]:
            emitter.newline()
            emitter.write(" " * tail_col)
            emitter.write(".")
            emit_seg_track_wrap(seg)

    def emit_p3() -> None:
        if head is not None:
            _emit_node(emitter, source, head)
            wrap_from = 0
        else:
            emit_segment(segments[0])
            wrap_from = 1
        for seg in segments[wrap_from:]:
            emitter.newline()
            emitter.write(" " * p3_col)
            emitter.write(".")
            emit_segment(seg)

    def emit_p2_greedy_dot_aligned() -> None:
        # 0.5.0 item 2b: same-method method-chain greedy.
        # Pack as many `.METHOD(args)` segments per continuation
        # line as fit. Continuation column = first_dot_col
        # (same dot-alignment as P2 dot-aligned). Used only when
        # all segments call the same method name — chains like
        # `sb.append(a).append(b).append(c)` where each segment
        # is semantically equivalent and benefit from horizontal
        # density.
        #
        # Mixed-name chains (`.builder().setReader().get()`)
        # keep P2 one-per-line — each call is distinct and the
        # vertical layout aids readability.
        #
        # Item 8 invariant: after each segment emit, if the
        # segment's args wrapped multi-line (a nested arg list
        # that itself wrapped, e.g. `.method(longArg, longArg)`
        # going to P4), force a break before the next segment —
        # otherwise the trailing segment would land at the same
        # column as the wrapped arg's tail, stranding the chain.
        # `start_line_count` is captured BEFORE the first
        # segment emit so a multi-row first segment (its arg
        # list itself wrapping, e.g. `sb.append(longExpression
        # ThatWraps).append(b)`) also forces the SECOND
        # segment to break — same anti-stranding behavior as
        # the per-segment check inside the loop below.
        # Call site at line ~7430 gates on `head is not None`, so
        # the headless branch is unreachable here. Asserting
        # rather than handling keeps the contract explicit: if
        # the gate is ever relaxed, this assert surfaces the
        # need to revisit `first_dot_col`'s capture point (it
        # must be the column of the FIRST `.` in the chain, not
        # the column after the second segment's args).
        assert head is not None, (
            "emit_p2_greedy_dot_aligned requires a non-None "
            "head; call site gates on this."
        )
        start_line_count = emitter.line_count
        _emit_node(emitter, source, head)
        first_dot_col = emitter.column
        emitter.write(".")
        emit_segment(segments[0])
        wrap_from = 1
        prev_segment_multi_row = (
            emitter.line_count > start_line_count
        )
        for seg in segments[wrap_from:]:
            if prev_segment_multi_row:
                # Item 8: previous segment's args wrapped — force
                # break before this segment.
                emitter.newline()
                emitter.write(" " * first_dot_col)
                emitter.write(".")
                seg_start_line = emitter.line_count
                emit_segment(seg)
            else:
                pack_saved = emitter.snapshot()
                emitter.write(".")
                seg_start_line = emitter.line_count
                emit_segment(seg)
                pack_ok = (
                    emitter.last_lines_max_width(pack_saved[0])
                    <= effective_max
                    and emitter.line_count == seg_start_line
                )
                if not pack_ok:
                    emitter.restore(pack_saved)
                    emitter.newline()
                    emitter.write(" " * first_dot_col)
                    emitter.write(".")
                    seg_start_line = emitter.line_count
                    emit_segment(seg)
            prev_segment_multi_row = (
                emitter.line_count > seg_start_line
            )

    # Manual P1 speculation with per-segment newline detection.
    # P1 is "all segments stay on whichever line the head
    # finished on"; if a nested arg-list emit wraps mid-segment
    # (e.g. `.method(arg)` wraps to put the arg on its own
    # line), the chain has effectively broken even though the
    # surrounding widths may still satisfy a simple width
    # check. The `p1_segment_break_seen` flag rejects exactly
    # that case while still letting the head itself wrap when
    # it's legitimately multi-line (e.g. a head that is itself
    # another chain). P2 / P3 commit by width — their newlines
    # are deliberate.
    effective_max = _MAX_LINE - emitter.tail_reserve
    saved = emitter.snapshot()
    emit_p1()
    p1_fits = (
        emitter.last_lines_max_width(saved[0]) <= effective_max
        and not p1_segment_break_seen[0]
    )
    if p1_fits:
        return
    emitter.restore(saved)

    # 0.5.0 item 2b: try emit_p2_greedy_dot_aligned BEFORE the
    # standard P2 (one-per-line dot-aligned) when all chain
    # segments call the same method name AND the chain has an
    # explicit receiver. Same-method chains
    # (`sb.append(a).append(b)…`) benefit from horizontal
    # density; mixed-name chains (`.builder().setReader().get()`)
    # keep the one-per-line shape via P2. Headless same-name
    # chains (`getX().getX().getX()` — extremely unusual) also
    # keep one-per-line because the canonical motivation
    # (builder pattern with named receiver) doesn't apply.
    if (
        not chain_is_sole_arg
        and head is not None
        and _chain_segments_share_method_name(source, segments)
    ):
        greedy_saved = emitter.snapshot()
        emit_p2_greedy_dot_aligned()
        if emitter.last_lines_max_width(greedy_saved[0]) <= effective_max:
            return
        emitter.restore(greedy_saved)

    # 0.7.0 removed the 0.6.0 "P1F" factory-chain tier, which sat
    # here and packed receiver + factory + FIRST CHAIN onto line 1
    # (`Factory.make(a).step1(b)` with `.step2(c)` aligned under
    # `.step1`'s dot) whenever the receiver was a PascalCase
    # identifier and the chain had 3+ segments.
    #
    # That violates the pack-all-or-nothing principle: the
    # all-on-one-line shape is only available when the WHOLE chain
    # fits. Once it does not, the correct break point is the first
    # chain continuation dot — not "as many segments as happen to
    # fit". P1F produced a line whose content was determined purely
    # by where 80 characters ran out, which is also why the same
    # idiom rendered two ways depending on whether segment 1 fit:
    #
    #     this.env = SzCoreEnvironment.newBuilder().instanceName(x)
    #                                              .settings(y)
    #
    # rather than the canonical form the source already had:
    #
    #     this.env = SzCoreEnvironment.newBuilder()
    #                                 .instanceName(x)
    #                                 .settings(y)
    #
    # Falling straight through to P2F (`emit_p2`: receiver +
    # factory on line 1, every remaining segment one per line at
    # the first dot's column) restores that.

    # 0.6.0 P3F/P2C — outer-parenthesized-expression chain
    # cascade. Fires when the whole chain is wrapped in a
    # grouping paren (paren_expr_col set). Tried BEFORE the
    # standard P2 (block+4-agnostic dot-align) because the
    # paren-indent shape is preferred when we're inside a
    # grouping paren — Q-CHAIN-5 confirms outer-paren-indent
    # + 4 for the chain-tail. Falls through to P2 if the
    # paren-indent shape overflows or Q-CHAIN-4 backoff
    # triggers.
    if (
        not chain_is_sole_arg
        and emitter.paren_expr_col is not None
    ):
        p3f_saved = emitter.snapshot()
        emit_p3f_paren_indent()
        p3f_fits = (
            emitter.last_lines_max_width(p3f_saved[0])
            <= effective_max
            and not p3f_segment_wrapped[0]
        )
        if p3f_fits:
            return
        emitter.restore(p3f_saved)

    p2_saved = emitter.snapshot()
    if not chain_is_sole_arg:
        emit_p2()
        p2_fits = (
            emitter.last_lines_max_width(p2_saved[0])
            <= effective_max
            and not p2_segment_wrapped[0]
        )
        if p2_fits:
            return
        emitter.restore(p2_saved)
    emit_p3()
    # Method-chain wrap site advisory uses the first segment
    # (or head, if present) as the source position — the
    # earliest token of the chain is the most useful jump
    # target for the developer fixing an overflow.
    advisory_anchor = head if head is not None else segments[0]
    _fire_wrap_overflow_advisory(
        emitter, advisory_anchor, p2_saved[0], "method chain"
    )


def _emit_method_invocation(
    emitter: Emitter, source: bytes, node: Node
) -> None:
    """Emit `[OBJECT.]METHOD(ARGS)` with chain-wrap support.

    Grammar fields:
        - `object` (optional): the receiver expression
        - `name`: the method identifier
        - `arguments`: the `argument_list` node
        - `type_arguments` (optional): explicit `<T>` type
          witness — refused for now (lands with the generic-
          type-parameter phase)

    When this node is the root of a 2+ segment method chain
    (`a.b().c().d()` and friends), dispatches to
    `_emit_method_chain_wrapped` for P1/P2/P3 wrap selection.
    Single-segment calls (just `obj.method(args)` with no
    further chaining) emit on one line; the surrounding
    expression's wrap engine handles overflow if the call
    itself is too long.
    """
    if node.child_by_field_name("type_arguments") is not None:
        raise NotImplementedError(
            "method_invocation with explicit type arguments "
            "(`obj.<Type>method(...)`) is not yet supported."
        )
    name_node = node.child_by_field_name("name")
    arguments_node = node.child_by_field_name("arguments")
    if name_node is None or arguments_node is None:
        raise NotImplementedError(
            "method_invocation missing 'name' or 'arguments' — "
            "grammar shape unexpected."
        )

    # Chain-wrap selection. Only run from the chain root; inner
    # segments are emitted directly by `_emit_method_chain_wrapped`
    # and never reach `_emit_node` on the chain root's path. The
    # defensive `_is_method_chain_inner` check guards against any
    # stray dispatch path that would otherwise double-emit.
    if not _is_method_chain_inner(node):
        head, segments = _collect_method_chain(node)
        if len(segments) >= 2:
            _emit_method_chain_wrapped(
                emitter, source, head, segments,
            )
            return

    # Simple single-call emission. When a receiver is
    # present, bump tail_reserve while emitting it so that
    # any wrap engine running inside the receiver (chain
    # wrap on a sub-expression, a binary expression, etc.)
    # accounts for the trailing `.NAME(ARGS)` it can't see.
    # The reserve is computed from the source-text length of
    # name + arguments — for single-line args this matches
    # the rendered length; for multi-line args we cap at the
    # first source line so a long multi-line literal doesn't
    # force overly-aggressive wrapping upstream.
    object_node = node.child_by_field_name("object")
    if object_node is not None:
        name_text = _node_source_text(source, name_node)
        args_text = _node_source_text(source, arguments_node)
        args_first_line = (
            args_text.split("\n", 1)[0]
        )
        trailing = 1 + len(name_text) + len(args_first_line)
        prev_reserve = emitter.set_tail_reserve(
            emitter.tail_reserve + trailing
        )
        try:
            _emit_node(emitter, source, object_node)
        finally:
            emitter.set_tail_reserve(prev_reserve)
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


def _emit_variable_declarator_with_array_rhs(
    emitter: Emitter,
    source: bytes,
    node: Node,
    value: Node,
    cascade_start: int,
    effective_max: int,
) -> None:
    """Cascade for `Type NAME = <array-literal>` variable_declarator.

    Per docs/java-coding-standards.md §"Array initializers":

      - Priority 1: `Type NAME = { … };` all on one line.
      - Priority 2: break BEFORE the `=`, array literal fits
        on one continuation line at block+4. Applies ONLY when
        the RHS is a bare `array_initializer` — SKIPPED for
        `new Type[] { … }` because moving the whole
        `= new Type[] {` prefix onto a continuation line eats
        too much horizontal budget for elements to fit.
      - Priority 3+: no break-at-`=`, array's own cascade
        emits multi-line greedy (P3) or one-per-line (P4).

    The Priority 1 and Priority 2 attempts set
    `emitter._array_init_inline_only` so the nested array
    emits its own P1 inline shape rather than committing to a
    multi-line P3/P4 that we would only have discarded.

    The `+ 1` in the width checks accounts for the trailing
    `;` the parent field_declaration / local_variable_declaration
    writes after this emitter returns.
    """
    is_new_type_array = _rhs_is_new_type_array(value)
    effective_max_with_semi = _MAX_LINE - emitter.tail_reserve - 1

    # Priority 1: inline all — force array inline. The `+ 1` in
    # `effective_max_with_semi` accounts for the trailing `;`
    # the parent field_declaration / local_variable_declaration
    # writes after this emitter returns; `tail_reserve` accounts
    # for any additional trailing chars the outer context
    # reserved (e.g. for-loop init tail). The width check uses
    # `last_lines_max_width` so a hypothetically-oversized LHS
    # line (long type + name) is caught even though the LHS
    # was emitted before the speculation snapshot.
    saved = emitter.snapshot()
    prev_flag = emitter._array_init_inline_only
    emitter._array_init_inline_only = True
    try:
        emitter.write(" = ")
        _emit_node(emitter, source, value)
    finally:
        emitter._array_init_inline_only = prev_flag
    p1_fits = (
        emitter.line_count == saved[0]
        and emitter.last_lines_max_width(saved[0])
        <= effective_max_with_semi
    )
    if p1_fits:
        return
    emitter.restore(saved)

    # Priority 2: break-at-`=` with array inline. Skipped for
    # `new Type[]` per spec. The `last_lines_max_width` check
    # verifies BOTH lines fit — the LHS line (already committed
    # before the p2_saved snapshot) is above `saved[0]` and the
    # array-continuation line is `saved[0] + 1`.
    if not is_new_type_array:
        p2_saved = emitter.snapshot()
        emitter.newline()
        emitter.push_indent()
        emitter.write_indent()
        emitter.write("= ")
        emitter._array_init_inline_only = True
        try:
            _emit_node(emitter, source, value)
        finally:
            emitter._array_init_inline_only = prev_flag
        p2_fits = (
            emitter.line_count == p2_saved[0] + 1
            and emitter.last_lines_max_width(saved[0])
            <= effective_max_with_semi
        )
        if p2_fits:
            emitter.pop_indent()
            return
        emitter.restore(p2_saved)

    # Priority 3+: no break-at-`=`, dispatch and let the array's
    # own cascade choose P3 or P4.
    emitter.write(" = ")
    _emit_node(emitter, source, value)
    _fire_wrap_overflow_advisory(
        emitter, node, cascade_start, "variable declarator"
    )


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
    the parent node (field_declaration or
    local_variable_declaration) has already written the
    indent + modifiers + type, so the emitter's column
    reflects the source's "statement start + leading text".
    """
    name = node.child_by_field_name("name")
    value = node.child_by_field_name("value")
    if name is None:
        raise NotImplementedError(
            "variable_declarator missing 'name' field — grammar "
            "shape unexpected."
        )
    _emit_node(emitter, source, name)
    # C-style array dimensions placed AFTER the variable name
    # (`Class<?> params[] = ...`, `int x[][] = ...`). Java allows
    # this as an alternative to declaring dimensions on the type
    # itself. The grammar exposes them as a `dimensions` named
    # child of `variable_declarator`. Emitting them after the
    # name preserves the source's array-typing.
    for c in node.named_children:
        if c.type == "dimensions":
            _emit_node(emitter, source, c)
            break
    if value is None:
        return
    cascade_start = emitter.line_count
    # Mid-statement comment preservation: when
    # line_comment / block_comment "extras" sit between the
    # `=` token and the value RHS (e.g. javadoc
    # `// @highlight region="..."` snippet markers on
    # assignment-with-text-block), the wrap engine has no way
    # to represent comments inline with operator placement,
    # so source-preserve the entire `= ...` region verbatim.
    # This matches the treatment of comments inside argument
    # lists (`_arg_list_takes_source_preserve_path`). Without
    # this guard the comments are silently dropped
    # since `_emit_node(value)` walks only the value subtree
    # and never visits the extra comment children.
    equals_token = None
    for child in node.children:
        if child.type == "=":
            equals_token = child
            break
    if equals_token is not None:
        mid_comments = [
            c for c in node.children
            if c.type in ("line_comment", "block_comment")
            and c.start_byte > equals_token.start_byte
            and c.start_byte < value.start_byte
        ]
        if mid_comments:
            # Emit `= <comments-and-rhs-verbatim-from-source>`.
            # Verbatim preserves the developer's whitespace
            # between `=`, the comments, and the value — the
            # only safe transform when comment placement
            # carries semantic meaning (snippet markers).
            emitter.write(" ")
            verbatim = source[
                equals_token.start_byte:value.end_byte
            ].decode("utf-8")
            emitter.write_raw_lines(
                verbatim, strip_trailing_ws=True
            )
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
    effective_max = _MAX_LINE - emitter.tail_reserve

    # 0.6.0: array-literal RHS gets its own cascade per the
    # spec's "Array initializers" section. Priority 2 is
    # skipped for `new Type[] { … }` (moving `= new Type[] {`
    # onto a continuation line eats too much horizontal
    # budget); the bare `Type x = { … }` form keeps Priority 2.
    if _rhs_has_array_literal(value):
        _emit_variable_declarator_with_array_rhs(
            emitter, source, node, value, cascade_start,
            effective_max,
        )
        return

    # Step 1: try inline single-line via speculative emission.
    # If the value's emission stays on one line AND the line
    # fits within the budget (counting the trailing `;` the
    # field/local-variable declaration will write), commit.
    saved = emitter.snapshot()
    emitter.write(" = ")
    _emit_node(emitter, source, value)
    inline_fits = (
        emitter.line_count == saved[0]
        and emitter.column + 1 <= effective_max
    )
    if inline_fits:
        return
    emitter.restore(saved)

    # Step 2: try break-at-`=` with single-line value.
    # Continuation indent is one level deeper than the
    # surrounding statement.
    p2_saved = emitter.snapshot()
    emitter.newline()
    emitter.push_indent()
    emitter.write_indent()
    emitter.write("= ")
    _emit_node(emitter, source, value)
    p2_fits = (
        emitter.line_count == p2_saved[0] + 1
        and emitter.column + 1 <= effective_max
    )
    if p2_fits:
        emitter.pop_indent()
        return
    # No explicit pop_indent on the failing path —
    # `restore()` resets `self._indent` to the snapshot's
    # captured value, which already undoes the push above.
    emitter.restore(p2_saved)

    # Step 3 (and the multi-line-value path): emit inline and
    # let the value handle its own wrap. The overflow check
    # runs regardless of `value_is_multiline` — if the value's
    # final rendered form pushes any line past 80 chars,
    # backtrack to the break-at-`=` shape. (An earlier version
    # short-circuited on `value_is_multiline` without the
    # overflow check, but the fuzz harness surfaced a non-
    # idempotent case where the source had a multi-line ternary
    # value that the formatter collapsed to a long single line:
    # the first pass kept the long line, the second pass saw
    # the now-single-line value and correctly broke at `=`.)
    saved = emitter.snapshot()
    emitter.write(" = ")
    prev_escaped = emitter._anchor_escaped
    emitter._anchor_escaped = False
    _emit_node(emitter, source, value)
    # 0.7.0: an inline RHS whose emission left a line starting LEFT of
    # where the value began has orphaned part of itself — typically a
    # chain whose tail could not fit at the deep column the inline
    # shape forced, so the tail's own arguments escaped to a
    # block-relative anchor:
    #
    #     String nativeResult = engine.getNativeApi()
    #                                 .getEntityByRecordId(
    #                     dataSourceCode, recordID);
    #
    # Width alone cannot detect this — every line above is under 80,
    # so the overflow test below passes and Step 3 commits. Treating it
    # like an overflow sends it to the break-at-`=` backtrack, where
    # the chain starts shallow enough for its tail to fit:
    #
    #     String nativeResult
    #         = engine.getNativeApi()
    #                 .getEntityByRecordId(dataSourceCode, recordID);
    #
    # Deliberately a REMEDY, not a preference: a wrapped chain that
    # orphans nothing keeps the inline shape, because breaking at `=`
    # would cost a line for no benefit.
    # Geometry cannot answer this: the legitimate chain-P3 ladder
    # (segments at block+4) also places rows left of the value column,
    # so a column test cannot tell a clean ladder from a real orphan.
    # The flag is set at the one place the escape actually happens.
    inline_orphan = emitter._anchor_escaped
    # `+ 1` accounts for the trailing `;` the parent
    # field_declaration / local_variable_declaration writes
    # after this emitter returns; `+ tail_reserve` accounts
    # for any additional trailing chars the outer context
    # reserved (e.g. a `for` header reserves 2 for the header
    # remainder while emitting the init clause — a
    # local_variable_declaration as for-init runs with
    # tail_reserve = 2, so this check must add both). Steps 1
    # and 2 above compute the same budget via `<=
    # effective_max`; this check keeps Step 3 consistent.
    inline_overflow = (
        emitter.last_lines_max_width(saved[0]) > _MAX_LINE
        or emitter.column + 1 + emitter.tail_reserve > _MAX_LINE
    )
    if not inline_overflow and not inline_orphan:
        # Hand back the flag as we found it. The reset above is a
        # local measurement device — it exists so `inline_orphan`
        # reflects THIS value's emission — but an enclosing
        # construct may already have recorded an escape of its own,
        # and a declarator nested in this one's value (inside a
        # lambda block or anonymous-class body) would otherwise
        # clear that evidence on the way out. The outer construct
        # then reads False and commits the very orphaned shape the
        # flag exists to prevent.
        #
        # Only this exit needs it: the backtrack path below calls
        # `emitter.restore(saved)`, and `saved` was snapshotted
        # before the reset, so it restores the incoming value and
        # then accumulates the re-emission's own escapes. Nothing
        # is OR-ed in here because reaching this branch requires
        # `inline_orphan` to be False.
        emitter._anchor_escaped = prev_escaped
        _fire_wrap_overflow_advisory(
            emitter, node, cascade_start, "variable declarator"
        )
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
    # Spec C1 emit-and-warn: the break-at-`=` shape may still
    # overflow when the value is a single atomic token
    # (long identifier / literal). Fire the advisory so
    # adopters get a first-class signal to hand-split the
    # value, matching every other C1 emit-and-warn site.
    _fire_wrap_overflow_advisory(
        emitter, node, cascade_start, "variable declarator"
    )


# Maps tree-sitter-java node type to its emitter. Adding a new
# emitter is purely a matter of registering it here. The
# dispatcher's `NotImplementedError` on an unknown type is the
# formatter's way of saying "this construct isn't yet supported"
# — that's preferable to silently passing source text through
# (which would propagate non-spec-compliant input).
_NODE_EMITTERS: Final[dict[str, EmitterFn]] = {
    "receiver_parameter": _emit_receiver_parameter,
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
    "annotation_type_declaration": _emit_annotation_type_declaration,
    "annotation_type_element_declaration": (
        _emit_annotation_type_element_declaration
    ),
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


def format_source(
    source: bytes,
    warnings_out: list[FormatterWarning] | None = None,
) -> bytes:
    """Format a Java source byte string per the project standards.

    Handles every Java construct exercised by the 83 fixture
    pairs and every file in the consumer codebases pre-flight
    diff exercise — including classes, interfaces, enums,
    records, methods, constructors, fields, type parameters,
    throws clauses, annotations, generics, wildcards, type-use
    annotations, anonymous classes, sealed/permits, switch
    statements and expressions (arrow form), pattern matching,
    multi-catch, try-with-resources, lambdas, method
    references, ternaries, binary/unary/parenthesized
    expressions, the full statement set (`if`/`for`/`while`/
    `do`/`try`/`switch`/`return`/`throw`/`break`/`continue`/
    labeled statements / assignments), and javadoc reflow.

    Constructs deliberately out-of-scope for 0.3.0: see the
    module docstring's "Coverage" section. Anything outside the
    supported subset raises `NotImplementedError` from the
    dispatcher (the explicit "this construct isn't supported
    yet" signal).

    On syntactically invalid input, raises `ValueError` rather
    than emitting potentially garbled output — protects
    `--write` mode from silently corrupting files.
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
    if warnings_out is not None:
        # Deduplicate by source position — speculative emit cascades
        # can revisit the same arg list under different
        # `indent_level` values, emitting the same advisory
        # multiple times for one node. The developer only needs
        # to see each source location once.
        seen: set[tuple[int, int]] = set()
        for warning in emitter.warnings:
            key = (warning.line, warning.column)
            if key in seen:
                continue
            seen.add(key)
            warnings_out.append(warning)
    return emitter.finish()


def print_warnings(
    path: str | Path,
    warnings: list[FormatterWarning],
    *,
    stream: TextIO | None = None,
) -> None:
    """Print `FormatterWarning` records to `stream` (default
    `sys.stderr`) in `path:line:col: WARNING: message` format.

    Shared helper used by both `format_java.py --format` and
    `format_file.py` so the two CLIs render advisories
    identically. Keeping the print contract in one place
    means a future change (e.g. machine-parseable JSON output
    behind a flag) lands in one site, not two.
    """
    out = sys.stderr if stream is None else stream
    for warning in warnings:
        print(
            f"{path}:{warning.line}:{warning.column}: "
            f"WARNING: {warning.message}",
            file=out,
        )


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
        warnings: list[FormatterWarning] = []
        try:
            formatted = format_source(source, warnings_out=warnings)
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
        print_warnings(path, warnings)
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
