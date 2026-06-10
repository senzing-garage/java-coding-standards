"""Fuzz the formatter against a real-world Java corpus.

For every .java file in the corpus this verifies:

1. **Round-trip AST equivalence** — the formatter's output
   re-parses to a CST with the same named-node-type sequence
   as the input (modulo whitespace / comment differences).
   Catches emitter bugs that would silently change Java
   semantics: a misplaced `static`, a dropped argument, etc.

2. **Idempotency** — formatting the formatter's output
   produces byte-identical text. Catches non-stable emitters
   (every run advances output by a character) and oscillating
   pairs of rules.

3. **Refusal cleanliness** — when the formatter declines a
   construct it raises a typed `NotImplementedError` with a
   diagnostic message; never a traceback into formatter
   internals, never a silently-dropped subtree.

The default corpus is `senzing-commons-java/src/`, ~106 files.
Set `SENZING_JAVA_FUZZ_CORPUS` to a different absolute path
to point this at a larger external corpus (e.g. OpenJDK
`java.base` source, ~3000 files). The test is `skip`-marked
when no corpus is found so a fresh clone doesn't fail CI
before any consumer is configured.

The error-recovery property (broken Java exits cleanly with
non-zero status, never produces garbled output) is covered
by `test_parse_error_exits_nonzero` in `test_format_file.py`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Add tooling/scripts/ to path so we can import format_java.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import format_java


def _resolve_corpus() -> Path | None:
    """Locate a Java corpus to fuzz against.

    Precedence:
        1. `SENZING_JAVA_FUZZ_CORPUS` env var (must exist).
        2. `senzing-commons-java/src/` two levels up from this
           submodule — the consumer project's source tree, used
           by default during development.
    """
    env = os.environ.get("SENZING_JAVA_FUZZ_CORPUS")
    if env:
        p = Path(env)
        return p if p.is_dir() else None
    # The submodule lives at `<consumer>/.java-coding-standards/`;
    # the consumer's source is at `<consumer>/src/`.
    submodule = Path(__file__).resolve()
    # tests/ → scripts/ → tooling/ → submodule root → consumer root
    consumer_root = submodule.parents[4]
    src = consumer_root / "src"
    return src if src.is_dir() else None


def _collect_java_files(corpus: Path) -> list[Path]:
    """Recursively collect .java files; deterministically sorted."""
    return sorted(corpus.rglob("*.java"))


def _named_node_signature(tree) -> tuple[str, ...]:
    """Walk the parse tree in preorder, emitting the `.type` of
    every NAMED node. Excludes anonymous tokens (keywords,
    punctuation) — those reflect surface syntax differences
    that the formatter is allowed to normalize (e.g. blank-line
    counts). The named-node sequence captures structural
    equivalence at the AST level.

    Comments and whitespace-only differences don't appear here
    because tree-sitter exposes comments as their own named
    nodes (`block_comment` / `line_comment`); we exclude those
    too since the formatter is allowed to re-indent and reflow
    comment content.
    """
    out: list[str] = []
    # Skip nodes whose presence depends on surface syntax the
    # formatter is allowed to normalize:
    #   - block_comment / line_comment: comments themselves are
    #     subject to javadoc reflow.
    #   - enum_body_declarations: the grammar emits this wrapper
    #     when an enum has the `;` separator between its
    #     constants and any extra members. Per spec A2 the
    #     formatter ALWAYS emits the trailing `;` after the last
    #     enum constant, so source-without-`;` becomes
    #     output-with-`;` and the parser reorganizes the AST
    #     around the new separator. That's a spec-mandated
    #     normalization, not a semantic change.
    #   - block: the spec's Tier-1/Tier-2/Tier-3 short-circuit
    #     conditional rules allow the formatter to add or remove
    #     braces (`{ ... }`) around a single short-circuit
    #     statement based on width. `if (x) return null;` and
    #     `if (x) { return null; }` are semantically equivalent;
    #     the choice between them is a formatting decision, not
    #     a meaning change. Excluding `block` from the
    #     comparison treats both shapes as equivalent.
    skip = (
        "block_comment",
        "line_comment",
        "enum_body_declarations",
        "block",
    )

    def visit(node) -> None:
        if node.is_named and node.type not in skip:
            out.append(node.type)
        for c in node.children:
            visit(c)

    visit(tree.root_node)
    return tuple(out)


_CORPUS = _resolve_corpus()
_FILES = _collect_java_files(_CORPUS) if _CORPUS else []


@pytest.mark.skipif(
    _CORPUS is None,
    reason=(
        "No Java corpus found. Set SENZING_JAVA_FUZZ_CORPUS to "
        "the absolute path of a Java source tree to enable."
    ),
)
@pytest.mark.parametrize(
    "java_file",
    _FILES,
    ids=[str(p.relative_to(_CORPUS)) for p in _FILES]
    if _CORPUS
    else [],
)
def test_round_trip_ast_equivalence(java_file: Path) -> None:
    """Formatter output re-parses to the same named-node sequence
    as the input. Refusals are reported as `skip` so they don't
    fail the gate.
    """
    source = java_file.read_bytes()
    try:
        formatted = format_java.format_source(source)
    except NotImplementedError as exc:
        pytest.skip(f"refused: {exc}")
    except ValueError as exc:
        # Parse error on input — skip; the input is bad, not the
        # formatter.
        pytest.skip(f"input parse error: {exc}")

    src_tree = format_java.parse_source(source)
    out_tree = format_java.parse_source(formatted)
    assert not format_java.has_parse_errors(out_tree), (
        "formatter output failed to re-parse"
    )
    assert _named_node_signature(src_tree) == \
        _named_node_signature(out_tree), (
            "formatter output's named-node sequence differs from "
            "the input — the emitter changed semantics."
        )


@pytest.mark.parametrize(
    "broken_source",
    [
        # Each input is syntactically invalid Java — `format_source`
        # must raise `ValueError` (parse error) cleanly rather
        # than crash with a Python traceback or, worse, silently
        # produce garbled output that would overwrite the source
        # in `--write` mode.
        pytest.param(
            b"public class Broken { ; ; ; nope",
            id="unterminated-class-body",
        ),
        pytest.param(
            b"public class A { void m() { if ( {} } }",
            id="malformed-if-condition",
        ),
        pytest.param(
            b"class A { int x = ; }",
            id="missing-rhs",
        ),
        pytest.param(
            b"class A { ((((((((( }",
            id="unbalanced-parens",
        ),
        pytest.param(
            b"",
            id="empty-input",
        ),
        pytest.param(
            b"this is not java at all",
            id="not-java",
        ),
    ],
)
def test_broken_input_raises_value_error(
    broken_source: bytes,
) -> None:
    """The formatter must REFUSE syntactically invalid input
    via a typed exception — never produce output that could
    silently overwrite a user's file in `--write` mode.

    Empty input is the lone exception: an empty Java file is
    LEGAL (tree-sitter parses it to an empty program), so it
    formats to `b""` cleanly.
    """
    if not broken_source.strip():
        # Empty file is valid Java.
        assert format_java.format_source(broken_source) == b""
        return
    with pytest.raises(ValueError):
        format_java.format_source(broken_source)


# Known-non-idempotent file patterns. Each entry is a relative-
# to-corpus path fragment. Files whose path CONTAINS any of
# these strings are marked `xfail` for the idempotency check —
# the formatter produces different output on the second pass
# due to a known limitation in method-chain wrap awareness
# (the formatter currently uses P4-style next-line single-indent
# for overflowed call args inside a chain, which can leave the
# enclosing assignment in a state where the second pass picks
# a different inline-vs-break-at-`=` shape).
#
# This list intentionally lives in the test rather than the
# formatter so it documents WHICH consumer files exercise the
# known issue, and so the day the underlying limitation is
# fixed the corresponding entry can be deleted and the test
# automatically tightens.
_KNOWN_NON_IDEMPOTENT = (
    # Deeply-chained method-call assignment where the chain
    # wraps in a way that makes the inline vs break-at-`=`
    # decision unstable between passes.
    "api/services/BulkDataSupport.java",
)


@pytest.mark.skipif(
    _CORPUS is None,
    reason=(
        "No Java corpus found. Set SENZING_JAVA_FUZZ_CORPUS to "
        "enable."
    ),
)
@pytest.mark.parametrize(
    "java_file",
    _FILES,
    ids=[str(p.relative_to(_CORPUS)) for p in _FILES]
    if _CORPUS
    else [],
)
def test_idempotent(java_file: Path) -> None:
    """`format(format(src)) == format(src)`. Refusals → skip."""
    rel = str(java_file.relative_to(_CORPUS))
    if any(pat in rel for pat in _KNOWN_NON_IDEMPOTENT):
        pytest.xfail(
            "known non-idempotent file (method-chain wrap "
            "interaction; see _KNOWN_NON_IDEMPOTENT)"
        )

    source = java_file.read_bytes()
    try:
        first = format_java.format_source(source)
    except (NotImplementedError, ValueError) as exc:
        pytest.skip(f"first pass: {exc}")

    try:
        second = format_java.format_source(first)
    except (NotImplementedError, ValueError) as exc:
        pytest.fail(
            f"second pass on already-formatted output raised: "
            f"{type(exc).__name__}: {exc}"
        )
    assert first == second, (
        "formatter is not idempotent — second pass differs from "
        "the first."
    )
