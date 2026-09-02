"""Smoke tests for the canonical AST-based Java formatter scaffolding.

Phase 2a only verifies the parser/grammar wiring. Emission tests
arrive with subsequent phases.
"""

from __future__ import annotations

import dataclasses
import importlib.metadata
import re
import subprocess
import sys
from pathlib import Path

import pytest

import format_java


# ---------------------------------------------------------------------------
# Version-pin consistency
# ---------------------------------------------------------------------------


def _read_runtime_requirements_pins() -> dict[str, str]:
    """Parse `tooling/scripts/requirements.txt` for `name==version`.

    The check ensures the in-source `GRAMMAR_VERSION` constants do
    not drift away from the pip-installed versions.
    """
    req = Path(__file__).resolve().parent.parent / "requirements.txt"
    pins: dict[str, str] = {}
    pattern = re.compile(r"^([a-zA-Z0-9_.\-]+)==([^\s;]+)")
    for line in req.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = pattern.match(stripped)
        if match:
            pins[match.group(1)] = match.group(2)
    return pins


class TestGrammarVersionPins:
    """Verify the in-source pins match `requirements.txt`."""

    def test_grammar_version_dict_keys(self) -> None:
        assert set(format_java.GRAMMAR_VERSION.keys()) == {
            "tree-sitter",
            "tree-sitter-java",
        }

    def test_grammar_version_values_match_requirements(self) -> None:
        pins = _read_runtime_requirements_pins()
        assert (
            pins["tree-sitter"]
            == format_java.GRAMMAR_VERSION["tree-sitter"]
        )
        assert (
            pins["tree-sitter-java"]
            == format_java.GRAMMAR_VERSION["tree-sitter-java"]
        )

    def test_installed_versions_match_pins(self) -> None:
        """The INSTALLED packages match the pins too.

        The two assertions above compare two files to each other
        and never consult the environment, so a stale virtualenv
        validates the whole suite against a binding the formatter
        is not calibrated for. That is not hypothetical: the 0.7.0
        review ran 704 passing tests with tree-sitter 0.25.2
        installed against a 0.26.0 pin.

        Determinism across machines is the stated reason these
        pins are tight, so the environment is exactly what needs
        checking. A failure here means `pip install -r
        tooling/scripts/requirements.txt`, not a code change.
        """
        for package, pinned in format_java.GRAMMAR_VERSION.items():
            installed = importlib.metadata.version(package)
            assert installed == pinned, (
                f"{package} {installed} is installed but the pin "
                f"is {pinned} — reinstall with `pip install -r "
                f"tooling/scripts/requirements.txt` so parses "
                f"match what the formatter is calibrated against."
            )


# ---------------------------------------------------------------------------
# Parser wiring
# ---------------------------------------------------------------------------


class TestParseSource:
    """Verify tree-sitter-java loads and parses Java byte strings."""

    def test_parse_empty_input(self) -> None:
        tree = format_java.parse_source(b"")
        assert tree.root_node.type == "program"
        assert not format_java.has_parse_errors(tree)

    def test_parse_simple_class(self) -> None:
        src = (
            b"public class Foo {\n"
            b"    public String getName() { return this.name; }\n"
            b"}\n"
        )
        tree = format_java.parse_source(src)
        assert tree.root_node.type == "program"
        assert not format_java.has_parse_errors(tree)
        children = [c.type for c in tree.root_node.children]
        assert "class_declaration" in children

    def test_parse_detects_syntax_errors(self) -> None:
        # Missing closing brace.
        src = b"public class Foo { public void run() {\n"
        tree = format_java.parse_source(src)
        assert format_java.has_parse_errors(tree)

    def test_parse_source_rejects_str(self) -> None:
        with pytest.raises(TypeError, match="requires bytes"):
            format_java.parse_source("public class Foo {}\n")


class TestParseFile:
    """Verify parse_file() loads a file from disk and parses it."""

    def test_parse_file_round_trip(self, tmp_path: Path) -> None:
        java = tmp_path / "Foo.java"
        java.write_text(
            "public class Foo\n"
            "{\n"
            "    public int x = 0;\n"
            "}\n",
            encoding="utf-8",
        )
        tree = format_java.parse_file(java)
        assert not format_java.has_parse_errors(tree)
        assert tree.root_node.type == "program"

    def test_parse_file_detects_syntax_errors(
        self, tmp_path: Path
    ) -> None:
        broken = tmp_path / "Broken.java"
        broken.write_text(
            "public class Broken { public void run() {\n",
            encoding="utf-8",
        )
        tree = format_java.parse_file(broken)
        assert format_java.has_parse_errors(tree)


# ---------------------------------------------------------------------------
# Stubs that intentionally raise
# ---------------------------------------------------------------------------


class TestFormatSourceSubset:
    """Verify format_source() handles the Phase 2c subset.

    Anything outside the supported subset (modifiers, methods,
    annotations, etc.) raises NotImplementedError from the
    dispatcher.
    """

    def test_empty_input_yields_empty_output(self) -> None:
        assert format_java.format_source(b"") == b""

    def test_empty_class(self) -> None:
        out = format_java.format_source(b"class A {}")
        assert out == b"class A\n{\n}\n"

    def test_class_with_field_no_initializer(self) -> None:
        out = format_java.format_source(b"class A { int x; }")
        assert out == b"class A\n{\n    int x;\n}\n"

    def test_class_with_field_with_initializer(self) -> None:
        out = format_java.format_source(b"class A { int x = 42; }")
        assert out == b"class A\n{\n    int x = 42;\n}\n"

    def test_class_with_multiple_fields_packed_no_blank_lines(
        self,
    ) -> None:
        out = format_java.format_source(
            b'class A { int x = 1; String s = "hi"; }'
        )
        # Per "Blank-Line Rules Between Class Members": fields
        # without javadoc are packed (no blank line between).
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int x = 1;\n"
            b'    String s = "hi";\n'
            b"}\n"
        )

    def test_field_with_multiple_declarators_comma_separated(
        self,
    ) -> None:
        out = format_java.format_source(
            b"class A { int x, y, z = 0; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int x, y, z = 0;\n"
            b"}\n"
        )

    def test_field_with_named_type(self) -> None:
        out = format_java.format_source(
            b'class A { String name = "foo"; }'
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b'    String name = "foo";\n'
            b"}\n"
        )

    def test_field_with_double_type(self) -> None:
        out = format_java.format_source(
            b"class A { double d = 1.5e-3; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    double d = 1.5e-3;\n"
            b"}\n"
        )

    def test_idempotency_for_supported_subset(self) -> None:
        # format(format(x)) == format(x) for every supported case.
        sources = [
            b"class A {}",
            b"class A { int x; }",
            b"class A { int x = 42; }",
            b'class A { String s = "hello"; double d = 1.5; }',
            b"class A { int x, y, z = 0; }",
        ]
        for src in sources:
            once = format_java.format_source(src)
            twice = format_java.format_source(once)
            assert once == twice, (
                f"non-idempotent for {src!r}: "
                f"once={once!r}, twice={twice!r}"
            )

    def test_parse_error_input_raises(self) -> None:
        with pytest.raises(ValueError, match="parse errors"):
            # Missing closing brace.
            format_java.format_source(b"class A { int x = 42;")

    def test_class_with_single_modifier(self) -> None:
        out = format_java.format_source(b"public class A {}")
        assert out == b"public class A\n{\n}\n"

    def test_class_with_multiple_modifiers(self) -> None:
        out = format_java.format_source(
            b"public final class A {}"
        )
        assert out == b"public final class A\n{\n}\n"

    def test_field_with_single_modifier(self) -> None:
        out = format_java.format_source(
            b"class A { public int x; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    public int x;\n"
            b"}\n"
        )

    def test_field_with_multiple_modifiers(self) -> None:
        out = format_java.format_source(
            b"class A { public static final int X = 42; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    public static final int X = 42;\n"
            b"}\n"
        )

    def test_class_and_fields_both_modified(self) -> None:
        out = format_java.format_source(
            b"public class A { "
            b"public static final int X = 42; "
            b"private String s; }"
        )
        assert out == (
            b"public class A\n"
            b"{\n"
            b"    public static final int X = 42;\n"
            b"    private String s;\n"
            b"}\n"
        )

    def test_modifier_order_is_preserved(self) -> None:
        # Formatter does NOT reorder modifiers; checkstyle enforces
        # the conventional JLS order separately. The formatter
        # emits modifiers as the developer wrote them.
        out = format_java.format_source(
            b"class A { volatile static private int x; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    volatile static private int x;\n"
            b"}\n"
        )

    def test_class_with_extends(self) -> None:
        # `extends` clause on a class declaration — single-line
        # form. Per spec B1, `extends X implements Y` flows
        # after the class name + type parameters; the body
        # opens Allman.
        out = format_java.format_source(b"class A extends B {}")
        assert out == (
            b"class A extends B\n"
            b"{\n"
            b"}\n"
        )

    def test_class_with_implements(self) -> None:
        # `implements` clause on a class declaration — single-
        # line form. Multiple interfaces separated by `, `.
        out = format_java.format_source(
            b"class A implements B, C {}"
        )
        assert out == (
            b"class A implements B, C\n"
            b"{\n"
            b"}\n"
        )

    def test_class_with_extends_and_implements(self) -> None:
        # Combined `extends X implements Y, Z` — both clauses
        # flow on the same line as the class name.
        out = format_java.format_source(
            b"class A extends Base implements I1, I2 {}"
        )
        assert out == (
            b"class A extends Base implements I1, I2\n"
            b"{\n"
            b"}\n"
        )

    def test_class_header_overflow_wraps_type_params(
        self,
    ) -> None:
        # When the single-line class header overflows 80 chars,
        # the type parameters wrap: first param after `<` on
        # the class line, subsequent params on continuation at
        # single-indent past the class start, `>` and any
        # extends/implements clause on the last type-param's
        # line, Allman brace because the header is multi-line.
        out = format_java.format_source(
            b"class Outer { "
            b"public abstract static class AbstractBuilder<"
            b"E extends Outer, "
            b"B extends AbstractBuilder<E, B>> "
            b"implements Initializer { } }"
        )
        assert out == (
            b"class Outer\n"
            b"{\n"
            b"    public abstract static class AbstractBuilder<"
            b"E extends Outer,\n"
            b"        B extends AbstractBuilder<E, B>>"
            b" implements Initializer\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    # method_declaration is now supported (Phase 2g) — the
    # former "not yet supported" test was promoted to a positive
    # assertion in `test_empty_method_body` below.

    # Annotations on classes and fields are now supported
    # (Phase 2n). Promoted to positive coverage below.

    # --- Expression-form initializers (Phase 2e) ---

    def test_field_with_binary_expression_initializer(self) -> None:
        out = format_java.format_source(
            b"class A { int x = 1 + 2; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int x = 1 + 2;\n"
            b"}\n"
        )

    def test_binary_operator_spacing_preserved(self) -> None:
        # Spec: single space around binary operators. Test
        # several operator families to verify the spacing rule
        # is applied uniformly.
        out = format_java.format_source(
            b"class A { int x = a + b * c - d / e % f; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int x = a + b * c - d / e % f;\n"
            b"}\n"
        )

    def test_comparison_and_boolean_operators(self) -> None:
        out = format_java.format_source(
            b"class A { boolean b = x == 1 && y != 2; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    boolean b = x == 1 && y != 2;\n"
            b"}\n"
        )

    def test_shift_and_bitwise_operators(self) -> None:
        out = format_java.format_source(
            b"class A { int x = a << 2 | b >> 1; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int x = a << 2 | b >> 1;\n"
            b"}\n"
        )

    def test_parenthesized_expression(self) -> None:
        out = format_java.format_source(
            b"class A { int x = (1 + 2) * 3; }"
        )
        # Spec: no space inside parens; binary operator
        # spacing applied recursively.
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int x = (1 + 2) * 3;\n"
            b"}\n"
        )

    def test_unary_expression_negation(self) -> None:
        out = format_java.format_source(
            b"class A { int x = -42; }"
        )
        # Spec: no space between unary operator and operand.
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int x = -42;\n"
            b"}\n"
        )

    def test_unary_expression_boolean_not(self) -> None:
        out = format_java.format_source(
            b"class A { boolean b = !flag; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    boolean b = !flag;\n"
            b"}\n"
        )

    def test_unary_expression_bitwise_not(self) -> None:
        out = format_java.format_source(
            b"class A { int x = ~mask; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int x = ~mask;\n"
            b"}\n"
        )

    def test_update_expression_prefix(self) -> None:
        out = format_java.format_source(
            b"class A { int x = ++counter; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int x = ++counter;\n"
            b"}\n"
        )

    def test_update_expression_postfix(self) -> None:
        # Symmetry check for the iteration approach in
        # `_emit_update_expression` — handles postfix the same
        # way as prefix.
        out = format_java.format_source(
            b"class A { int x = counter++; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int x = counter++;\n"
            b"}\n"
        )

    def test_nested_parens_and_unary(self) -> None:
        out = format_java.format_source(
            b"class A { boolean b = !((a == 1) || (b == 2)); }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    boolean b = !((a == 1) || (b == 2));\n"
            b"}\n"
        )

    # ternary_expression is now supported (Phase 2m, Tier 1
    # single-line). Promoted to positive coverage below.

    # --- Single-line expression operations (Phase 2f) ---

    def test_field_access_simple(self) -> None:
        out = format_java.format_source(
            b"class A { int x = obj.field; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int x = obj.field;\n"
            b"}\n"
        )

    def test_field_access_through_this(self) -> None:
        out = format_java.format_source(
            b"class A { int x = this.y; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int x = this.y;\n"
            b"}\n"
        )

    def test_method_call_no_arguments(self) -> None:
        out = format_java.format_source(
            b"class A { int x = obj.method(); }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int x = obj.method();\n"
            b"}\n"
        )

    def test_method_call_with_arguments(self) -> None:
        out = format_java.format_source(
            b"class A { int x = compute(1, 2); }"
        )
        # Comma-space separator per "Whitespace and Operator
        # Spacing" spec row "After commas: Exactly one space".
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int x = compute(1, 2);\n"
            b"}\n"
        )

    def test_method_call_with_compound_arguments(self) -> None:
        # Arguments dispatched recursively — exercises the
        # interaction between argument_list and the
        # binary_expression / field_access emitters.
        out = format_java.format_source(
            b"class A { int x = obj.method(a, b + c, d.e); }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int x = obj.method(a, b + c, d.e);\n"
            b"}\n"
        )

    def test_method_call_p2_paren_aligned_wrap(self) -> None:
        # Spec "Method Call Arguments / Priority 2 (two-line,
        # paren-aligned, comma-packed)": when P1 single-line
        # would overflow 80 chars, pack as many args as fit on
        # the call line and align the continuation to the
        # column right after `(`. Greedy packing — args go on
        # the call line until adding the next one would push
        # the line past 80; remaining args land at the paren-
        # aligned continuation column.
        src = (
            b"class A {\n"
            b"    void m() {\n"
            b"        String r = svc.callSomeLongMethodName("
            b"firstArg, secondArg, thirdArg, fourthArg);\n"
            b"    }\n"
            b"}\n"
        )
        out = format_java.format_source(src)
        # The `(` lands at column 46, so continuation is at
        # column 47 (46 leading spaces + the arg). The first
        # three args (firstArg, secondArg, thirdArg) pack
        # onto the call line; fourthArg breaks to the
        # continuation.
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        String r = svc.callSomeLongMethodName("
            b"firstArg, secondArg, thirdArg,\n"
            b"                                              "
            b"fourthArg);\n"
            b"    }\n"
            b"}\n"
        )

    def test_method_call_p4_single_arg_overflow(self) -> None:
        # Spec "Method Call Arguments / Priority 4 (next-line,
        # single-indented)": when a single-arg call's P1 form
        # would exceed 80 chars, line-break before the arg.
        # The arg lands at `(indent_level + 1) * 4` (single-
        # indent past the statement start); the closing `)`
        # stays on the arg's last line.
        src = (
            b"class A {\n"
            b"    void m(Object x) {\n"
            b"        if (x == null) {\n"
            b"            throw new IllegalArgumentException("
            b'"Cannot specify a secondary value when " + '
            b'"the primary value is null. primary=[ " + '
            b'x + " ]");\n'
            b"        }\n"
            b"    }\n"
            b"}\n"
        )
        out = format_java.format_source(src)
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m(Object x)\n"
            b"    {\n"
            b"        if (x == null) {\n"
            b"            throw new IllegalArgumentException(\n"
            b'                "Cannot specify a secondary value'
            b' when "\n'
            b'                    + "the primary value is null.'
            b' primary=[ " + x + " ]");\n'
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_binary_expression_wrap_greedy_packs(
        self,
    ) -> None:
        # Spec "Line Continuation / break before binary
        # operators" + 0.5.0 item 3 (greedy): non-boolean
        # binary chains pack as many `OP operand` pairs per
        # line as fit, then break at the operator boundary.
        # Continuation lines start at the +4 indent column.
        # This replaces the older leftmost-only-break (P2)
        # behavior for non-boolean operators.
        src = (
            b"class A {\n"
            b"    String s = "
            b'"alpha alpha alpha alpha alpha alpha" + '
            b'"beta" + "gamma" + "delta delta";\n'
            b"}\n"
        )
        out = format_java.format_source(src)
        # The chain overflows single-line; greedy packs the
        # short middle operands (`+ "beta"`, `+ "gamma"`)
        # onto the leftmost-operand line until adding
        # `+ "delta delta"` would overflow, then breaks.
        # Substring checks pin the greedy behavior without
        # over-constraining the exact column choice (which
        # the wrap engine may legitimately adjust).
        assert b'+ "beta" + "gamma"' in out
        assert b'        + "delta delta"' in out

    def test_method_call_without_receiver(self) -> None:
        # Method call with no `object` field — bare
        # method(args) form (typical for same-class methods or
        # statically-imported methods).
        out = format_java.format_source(
            b"class A { int x = compute(42); }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int x = compute(42);\n"
            b"}\n"
        )

    def test_cast_expression(self) -> None:
        out = format_java.format_source(
            b"class A { int x = (int) 1.5; }"
        )
        # Spec: single space after the closing cast paren.
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int x = (int) 1.5;\n"
            b"}\n"
        )

    def test_cast_to_named_type(self) -> None:
        out = format_java.format_source(
            b"class A { Object o = (String) value; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    Object o = (String) value;\n"
            b"}\n"
        )

    def test_instanceof_expression(self) -> None:
        out = format_java.format_source(
            b"class A { boolean ok = obj instanceof String; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    boolean ok = obj instanceof String;\n"
            b"}\n"
        )

    def test_instanceof_pattern_not_yet_supported(self) -> None:
        # The pattern-binding form (`x instanceof Type t`) has
        # its own spec section and lands in a later phase with
        # the pattern-matching emitters.
        with pytest.raises(
            NotImplementedError, match="pattern-binding"
        ):
            format_java.format_source(
                b"class A { "
                b"boolean ok = obj instanceof String s; }"
            )

    def test_method_call_with_explicit_type_witness_not_supported(
        self,
    ) -> None:
        # `obj.<Type>method(...)` form has explicit type
        # arguments handled with the generic-type emitter phase.
        with pytest.raises(
            NotImplementedError, match="type arguments"
        ):
            format_java.format_source(
                b"class A { "
                b"Object o = util.<String>method(); }"
            )

    def test_intersection_cast_not_yet_supported(self) -> None:
        # `(A & B) value` carries two `type`-field children in
        # the tree-sitter-java grammar; the naive emitter would
        # silently drop the second bound. Refuse loudly until
        # the intersection-type emitter lands.
        with pytest.raises(
            NotImplementedError, match="intersection type"
        ):
            format_java.format_source(
                b"class A { Object o = (A & B) v; }"
            )

    def test_instanceof_record_pattern_not_yet_supported(
        self,
    ) -> None:
        # `obj instanceof Point(int x, int y)` uses a
        # `pattern` field instead of `right`; refuse with a
        # clear message rather than the misleading
        # "grammar shape unexpected" error.
        with pytest.raises(
            NotImplementedError, match="record/deconstruction"
        ):
            # Wrap in a class+field-init context that's
            # supported through Phase 2f. The instanceof
            # itself is the unsupported part.
            format_java.format_source(
                b"class A { "
                b"boolean ok = obj instanceof Pt(int x); }"
            )

    # --- Method declarations (Phase 2g) ---

    def test_empty_method_body(self) -> None:
        out = format_java.format_source(
            b"class A { void m() {} }"
        )
        # Allman opening brace on its own line at the same
        # indent as the method declaration, closing brace
        # likewise; empty body between them.
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    def test_method_with_modifiers(self) -> None:
        out = format_java.format_source(
            b"class A { public void run() {} }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    public void run()\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    def test_method_with_single_parameter(self) -> None:
        out = format_java.format_source(
            b"class A { void process(int x) {} }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void process(int x)\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    def test_method_with_multiple_parameters(self) -> None:
        # Comma-space separator between parameters per spec.
        out = format_java.format_source(
            b"class A { String format(int x, String s) {} }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    String format(int x, String s)\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    def test_main_method_with_array_parameter(self) -> None:
        # Exercises the array_type emitter (`String[]`).
        out = format_java.format_source(
            b"class A { "
            b"public static void main(String[] args) {} }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    public static void main(String[] args)\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    def test_class_with_field_and_method_packed(self) -> None:
        # Per the "Blank-Line Rules" spec section, the formatter
        # doesn't yet emit blank lines between mixed members
        # (that requires javadoc handling). Just verify the
        # output is structurally correct.
        out = format_java.format_source(
            b"class A { int x = 1; void m() {} }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int x = 1;\n"
            b"    void m()\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    def test_nested_class_indents_braces(self) -> None:
        # A nested class declaration is emitted as a member of
        # the outer class body — its opening `{` and closing
        # `}` must indent to the nested-class column, NOT
        # column 0. (Top-level classes work either way because
        # indent_level=0.) Also verifies no doubled-newline
        # between the inner closing `}` and the outer closing
        # `}` (a regression that would emit a stray blank
        # line from a previously-redundant trailing newline).
        out = format_java.format_source(
            b"class Outer { class Inner { } }"
        )
        assert out == (
            b"class Outer\n"
            b"{\n"
            b"    class Inner\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    # method_declaration with non-empty body is now supported
    # (Phase 2h) — the former "not yet supported" assertion was
    # promoted to positive coverage in the statement tests below.

    # method throws clause is now supported (Phase 2p);
    # promoted to positive coverage below.

    def test_method_with_single_throws(self) -> None:
        # Per "Method and Constructor Declarations / Throws
        # Clause": throws on its own line, single-indented
        # (4 spaces from method declaration).
        out = format_java.format_source(
            b"class A { void m() throws IOException {} }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"        throws IOException\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    def test_method_with_multi_throws_single_line(self) -> None:
        # Spec P1 (single line) — the resulting line fits within
        # 80 chars, so the comma-space-separated form stays on
        # one line.
        out = format_java.format_source(
            b"class A { void m() "
            b"throws IOException, SQLException {} }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"        throws IOException, SQLException\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    def test_method_with_multi_throws_wraps_column_aligned(
        self,
    ) -> None:
        # Spec P2 (one per line, column-aligned with the first
        # type after `throws `) — when the P1 single-line form
        # would exceed 80 chars from the throws-line's start
        # column. Each line but the last carries `,`; the last
        # has no terminator. Continuation column = throws-line
        # indent + len("throws ").
        out = format_java.format_source(
            b"class A { void method() "
            b"throws AReallyLongExceptionTypeNameOne, "
            b"AReallyLongExceptionTypeNameTwo, "
            b"AReallyLongExceptionTypeNameThree {} }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void method()\n"
            b"        throws AReallyLongExceptionTypeNameOne,\n"
            b"               AReallyLongExceptionTypeNameTwo,\n"
            b"               AReallyLongExceptionTypeNameThree\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    def test_method_with_modifiers_and_throws(self) -> None:
        out = format_java.format_source(
            b"class A { public void load() "
            b"throws IOException { x(); } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    public void load()\n"
            b"        throws IOException\n"
            b"    {\n"
            b"        x();\n"
            b"    }\n"
            b"}\n"
        )

    # Methods with type parameters (`<T> void m(T x)`) are
    # now supported as of Phase 2x. Positive coverage in the
    # type-parameters tests below.

    # Abstract / interface methods (method_declaration without
    # body field) are now supported (Phase 2s). Positive
    # coverage in the interface tests below.

    def test_parameter_with_modifier(self) -> None:
        # Per spec A3: keyword modifier (`final`) on a parameter
        # appears before the type with a single space separator.
        out = format_java.format_source(
            b"class A { void m(final int x) {} }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m(final int x)\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    def test_parameter_with_annotation(self) -> None:
        # Per spec A3: annotation on a parameter appears before
        # the type with a single space.
        out = format_java.format_source(
            b"class A { void m(@NonNull String x) {} }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m(@NonNull String x)\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    # --- Statement emitters (Phase 2h) ---

    def test_return_statement_with_value(self) -> None:
        out = format_java.format_source(
            b"class A { int m() { return 42; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int m()\n"
            b"    {\n"
            b"        return 42;\n"
            b"    }\n"
            b"}\n"
        )

    def test_return_statement_without_value(self) -> None:
        out = format_java.format_source(
            b"class A { void m() { return; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        return;\n"
            b"    }\n"
            b"}\n"
        )

    def test_return_statement_with_expression(self) -> None:
        out = format_java.format_source(
            b"class A { int m() { return x + y; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int m()\n"
            b"    {\n"
            b"        return x + y;\n"
            b"    }\n"
            b"}\n"
        )

    def test_expression_statement_method_call(self) -> None:
        out = format_java.format_source(
            b"class A { void m() { compute(); } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        compute();\n"
            b"    }\n"
            b"}\n"
        )

    def test_expression_statement_assignment(self) -> None:
        out = format_java.format_source(
            b"class A { void m() { x = 1; } }"
        )
        # Assignment operator gets single space on each side
        # per "Whitespace and Operator Spacing" spec section.
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        x = 1;\n"
            b"    }\n"
            b"}\n"
        )

    def test_compound_assignment_operators(self) -> None:
        # `+=` and `*=` exercise the assignment-operator field
        # recovery in `_emit_assignment_expression`.
        out = format_java.format_source(
            b"class A { void m() { "
            b"this.count += 1; this.total *= 2; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        this.count += 1;\n"
            b"        this.total *= 2;\n"
            b"    }\n"
            b"}\n"
        )

    def test_local_variable_declaration(self) -> None:
        out = format_java.format_source(
            b"class A { int m() { int r = 42; return r; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int m()\n"
            b"    {\n"
            b"        int r = 42;\n"
            b"        return r;\n"
            b"    }\n"
            b"}\n"
        )

    def test_multiple_local_variable_declarations(self) -> None:
        out = format_java.format_source(
            b"class A { void m() { int x = 1; long y = 2; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        int x = 1;\n"
            b"        long y = 2;\n"
            b"    }\n"
            b"}\n"
        )

    def test_local_variable_with_modifier(self) -> None:
        # `local_variable_declaration` shares the same emitter
        # as `field_declaration`, so the modifier path is
        # already covered structurally; this test confirms it
        # works in the local-variable context.
        out = format_java.format_source(
            b"class A { void m() { final int x = 1; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        final int x = 1;\n"
            b"    }\n"
            b"}\n"
        )

    # --- if-statement + control-flow blocks (Phase 2i) ---

    def test_if_statement_with_block(self) -> None:
        out = format_java.format_source(
            b"class A { void m() { if (x) { y(); } } }"
        )
        # Same-line opening brace; statements indented; closing
        # brace on its own line at the if's indent.
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        if (x) {\n"
            b"            y();\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_if_else_statement(self) -> None:
        out = format_java.format_source(
            b"class A { void m() { "
            b"if (x) { y(); } else { z(); } } }"
        )
        # Per "Closing Brace Rules": `else` cuddles with the
        # closing `}` of the preceding block.
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        if (x) {\n"
            b"            y();\n"
            b"        } else {\n"
            b"            z();\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_else_if_chain(self) -> None:
        # Else-if chains are recursive: the `alternative` field
        # is itself an `if_statement`.
        out = format_java.format_source(
            b"class A { void m() { "
            b"if (a) { x(); } else if (b) { y(); } "
            b"else { z(); } } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        if (a) {\n"
            b"            x();\n"
            b"        } else if (b) {\n"
            b"            y();\n"
            b"        } else {\n"
            b"            z();\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_if_with_compound_condition(self) -> None:
        # Condition is a parenthesized binary expression;
        # dispatches through parenthesized_expression and
        # binary_expression, exercising the recursive emit.
        out = format_java.format_source(
            b"class A { void m() { "
            b"if (x == 1 && y != 2) { compute(); } } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        if (x == 1 && y != 2) {\n"
            b"            compute();\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_braceless_non_short_circuit_wraps_in_braces(
        self,
    ) -> None:
        # `if (x) y();` is Tier 1 SOURCE FORM but the body is
        # a method call, NOT a short-circuit statement.
        # Per the spec's "Short-Circuit Conditionals" section,
        # Tier 1 only applies for return/continue/break/throw
        # bodies; everything else must be braced. The
        # formatter wraps the bare statement in braces via
        # `_emit_branch_as_block`.
        out = format_java.format_source(
            b"class A { void m() { if (x) y(); } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        if (x) {\n"
            b"            y();\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_braceless_short_circuit_stays_tier1(self) -> None:
        # Tier 1 source form with a short-circuit body
        # preserves Tier 1 in the output.
        out = format_java.format_source(
            b"class A { void m() { if (x) return; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        if (x) return;\n"
            b"    }\n"
            b"}\n"
        )

    def test_braced_short_circuit_collapses_to_tier1(self) -> None:
        # Tier 2 source form with a single short-circuit body
        # collapses to Tier 1 output (per spec's
        # "Short-Circuit Conditionals" section).
        out = format_java.format_source(
            b"class A { void m() { "
            b"if (x) { return null; } } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        if (x) return null;\n"
            b"    }\n"
            b"}\n"
        )

    # --- Constructors + static initializers (Phase 2r) ---

    def test_constructor_no_args(self) -> None:
        out = format_java.format_source(
            b"class A { public A() {} }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    public A()\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    def test_constructor_with_args_and_body(self) -> None:
        out = format_java.format_source(
            b"class A { "
            b"public A(int x) { this.x = x; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    public A(int x)\n"
            b"    {\n"
            b"        this.x = x;\n"
            b"    }\n"
            b"}\n"
        )

    def test_constructor_with_throws(self) -> None:
        out = format_java.format_source(
            b"class A { A() throws IOException {} }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    A()\n"
            b"        throws IOException\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    def test_static_initializer_allman(self) -> None:
        # Per spec B10: static keyword on its own line,
        # opening `{` on the next line at the same column.
        out = format_java.format_source(
            b"class A { static "
            b"{ CODES = new HashMap<>(); } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    static\n"
            b"    {\n"
            b"        CODES = new HashMap<>();\n"
            b"    }\n"
            b"}\n"
        )

    # --- Interface declarations (Phase 2s) ---

    def test_empty_interface(self) -> None:
        out = format_java.format_source(b"interface A {}")
        assert out == b"interface A\n{\n}\n"

    def test_interface_with_abstract_method(self) -> None:
        # Abstract method emits as signature + `;` — no
        # Allman brace, no body.
        out = format_java.format_source(
            b"public interface A { void m(); }"
        )
        assert out == (
            b"public interface A\n"
            b"{\n"
            b"    void m();\n"
            b"}\n"
        )

    def test_interface_with_constant_and_method(self) -> None:
        out = format_java.format_source(
            b"interface A { int VALUE = 42; void m(); }"
        )
        # `constant_declaration` reuses `_emit_field_declaration`
        # since the grammar shape is identical.
        assert out == (
            b"interface A\n"
            b"{\n"
            b"    int VALUE = 42;\n"
            b"    void m();\n"
            b"}\n"
        )

    def test_interface_with_default_method(self) -> None:
        out = format_java.format_source(
            b"interface A { default void m() { x(); } }"
        )
        assert out == (
            b"interface A\n"
            b"{\n"
            b"    default void m()\n"
            b"    {\n"
            b"        x();\n"
            b"    }\n"
            b"}\n"
        )

    # --- Type-use annotations (Phase 2t) ---

    # --- Lambda expressions (Phase 2v, single-line form) ---

    def test_lambda_zero_args(self) -> None:
        # Spec B5: single space on each side of `->`.
        out = format_java.format_source(
            b"class A { void m() { "
            b"Runnable r = () -> doWork(); } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        Runnable r = () -> doWork();\n"
            b"    }\n"
            b"}\n"
        )

    def test_lambda_single_inferred_param_no_parens(self) -> None:
        # `s -> body` form — parameters is a bare identifier.
        out = format_java.format_source(
            b"class A { void m() { "
            b"Consumer<String> c = s -> print(s); } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        Consumer<String> c = s -> print(s);\n"
            b"    }\n"
            b"}\n"
        )

    def test_lambda_multi_inferred_params(self) -> None:
        # `(x, y) -> body` form — inferred_parameters.
        out = format_java.format_source(
            b"class A { void m() { "
            b"BiFunction<Integer, Integer, Integer> f = "
            b"(x, y) -> x + y; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        BiFunction<Integer, Integer, Integer> f"
            b" = (x, y) -> x + y;\n"
            b"    }\n"
            b"}\n"
        )

    def test_lambda_explicit_typed_param(self) -> None:
        # `(Integer x) -> body` form — formal_parameters.
        out = format_java.format_source(
            b"class A { void m() { "
            b"Function<Integer, Integer> g = "
            b"(Integer x) -> x * 2; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        Function<Integer, Integer> g = "
            b"(Integer x) -> x * 2;\n"
            b"    }\n"
            b"}\n"
        )

    def test_lambda_block_body(self) -> None:
        # Lambda with a block body — same-line opening brace
        # per spec's same-line-brace rule for lambda
        # expressions.
        out = format_java.format_source(
            b"class A { void m() { "
            b"Runnable r = () -> { doA(); doB(); }; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        Runnable r = () -> {\n"
            b"            doA();\n"
            b"            doB();\n"
            b"        };\n"
            b"    }\n"
            b"}\n"
        )

    # --- Wildcard + enum declarations (Phase 2u) ---

    def test_wildcard_unbounded(self) -> None:
        out = format_java.format_source(
            b"class A { List<?> any; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    List<?> any;\n"
            b"}\n"
        )

    def test_wildcard_extends_bound(self) -> None:
        # Spec A4: space after `?` before extends/super.
        out = format_java.format_source(
            b"class A { List<? extends Foo> bounded; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    List<? extends Foo> bounded;\n"
            b"}\n"
        )

    def test_wildcard_super_bound(self) -> None:
        out = format_java.format_source(
            b"class A { List<? super Foo> bounded; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    List<? super Foo> bounded;\n"
            b"}\n"
        )

    # --- type parameters on declarations (Phase 2x) ---

    def test_type_parameters_class_single(self) -> None:
        # Spec B11: `<T>` adjacent to the class name (no space)
        # for a single type parameter.
        out = format_java.format_source(
            b"public class A<T> { }"
        )
        assert out == (
            b"public class A<T>\n"
            b"{\n"
            b"}\n"
        )

    def test_type_parameters_class_multiple(self) -> None:
        # Spec A4 / B11: comma-space between type parameters,
        # no spaces inside `<>`.
        out = format_java.format_source(
            b"public class A<T, U, V> { }"
        )
        assert out == (
            b"public class A<T, U, V>\n"
            b"{\n"
            b"}\n"
        )

    def test_type_parameters_class_bounded(self) -> None:
        # Spec B11: single space around `extends`.
        out = format_java.format_source(
            b"public class A<T extends Foo> { }"
        )
        assert out == (
            b"public class A<T extends Foo>\n"
            b"{\n"
            b"}\n"
        )

    def test_type_parameters_class_multi_bound(self) -> None:
        # Spec B11: single space around `&` for multi-bound
        # types.
        out = format_java.format_source(
            b"class A<T extends Foo & Bar & Baz> { }"
        )
        assert out == (
            b"class A<T extends Foo & Bar & Baz>\n"
            b"{\n"
            b"}\n"
        )

    def test_type_parameters_interface(self) -> None:
        # Interface declarations follow the same rule as class
        # declarations — `<T>` adjacent to the interface name.
        out = format_java.format_source(
            b"public interface I<T> { }"
        )
        assert out == (
            b"public interface I<T>\n"
            b"{\n"
            b"}\n"
        )

    def test_type_parameters_method(self) -> None:
        # Spec B11: `<T>` BEFORE the return type, followed by
        # a single space.
        out = format_java.format_source(
            b"class A { public <T> T m(T x) { return x; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    public <T> T m(T x)\n"
            b"    {\n"
            b"        return x;\n"
            b"    }\n"
            b"}\n"
        )

    def test_type_parameters_method_bounded(self) -> None:
        # Method with a bounded type parameter — combines the
        # B11 type-parameter placement with the bound spacing.
        out = format_java.format_source(
            b"class A { "
            b"<T extends Foo> T m(T x) { return x; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    <T extends Foo> T m(T x)\n"
            b"    {\n"
            b"        return x;\n"
            b"    }\n"
            b"}\n"
        )

    def test_type_parameters_constructor(self) -> None:
        # Spec B11: `<T>` BEFORE the constructor name (after
        # modifiers, with a single space after the closing
        # `>`).
        out = format_java.format_source(
            b"class A { public <T> A(T x) { } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    public <T> A(T x)\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    def test_enum_simple_constants(self) -> None:
        out = format_java.format_source(
            b"enum Color { RED, GREEN, BLUE; }"
        )
        # Per spec A2/B9: one constant per line; trailing
        # `;` after last constant always emitted.
        assert out == (
            b"enum Color\n"
            b"{\n"
            b"    RED,\n"
            b"    GREEN,\n"
            b"    BLUE;\n"
            b"}\n"
        )

    def test_enum_constants_with_arguments(self) -> None:
        out = format_java.format_source(
            b'enum E { ACTIVE("active"), INACTIVE("inactive"); }'
        )
        assert out == (
            b"enum E\n"
            b"{\n"
            b'    ACTIVE("active"),\n'
            b'    INACTIVE("inactive");\n'
            b"}\n"
        )

    def test_enum_with_constructor_and_field(self) -> None:
        # Per spec A2: blank line between the constants `;`
        # and the non-constant members that follow.
        out = format_java.format_source(
            b"enum E { A, B; private final int x; "
            b"E() { this.x = 0; } }"
        )
        assert out == (
            b"enum E\n"
            b"{\n"
            b"    A,\n"
            b"    B;\n"
            b"\n"
            b"    private final int x;\n"
            b"    E()\n"
            b"    {\n"
            b"        this.x = 0;\n"
            b"    }\n"
            b"}\n"
        )

    # --- Enum constants with anonymous bodies (Phase 2z / spec B9) ---

    def test_enum_constant_with_anonymous_body(self) -> None:
        # Spec B9: enum-constant body opens on its OWN line
        # (Allman), NOT same-line like C8 anonymous-class
        # expressions. Body content uses standard class-body
        # member emission — method declarations inside still
        # take their normal Allman brace placement.
        out = format_java.format_source(
            b"enum Op { PLUS { public int apply(int a, int b) "
            b"{ return a + b; } } }"
        )
        assert out == (
            b"enum Op\n"
            b"{\n"
            b"    PLUS\n"
            b"    {\n"
            b"        public int apply(int a, int b)\n"
            b"        {\n"
            b"            return a + b;\n"
            b"        }\n"
            b"    };\n"
            b"}\n"
        )

    def test_enum_constants_with_anonymous_bodies(self) -> None:
        # Two constants each with an anonymous body — the
        # parent enum-body emitter handles `,` between
        # consecutive constants and `;` after the last,
        # attached to the closing `}` of the body.
        out = format_java.format_source(
            b"enum Op { "
            b"PLUS { public int apply(int a, int b) "
            b"{ return a + b; } }, "
            b"MINUS { public int apply(int a, int b) "
            b"{ return a - b; } } "
            b"}"
        )
        assert out == (
            b"enum Op\n"
            b"{\n"
            b"    PLUS\n"
            b"    {\n"
            b"        public int apply(int a, int b)\n"
            b"        {\n"
            b"            return a + b;\n"
            b"        }\n"
            b"    },\n"
            b"    MINUS\n"
            b"    {\n"
            b"        public int apply(int a, int b)\n"
            b"        {\n"
            b"            return a - b;\n"
            b"        }\n"
            b"    };\n"
            b"}\n"
        )

    def test_enum_constant_with_arguments_and_body(self) -> None:
        # Spec B9 combined form: constructor arguments AND
        # anonymous body on the same constant. Arguments on
        # the constant's line; body opens on its own line
        # (Allman) following the closing `)`.
        out = format_java.format_source(
            b'enum Op { '
            b'PLUS("plus", 1) { '
            b'@Override public int apply(int a, int b) '
            b'{ return a + b; } '
            b'} }'
        )
        assert out == (
            b"enum Op\n"
            b"{\n"
            b'    PLUS("plus", 1)\n'
            b"    {\n"
            b"        @Override\n"
            b"        public int apply(int a, int b)\n"
            b"        {\n"
            b"            return a + b;\n"
            b"        }\n"
            b"    };\n"
            b"}\n"
        )

    def test_enum_mixed_plain_and_body_constants(self) -> None:
        # Plain constants and body constants can be mixed in
        # the same enum. Plain constants emit a `,` directly
        # after the name; body constants emit the `,` after
        # the closing `}` of the body.
        out = format_java.format_source(
            b"enum Op { PLUS, MINUS { void m() { y(); } }, "
            b"DIVIDE }"
        )
        assert out == (
            b"enum Op\n"
            b"{\n"
            b"    PLUS,\n"
            b"    MINUS\n"
            b"    {\n"
            b"        void m()\n"
            b"        {\n"
            b"            y();\n"
            b"        }\n"
            b"    },\n"
            b"    DIVIDE;\n"
            b"}\n"
        )

    def test_annotated_type_in_throws(self) -> None:
        # Per spec A3 type-use annotations: annotation
        # inline immediately before the type with a single
        # space between annotation and type.
        out = format_java.format_source(
            b"class A { void m() throws @NonNull IOException {} }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"        throws @NonNull IOException\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    def test_annotated_type_multi_in_throws(self) -> None:
        out = format_java.format_source(
            b"class A { void m() throws "
            b"@NonNull IOException, @Nullable SQLException {} }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"        throws @NonNull IOException, "
            b"@Nullable SQLException\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    def test_interface_abstract_method_with_throws(self) -> None:
        out = format_java.format_source(
            b"public interface Foo { "
            b"void method() throws AlphaException; }"
        )
        # Abstract method with throws: signature line +
        # indented throws line with `;` at end. No Allman
        # brace.
        assert out == (
            b"public interface Foo\n"
            b"{\n"
            b"    void method()\n"
            b"        throws AlphaException;\n"
            b"}\n"
        )

    def test_static_initializer_multiple_statements(self) -> None:
        out = format_java.format_source(
            b"class A { static { x = 1; y = 2; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    static\n"
            b"    {\n"
            b"        x = 1;\n"
            b"        y = 2;\n"
            b"    }\n"
            b"}\n"
        )

    def test_if_else_inhibits_tier1_short_circuit(self) -> None:
        # Per the spec's "if/else pairs always use braces"
        # rule, the presence of any else clause forces braces
        # on BOTH branches, even if the body is short-circuit.
        out = format_java.format_source(
            b"class A { void m() { "
            b"if (x) return; else doB(); } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        if (x) {\n"
            b"            return;\n"
            b"        } else {\n"
            b"            doB();\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_else_if_chain_inhibits_tier1(self) -> None:
        # Per spec's "once any branch has an `else`, every
        # branch is braced", an `else if` branch is part of
        # the chain even if its own body would otherwise be
        # Tier-1-eligible. The inner if_statement (the
        # alternative of the outer) must keep its braces.
        out = format_java.format_source(
            b"class A { int m(int a, int b) { "
            b"if (a == 0) { return 1; } "
            b"else if (b == 0) { return 2; } "
            b"return 3; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int m(int a, int b)\n"
            b"    {\n"
            b"        if (a == 0) {\n"
            b"            return 1;\n"
            b"        } else if (b == 0) {\n"
            b"            return 2;\n"
            b"        }\n"
            b"        return 3;\n"
            b"    }\n"
            b"}\n"
        )

    def test_tier1_inhibited_by_blank_line_in_body(self) -> None:
        # A source-authored blank line between the opening `{`
        # and the short-circuit statement is a deliberate
        # visual-separation cue. Tier 1 collapse would erase
        # it, so the formatter keeps the Tier 2 braced form
        # AND preserves the blank line inside the body.
        out = format_java.format_source(
            b"class A {\n"
            b"    Object m(Object x) {\n"
            b"        if (x == null) {\n"
            b"\n"
            b"            return null;\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    Object m(Object x)\n"
            b"    {\n"
            b"        if (x == null) {\n"
            b"\n"
            b"            return null;\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_inline_side_comment_on_brace_line(self) -> None:
        # Per spec C6 ("End-of-line side comments"), a
        # line_comment on the same source row as a preceding
        # `{` stays inline with the brace, separated by
        # exactly two spaces, with a single space after `//`.
        out = format_java.format_source(
            b"class A {\n"
            b"    void m() {\n"
            b"        if (x == null) { // inline comment\n"
            b"            return;\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        if (x == null) {  // inline comment\n"
            b"            return;\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_if_with_empty_block(self) -> None:
        # Empty consequence block should still emit cleanly
        # with the opening `{` on the if-line and the closing
        # `}` on its own line at the if's indent.
        out = format_java.format_source(
            b"class A { void m() { if (x) {} } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        if (x) {\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    # --- Loop statements (Phase 2j) ---

    def test_for_statement_classic(self) -> None:
        out = format_java.format_source(
            b"class A { void m() { "
            b"for (int i = 0; i < n; i++) { x(); } } }"
        )
        # Same-line-brace control-flow form; the
        # `local_variable_declaration` init carries its own
        # trailing `;` from the grammar.
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        for (int i = 0; i < n; i++) {\n"
            b"            x();\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_for_statement_empty_header(self) -> None:
        # `for (;;)` — no init, no condition, no update.
        out = format_java.format_source(
            b"class A { void m() { for (;;) {} } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        for (;;) {\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_while_statement(self) -> None:
        out = format_java.format_source(
            b"class A { void m() { while (x) { y(); } } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        while (x) {\n"
            b"            y();\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_while_multiline_condition_uses_allman(self) -> None:
        # Per spec "Brace Placement / Exception: Multi-Line
        # Conditions" — when the condition spans multiple
        # source rows, the opening `{` goes Allman. The
        # source's multi-line layout is preserved.
        src = (
            b"class A {\n"
            b"    void m() {\n"
            b"        while (this.a.size()\n"
            b"                < this.b.size()) {\n"
            b"            y();\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )
        out = format_java.format_source(src)
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        while (this.a.size()\n"
            b"                < this.b.size())\n"
            b"        {\n"
            b"            y();\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_for_multiline_header_uses_allman(self) -> None:
        # Per spec "Brace Placement / Exception: Multi-Line
        # Conditions" — when the for-header spans multiple
        # source rows, the opening `{` goes Allman.
        src = (
            b"class A {\n"
            b"    void m() {\n"
            b"        for (int i = a();\n"
            b"             i >= 0;\n"
            b"             i = a()) {\n"
            b"            y();\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )
        out = format_java.format_source(src)
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        for (int i = a();\n"
            b"             i >= 0;\n"
            b"             i = a())\n"
            b"        {\n"
            b"            y();\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_method_multiline_params_preserved(self) -> None:
        # Per spec — source-authored multi-line parameter
        # lists are preserved; the body's Allman brace is
        # unchanged (method bodies are always Allman).
        src = (
            b"class A {\n"
            b"    void wrappedHeader(int alpha,\n"
            b"                       int beta) {\n"
            b"        doIt();\n"
            b"    }\n"
            b"}\n"
        )
        out = format_java.format_source(src)
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void wrappedHeader(int alpha,\n"
            b"                       int beta)\n"
            b"    {\n"
            b"        doIt();\n"
            b"    }\n"
            b"}\n"
        )

    def test_tier1_overlong_falls_back_to_tier2(self) -> None:
        # Spec "Short-Circuit Conditionals / Tier 2" — when
        # the Tier-1 single-line form would exceed 80 chars,
        # fall back to Tier 2 (braced).
        src = (
            b"class A {\n"
            b"    void m() {\n"
            b"        if (somethingExtremelyLongConditionThatGoesOnAndOnAndOnAndOn)\n"
            b'            throw new IllegalStateException("a long-ish message here");\n'
            b"    }\n"
            b"}\n"
        )
        out = format_java.format_source(src)
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        if (somethingExtremelyLongConditionThatGoesOnAndOnAndOnAndOn) {\n"
            b'            throw new IllegalStateException("a long-ish message here");\n'
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_do_while_statement_cuddled_while(self) -> None:
        # Per "Closing Brace Rules", `while` cuddles with the
        # closing `}` of the body block: `} while (cond);`.
        out = format_java.format_source(
            b"class A { void m() { "
            b"do { x(); } while (cond); } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        do {\n"
            b"            x();\n"
            b"        } while (cond);\n"
            b"    }\n"
            b"}\n"
        )

    def test_enhanced_for_statement(self) -> None:
        # For-each form: `for (TYPE NAME : VALUE) { ... }`.
        out = format_java.format_source(
            b"class A { void m() { "
            b"for (int x : list) { use(x); } } }"
        )
        # Single space around the `:` separator.
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        for (int x : list) {\n"
            b"            use(x);\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_enhanced_for_with_named_type(self) -> None:
        out = format_java.format_source(
            b"class A { void m() { "
            b"for (String s : items) { print(s); } } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        for (String s : items) {\n"
            b"            print(s);\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_for_statement_bare_expression_init(self) -> None:
        # `i = 0` as init (no `int` keyword) — the bare-
        # expression init branch of `_emit_for_statement`
        # (different from the local_variable_declaration
        # init branch tested above).
        out = format_java.format_source(
            b"class A { void m() { "
            b"for (i = 0; i < n; i++) {} } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        for (i = 0; i < n; i++) {\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_for_multi_init(self) -> None:
        # Comma-separated init expressions
        # (`for (i = 0, j = 0; ...)`) — the grammar surfaces
        # them as multiple children sharing the `init` field
        # name; the emitter collects all of them and emits
        # comma-separated. Pin the full output so a regression
        # that corrupts the surrounding class body would also
        # be caught.
        out = format_java.format_source(
            b"class A { void m() { "
            b"for (i = 0, j = 0; i < n; i++) {} } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        for (i = 0, j = 0; i < n; i++) {\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_for_multi_update(self) -> None:
        # Mirror of `test_for_multi_init` for the update slot
        # (`for (... ; ... ; i++, j++)`). Full-output pin for
        # the same surrounding-context regression reason.
        out = format_java.format_source(
            b"class A { void m() { "
            b"for (int i = 0; i < n; i++, j++) {} } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        for (int i = 0; i < n; i++, j++) {\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    # --- try/catch/finally (Phase 2k) ---

    def test_try_catch(self) -> None:
        # Per "Closing Brace Rules", `catch` cuddles with the
        # closing `}` of the try block: `} catch (...) {`.
        out = format_java.format_source(
            b"class A { void m() { "
            b"try { x(); } catch (Exception e) { y(); } } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        try {\n"
            b"            x();\n"
            b"        } catch (Exception e) {\n"
            b"            y();\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_try_finally(self) -> None:
        # `finally` cuddles with `}` per the spec.
        out = format_java.format_source(
            b"class A { void m() { "
            b"try { x(); } finally { cleanup(); } } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        try {\n"
            b"            x();\n"
            b"        } finally {\n"
            b"            cleanup();\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_try_catch_catch_finally(self) -> None:
        # Multiple catches followed by a finally, all cuddled.
        out = format_java.format_source(
            b"class A { void m() { "
            b"try { x(); } "
            b"catch (IOException e) { a(); } "
            b"catch (SQLException e) { b(); } "
            b"finally { c(); } } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        try {\n"
            b"            x();\n"
            b"        } catch (IOException e) {\n"
            b"            a();\n"
            b"        } catch (SQLException e) {\n"
            b"            b();\n"
            b"        } finally {\n"
            b"            c();\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_multi_catch_single_line(self) -> None:
        # Spec "Multi-catch": single space on each side of `|`.
        out = format_java.format_source(
            b"class A { void m() { "
            b"try { x(); } catch (IOException | SQLException e) "
            b"{ y(); } } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        try {\n"
            b"            x();\n"
            b"        } catch (IOException | SQLException e) {\n"
            b"            y();\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_try_with_resources_single_resource(self) -> None:
        # Spec B8: single resource fitting on one line uses
        # same-line opening brace.
        out = format_java.format_source(
            b"class A { void m() throws Exception { "
            b"try (FileInputStream in = new FileInputStream(file)) "
            b"{ process(in); } } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"        throws Exception\n"
            b"    {\n"
            b"        try (FileInputStream in"
            b" = new FileInputStream(file)) {\n"
            b"            process(in);\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_try_with_resources_multi_resource(self) -> None:
        # Spec B8: multi-resource is ALWAYS multi-line. Subsequent
        # resources paren-align with the column right after
        # `try (`. The opening `{` goes Allman because the try
        # condition spans multiple lines.
        out = format_java.format_source(
            b"class A { void m() throws Exception { "
            b"try (FileInputStream in = new FileInputStream(input);"
            b" FileOutputStream out = new FileOutputStream(output)) "
            b"{ transfer(in, out); } } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"        throws Exception\n"
            b"    {\n"
            b"        try (FileInputStream in"
            b" = new FileInputStream(input);\n"
            b"             FileOutputStream out"
            b" = new FileOutputStream(output))\n"
            b"        {\n"
            b"            transfer(in, out);\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_try_with_resources_with_catch_and_finally(self) -> None:
        # Spec B8 / "Closing Brace Rules": catch and finally
        # clauses cuddle with the closing `}` of the try body
        # the same way they do for plain try_statement.
        out = format_java.format_source(
            b"class A { void m() { "
            b"try (FileInputStream in = new FileInputStream(file)) "
            b"{ process(in); } "
            b"catch (IOException e) { log(e); } "
            b"finally { cleanup(); } } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        try (FileInputStream in"
            b" = new FileInputStream(file)) {\n"
            b"            process(in);\n"
            b"        } catch (IOException e) {\n"
            b"            log(e);\n"
            b"        } finally {\n"
            b"            cleanup();\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_try_with_resources_three_resources(self) -> None:
        # Spec B8 alignment generalizes: every subsequent
        # resource lines up with the column right after `try (`.
        out = format_java.format_source(
            b"class A { void m() throws Exception { "
            b"try (A a = openA(); B b = openB(); C c = openC()) "
            b"{ use(a, b, c); } } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"        throws Exception\n"
            b"    {\n"
            b"        try (A a = openA();\n"
            b"             B b = openB();\n"
            b"             C c = openC())\n"
            b"        {\n"
            b"            use(a, b, c);\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_try_with_resources_shorthand_refuses(self) -> None:
        # Java 9+ shorthand: a previously-declared effectively-
        # final variable can appear in the resource list without
        # a `Type name = ` prefix (`try (conn) { ... }`). The
        # grammar exposes this via a missing `type` / `name` /
        # `value` field on the resource node. Phase 2w refuses
        # this shape cleanly; support lands later.
        with pytest.raises(
            NotImplementedError,
            match=(
                "shorthand resource form .Java 9. effectively-"
                "final variable. is not yet supported"
            ),
        ):
            format_java.format_source(
                b"class A { "
                b"void m(AutoCloseable conn) throws Exception { "
                b"try (conn) { use(conn); } } }"
            )

    # --- throw / break / continue / labeled (Phase 2l) ---

    def test_throw_statement_with_identifier(self) -> None:
        out = format_java.format_source(
            b"class A { void m() { throw e; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        throw e;\n"
            b"    }\n"
            b"}\n"
        )

    def test_break_statement_unlabeled(self) -> None:
        out = format_java.format_source(
            b"class A { void m() { "
            b"while (x) { break; } } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        while (x) {\n"
            b"            break;\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_continue_statement_unlabeled(self) -> None:
        out = format_java.format_source(
            b"class A { void m() { "
            b"while (x) { continue; } } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        while (x) {\n"
            b"            continue;\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_labeled_break(self) -> None:
        # Spec C7: label appears on its own line at the column
        # of the labeled statement. `break LABEL;` with a
        # single space between keyword and label.
        out = format_java.format_source(
            b"class A { void m() { "
            b"outer: for (;;) { break outer; } } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        outer:\n"
            b"        for (;;) {\n"
            b"            break outer;\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    def test_labeled_continue(self) -> None:
        # Updated post-Phase-2q: the inner `if (i == 5) {
        # continue outer; }` collapses to Tier 1 since
        # `continue outer;` is a short-circuit body and
        # there's no else.
        out = format_java.format_source(
            b"class A { void m() { "
            b"outer: for (int i = 0; i < n; i++) { "
            b"if (i == 5) { continue outer; } } } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        outer:\n"
            b"        for (int i = 0; i < n; i++) {\n"
            b"            if (i == 5) continue outer;\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )

    # --- Ternary + object creation (Phase 2m) ---

    def test_ternary_expression_simple(self) -> None:
        out = format_java.format_source(
            b"class A { int x = a ? b : c; }"
        )
        # Per "Whitespace and Operator Spacing", `?` and `:`
        # each get single space on each side.
        assert out == (
            b"class A\n"
            b"{\n"
            b"    int x = a ? b : c;\n"
            b"}\n"
        )

    def test_ternary_expression_with_compound_condition(
        self,
    ) -> None:
        out = format_java.format_source(
            b'class A { String s = x > 0 ? "pos" : "neg"; }'
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b'    String s = x > 0 ? "pos" : "neg";\n'
            b"}\n"
        )

    def test_object_creation_no_args(self) -> None:
        out = format_java.format_source(
            b"class A { Object o = new Object(); }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    Object o = new Object();\n"
            b"}\n"
        )

    def test_object_creation_with_args(self) -> None:
        out = format_java.format_source(
            b'class A { String s = new String("hi"); }'
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b'    String s = new String("hi");\n'
            b"}\n"
        )

    def test_object_creation_with_diamond_generic(self) -> None:
        # `new ArrayList<>()` — diamond operator. Exercises
        # `_emit_generic_type` + `_emit_type_arguments` with
        # no type arguments inside `<>`.
        out = format_java.format_source(
            b"class A { List<String> ls = new ArrayList<>(); }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    List<String> ls = new ArrayList<>();\n"
            b"}\n"
        )

    def test_generic_type_with_two_args(self) -> None:
        # `Map<String, Integer>` — comma-space between type
        # arguments per the "Whitespace and Operator Spacing"
        # spec's "After commas" row, no spaces inside `<>`.
        out = format_java.format_source(
            b"class A { Map<String, Integer> m = "
            b"new HashMap<>(); }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    Map<String, Integer> m = new HashMap<>();\n"
            b"}\n"
        )

    def test_object_creation_with_scoped_type(self) -> None:
        # `new Outer.Inner()` — scoped_type_identifier emitted
        # verbatim from the source span (it's just the
        # dotted identifier path).
        out = format_java.format_source(
            b"class A { Object o = new Outer.Inner(); }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    Object o = new Outer.Inner();\n"
            b"}\n"
        )

    # --- Anonymous classes on object creation (Phase 2y / spec C8) ---

    def test_anonymous_class_empty_body(self) -> None:
        # Spec C8: same-line opening `{`, closing `}` aligned
        # with surrounding statement's indent.
        out = format_java.format_source(
            b"class A { Foo f = new Foo() { }; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    Foo f = new Foo() {\n"
            b"    };\n"
            b"}\n"
        )

    def test_anonymous_class_single_method(self) -> None:
        # Spec C8: body content uses standard class-body member
        # emission — method declarations inside an anonymous
        # body still take Allman braces (the C8 same-line-brace
        # rule applies only to the anonymous-class opening
        # brace itself, not to members inside).
        out = format_java.format_source(
            b"class A { void m() { "
            b"Runnable r = new Runnable() { "
            b"@Override public void run() { x(); } "
            b"}; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        Runnable r = new Runnable() {\n"
            b"            @Override\n"
            b"            public void run()\n"
            b"            {\n"
            b"                x();\n"
            b"            }\n"
            b"        };\n"
            b"    }\n"
            b"}\n"
        )

    def test_anonymous_class_as_call_argument(self) -> None:
        # Spec C8: the closing `}` of an anonymous-class
        # argument aligns with the surrounding statement's
        # indent, and is followed by whatever syntactic
        # terminator the call expression requires (here `);`).
        out = format_java.format_source(
            b"class A { void m() { "
            b"service.execute(new Runnable() { "
            b"public void run() { y(); } "
            b"}); } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        service.execute(new Runnable() {\n"
            b"            public void run()\n"
            b"            {\n"
            b"                y();\n"
            b"            }\n"
            b"        });\n"
            b"    }\n"
            b"}\n"
        )

    def test_anonymous_class_with_generic_type(self) -> None:
        # `new Comparator<String>() { ... }` — type is a
        # `generic_type` node, not a bare `type_identifier`;
        # verifies the type dispatch handles both shapes.
        out = format_java.format_source(
            b"class A { void m() { "
            b"Comparator<String> c = new Comparator<String>() { "
            b"public int compare(String a, String b) "
            b"{ return 0; } "
            b"}; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        Comparator<String> c = new Comparator<String>() {\n"
            b"            public int compare(String a, String b)\n"
            b"            {\n"
            b"                return 0;\n"
            b"            }\n"
            b"        };\n"
            b"    }\n"
            b"}\n"
        )

    def test_anonymous_class_mixed_fields_and_methods(self) -> None:
        # Anonymous class bodies can contain mixed members —
        # fields and methods. Standard class-body emission
        # rules apply (fields packed; one blank line between
        # the last field and the first method, NOT yet — the
        # current `_emit_class_body_members` doesn't insert
        # that blank line yet; that lands with the A2 blank-
        # line phase).
        out = format_java.format_source(
            b"class A { void m() { "
            b"Foo f = new Foo() { "
            b"int x = 1; void run() { y(); } "
            b"}; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        Foo f = new Foo() {\n"
            b"            int x = 1;\n"
            b"            void run()\n"
            b"            {\n"
            b"                y();\n"
            b"            }\n"
            b"        };\n"
            b"    }\n"
            b"}\n"
        )

    # --- Annotations (Phase 2n) ---

    def test_marker_annotation_on_class(self) -> None:
        # Spec A3: annotation on its own line above the
        # declaration, no blank between.
        out = format_java.format_source(
            b"@Override class A {}"
        )
        assert out == (
            b"@Override\n"
            b"class A\n"
            b"{\n"
            b"}\n"
        )

    def test_annotation_with_string_arg(self) -> None:
        out = format_java.format_source(
            b'@SuppressWarnings("unchecked") class A {}'
        )
        assert out == (
            b'@SuppressWarnings("unchecked")\n'
            b"class A\n"
            b"{\n"
            b"}\n"
        )

    def test_annotation_with_element_value_pair(self) -> None:
        # `@Schedule(hour = "12")` — named-argument form via
        # element_value_pair. Spec assignment-operator rule
        # gives space-space around `=`.
        out = format_java.format_source(
            b'@Schedule(hour = "12") class A {}'
        )
        assert out == (
            b'@Schedule(hour = "12")\n'
            b"class A\n"
            b"{\n"
            b"}\n"
        )

    def test_annotation_plus_keyword_modifiers_on_class(
        self,
    ) -> None:
        out = format_java.format_source(
            b"@Deprecated public class A {}"
        )
        assert out == (
            b"@Deprecated\n"
            b"public class A\n"
            b"{\n"
            b"}\n"
        )

    def test_multiple_annotations_on_class(self) -> None:
        # Spec A3: no blank line between consecutive
        # annotations; no blank line between the last
        # annotation and the declaration.
        out = format_java.format_source(
            b"@Override @Deprecated public class A {}"
        )
        assert out == (
            b"@Override\n"
            b"@Deprecated\n"
            b"public class A\n"
            b"{\n"
            b"}\n"
        )

    def test_annotation_on_method(self) -> None:
        out = format_java.format_source(
            b"class A { "
            b"@Override public String name() { return n; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    @Override\n"
            b"    public String name()\n"
            b"    {\n"
            b"        return n;\n"
            b"    }\n"
            b"}\n"
        )

    def test_multiple_annotations_on_method(self) -> None:
        out = format_java.format_source(
            b"class A { "
            b"@Override @Deprecated public void m() {} }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    @Override\n"
            b"    @Deprecated\n"
            b"    public void m()\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    def test_annotation_on_field(self) -> None:
        out = format_java.format_source(
            b"class A { @Deprecated private int x = 0; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    @Deprecated\n"
            b"    private int x = 0;\n"
            b"}\n"
        )

    def test_annotation_only_on_class_no_keyword_modifiers(
        self,
    ) -> None:
        # Annotations-only modifiers: the trailing
        # newline + write_indent positions the caller's
        # next token on the line below at the right column
        # — no stray space.
        out = format_java.format_source(
            b"@Deprecated class A {}"
        )
        assert out == (
            b"@Deprecated\n"
            b"class A\n"
            b"{\n"
            b"}\n"
        )

    # --- Comments (Phase 2o, verbatim, no reflow) ---

    def test_single_line_block_comment_above_field(self) -> None:
        out = format_java.format_source(
            b"class A { /** Field. */ int x = 1; }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    /** Field. */\n"
            b"    int x = 1;\n"
            b"}\n"
        )

    def test_single_line_block_comment_above_method(self) -> None:
        out = format_java.format_source(
            b"class A { /** Method. */ void m() {} }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    /** Method. */\n"
            b"    void m()\n"
            b"    {\n"
            b"    }\n"
            b"}\n"
        )

    def test_line_comment_in_method_body(self) -> None:
        # Line comments inside method bodies emit verbatim
        # on their own line — side-comment attachment is a
        # known limitation deferred to a later phase.
        out = format_java.format_source(
            b"class A { void m() { // a comment\n"
            b"return; } }"
        )
        assert out == (
            b"class A\n"
            b"{\n"
            b"    void m()\n"
            b"    {\n"
            b"        // a comment\n"
            b"        return;\n"
            b"    }\n"
            b"}\n"
        )

    def test_multi_line_block_comment(self) -> None:
        # Multi-line javadoc with already-balanced single-prose
        # paragraph emits unchanged at the formatter's
        # authoritative indent.
        src = (
            b"class A {\n"
            b"    /**\n"
            b"     * Multi-line.\n"
            b"     */\n"
            b"    int x = 1;\n"
            b"}"
        )
        out = format_java.format_source(src)
        assert out == (
            b"class A\n"
            b"{\n"
            b"    /**\n"
            b"     * Multi-line.\n"
            b"     */\n"
            b"    int x = 1;\n"
            b"}\n"
        )

    # --- Javadoc reflow (Phase 4b / spec "Javadoc Comments") ---

    def test_javadoc_prose_orphan_reflows(self) -> None:
        # Per the ported `fix_javadoc_reflow.py` behavior: a
        # paragraph with an awkward orphan continuation (next
        # line's first word would fit on the previous line) is
        # reflowed to fill near 80 chars.
        src = (
            b"class A {\n"
            b"    /**\n"
            b"     * The number of milliseconds to sleep between"
            b" checks on the\n"
            b"     * locks required for\n"
            b"     * tasks that have been postponed.\n"
            b"     */\n"
            b"    int x;\n"
            b"}\n"
        )
        out = format_java.format_source(src)
        assert out == (
            b"class A\n"
            b"{\n"
            b"    /**\n"
            b"     * The number of milliseconds to sleep between"
            b" checks on the locks required\n"
            b"     * for tasks that have been postponed.\n"
            b"     */\n"
            b"    int x;\n"
            b"}\n"
        )

    def test_javadoc_at_param_orphan_reflows(self) -> None:
        # `@param NAME desc` continuation lines that are
        # awkwardly short collapse to a single line when the
        # full description fits within 80 chars.
        src = (
            b"class A {\n"
            b"    /**\n"
            b"     * @param input the input value\n"
            b"     *              that controls the\n"
            b"     *              behavior of the call\n"
            b"     */\n"
            b"    int m(int input) { return 0; }\n"
            b"}\n"
        )
        out = format_java.format_source(src)
        assert out == (
            b"class A\n"
            b"{\n"
            b"    /**\n"
            b"     * @param input the input value that controls"
            b" the behavior of the call\n"
            b"     */\n"
            b"    int m(int input)\n"
            b"    {\n"
            b"        return 0;\n"
            b"    }\n"
            b"}\n"
        )

    def test_javadoc_at_param_long_name_alignment(self) -> None:
        # When a `@param NAME desc` overflows on a single line,
        # the continuation lines align with the description's
        # start column (one space past `NAME`).
        src = (
            b"class A {\n"
            b"    /**\n"
            b"     * @param connectionPoolSize the size of the"
            b" connection pool to allocate at construction"
            b" time\n"
            b"     */\n"
            b"    A(int connectionPoolSize) {}\n"
            b"}\n"
        )
        out = format_java.format_source(src)
        # The description wraps; continuation aligns with the
        # column after `@param connectionPoolSize `.
        assert b"     * @param connectionPoolSize the size of " \
            b"the connection pool to allocate at\n" in out
        assert b"     *                           construction" \
            b" time\n" in out

    def test_javadoc_pre_block_preserved_verbatim(self) -> None:
        # `<pre> ... </pre>` interior content is never reflowed,
        # even when individual lines are short.
        src = (
            b"class A {\n"
            b"    /**\n"
            b"     * <pre>\n"
            b"     *   a.foo();\n"
            b"     *   b.bar();\n"
            b"     * </pre>\n"
            b"     */\n"
            b"    int x;\n"
            b"}\n"
        )
        out = format_java.format_source(src)
        assert b"     * <pre>\n" in out
        assert b"     *   a.foo();\n" in out
        assert b"     *   b.bar();\n" in out
        assert b"     * </pre>\n" in out

    def test_javadoc_balanced_prose_preserved(self) -> None:
        # Per the orphan-or-overlong gate: a paragraph whose
        # lines all fit and have NO awkward orphan emits
        # verbatim — the formatter doesn't re-flow developer-
        # authored breaks just because the lines happen to be
        # short. Verifies fixture-02 behavior: a `{@link}` line
        # followed by a balanced prose pair stays untouched.
        src = (
            b"class A {\n"
            b"    /**\n"
            b"     * {@link Bar} is the\n"
            b"     * preferred replacement for this"
            b" deprecated class.\n"
            b"     */\n"
            b"    int x;\n"
            b"}\n"
        )
        out = format_java.format_source(src)
        assert b"     * {@link Bar} is the\n" in out
        assert b"     * preferred replacement for this " \
            b"deprecated class.\n" in out

    def test_field_with_text_block_initializer(
        self,
    ) -> None:
        # Text blocks inside an indented context shift the
        # closing `"""` to +4 from the introducing statement
        # column. Content lines move by the same delta so the
        # rendered string is byte-for-byte unchanged per spec
        # B4 content-preservation.
        out = format_java.format_source(
            b'class A { String s = """\nhello\n"""; }'
        )
        # Closing `"""` lands at column 8 (= statement column 4
        # + 4 indent), and the content line `hello` shifts by
        # the same delta from its source column.
        assert b'    String s = """\n' in out
        assert b'        hello\n        """;\n' in out


# ---------------------------------------------------------------------------
# Emitter (token-stream output buffer)
# ---------------------------------------------------------------------------


class TestEmitterBasics:
    """Verify the column/indent bookkeeping invariants."""

    def test_initial_state(self) -> None:
        e = format_java.Emitter()
        assert e.column == 0
        assert e.line_count == 0
        assert e.indent_level == 0

    def test_write_advances_column(self) -> None:
        e = format_java.Emitter()
        e.write("hello")
        assert e.column == 5
        e.write(" world")
        assert e.column == 11
        assert e.line_count == 0  # no newline yet

    def test_write_rejects_newlines(self) -> None:
        e = format_java.Emitter()
        with pytest.raises(ValueError, match="does not accept newlines"):
            e.write("line1\nline2")

    def test_newline_finalizes_line(self) -> None:
        e = format_java.Emitter()
        e.write("foo")
        e.newline()
        assert e.column == 0
        assert e.line_count == 1
        e.write("bar")
        e.newline()
        assert e.line_count == 2

    def test_indent_push_pop(self) -> None:
        e = format_java.Emitter()
        e.push_indent()
        assert e.indent_level == 1
        e.push_indent()
        assert e.indent_level == 2
        e.pop_indent()
        assert e.indent_level == 1
        e.pop_indent()
        assert e.indent_level == 0

    def test_pop_indent_below_zero_raises(self) -> None:
        e = format_java.Emitter()
        with pytest.raises(ValueError, match="indent_level=0"):
            e.pop_indent()

    def test_write_indent_at_column_zero(self) -> None:
        e = format_java.Emitter()
        e.push_indent()
        e.write_indent()
        assert e.column == 4
        e.push_indent()
        e.write("body")
        e.newline()
        e.write_indent()  # back at column 0 after newline
        assert e.column == 8

    def test_write_indent_rejects_non_empty_line(self) -> None:
        e = format_java.Emitter()
        e.write("foo")
        with pytest.raises(ValueError, match="only valid at column 0"):
            e.write_indent()


class TestEmitterWriteRawLines:
    """Verify multi-line verbatim emission preserves content."""

    def test_single_line_input_continues_current_line(self) -> None:
        e = format_java.Emitter()
        e.write_raw_lines("foo")
        assert e.column == 3
        assert e.line_count == 0

    def test_multiline_finalizes_each_line(self) -> None:
        e = format_java.Emitter()
        e.write_raw_lines("a\nb\nc")
        # 'a' and 'b' should be finalized lines; 'c' is in progress
        assert e.line_count == 2
        assert e.column == 1  # 'c'

    def test_preserves_trailing_whitespace_inside(self) -> None:
        # B4 spec — text-block content is verbatim, including
        # any developer-authored trailing whitespace.
        e = format_java.Emitter()
        e.write_raw_lines('"""\nhello   \nworld\n"""')
        out = e.finish()
        # Each line inside the literal must be preserved exactly.
        assert b'hello   \n' in out

    def test_combines_with_write_after(self) -> None:
        e = format_java.Emitter()
        e.write_raw_lines('"""\nfoo\n"""')
        # After the verbatim block ends, normal write/newline
        # should continue from the open line.
        e.write(";")
        assert e.finish() == b'"""\nfoo\n""";\n'

    def test_column_reflects_last_segment(self) -> None:
        # Column after multi-line emit should equal the length of
        # the final segment, not the total character count.
        e = format_java.Emitter()
        e.write_raw_lines("a\nbb\nccc")
        assert e.column == 3  # 'ccc'
        assert e.line_count == 2  # 'a' and 'bb' finalized

    def test_empty_string_is_noop(self) -> None:
        e = format_java.Emitter()
        e.write("prefix")
        e.write_raw_lines("")
        # No newlines + no content → line untouched.
        assert e.column == 6
        assert e.line_count == 0

    def test_bare_newline_finalizes_line(self) -> None:
        e = format_java.Emitter()
        e.write("prefix")
        e.write_raw_lines("\n")
        # The single newline commits 'prefix' and leaves an empty
        # open line.
        assert e.column == 0
        assert e.line_count == 1


class TestEmitterFinish:
    """Verify finish() produces the right byte output."""

    def test_empty_buffer_returns_empty_bytes(self) -> None:
        e = format_java.Emitter()
        assert e.finish() == b""

    def test_single_line_ends_with_one_newline(self) -> None:
        e = format_java.Emitter()
        e.write("class A {}")
        assert e.finish() == b"class A {}\n"

    def test_multiple_lines_join_with_newline(self) -> None:
        e = format_java.Emitter()
        e.write("class A")
        e.newline()
        e.write("{")
        e.newline()
        e.write("}")
        assert e.finish() == b"class A\n{\n}\n"

    def test_trailing_whitespace_stripped(self) -> None:
        e = format_java.Emitter()
        e.write("foo   ")  # trailing spaces
        e.newline()
        e.write("bar")
        assert e.finish() == b"foo\nbar\n"

    def test_trailing_empty_lines_dropped(self) -> None:
        e = format_java.Emitter()
        e.write("foo")
        e.newline()
        e.newline()
        e.newline()
        assert e.finish() == b"foo\n"

    def test_finish_finalizes_in_progress_line(self) -> None:
        e = format_java.Emitter()
        e.write("incomplete")  # never called newline()
        assert e.finish() == b"incomplete\n"


class TestEmitterTailReserve:
    """Verify the tail-reserve push/restore mechanism.

    Wrap candidates inside an `if` condition, an expression
    statement, etc. consult `Emitter.tail_reserve` to budget for
    trailing tokens (`) {`, `;`) they can't see during their
    own emission. Callers set it via `set_tail_reserve(N)`,
    which returns the previous value so they can restore it.
    """

    def test_default_zero(self) -> None:
        e = format_java.Emitter()
        assert e.tail_reserve == 0

    def test_set_tail_reserve_returns_previous(self) -> None:
        e = format_java.Emitter()
        prev = e.set_tail_reserve(2)
        assert prev == 0
        assert e.tail_reserve == 2

    def test_set_tail_reserve_restores(self) -> None:
        e = format_java.Emitter()
        e.set_tail_reserve(2)
        prev = e.set_tail_reserve(5)
        assert prev == 2
        e.set_tail_reserve(prev)
        assert e.tail_reserve == 2

    def test_set_tail_reserve_nested_push_restore(
        self,
    ) -> None:
        # Idiomatic usage: callers push a new value, do their
        # work, restore the saved previous. Multiple levels of
        # nesting should compose cleanly.
        e = format_java.Emitter()
        prev_a = e.set_tail_reserve(2)
        prev_b = e.set_tail_reserve(e.tail_reserve + 3)
        assert e.tail_reserve == 5
        e.set_tail_reserve(prev_b)
        assert e.tail_reserve == 2
        e.set_tail_reserve(prev_a)
        assert e.tail_reserve == 0


# ---------------------------------------------------------------------------
# Wrap-priority engine helpers
# ---------------------------------------------------------------------------


class TestWrapContext:
    """Verify the WrapContext dataclass.

    Threaded by the per-construct wrap helpers
    (`_emit_method_header_wrapped`, `_emit_class_header_wrapped`,
    etc.) to replace ad-hoc `start_col` arguments. The factory
    `WrapContext.at(start_col)` produces the conventional `+4`
    single-indent and `+8` double-indent continuation columns.
    """

    def test_at_uses_plus_four_and_plus_eight(self) -> None:
        ctx = format_java.WrapContext.at(8)
        assert ctx.start_col == 8
        assert ctx.indent_col == 12
        assert ctx.p3_indent_col == 16

    def test_direct_construction_with_custom_columns(
        self,
    ) -> None:
        # Callers can override the convention if a construct
        # wants a non-standard continuation column.
        ctx = format_java.WrapContext(
            start_col=4, indent_col=20, p3_indent_col=24
        )
        assert ctx.start_col == 4
        assert ctx.indent_col == 20
        assert ctx.p3_indent_col == 24

    def test_is_frozen(self) -> None:
        # Frozen dataclass — mutations should fail. Pinning
        # this invariant guards against accidental aliasing
        # bugs in wrap helpers that pass the same ctx down
        # multiple recursion levels.
        #
        # Python 3.11+ raises `FrozenInstanceError` from
        # `dataclasses`; earlier 3.10 still raises a plain
        # `AttributeError`. The narrow catch ensures an
        # unrelated typo or import error in the test doesn't
        # silently pass this assertion.
        ctx = format_java.WrapContext.at(0)
        with pytest.raises(
            (dataclasses.FrozenInstanceError, AttributeError)
        ):
            ctx.start_col = 99  # type: ignore[misc]

    def test_uses_slots_no_dict(self) -> None:
        # `slots=True` keeps WrapContext small (used in deep
        # recursion). Verify there's no `__dict__`.
        ctx = format_java.WrapContext.at(0)
        assert not hasattr(ctx, "__dict__")


class TestTryPriorities:
    """Verify the try_priorities wrap-priority engine.

    Each candidate emits via the shared emitter; the engine
    rolls back between candidates and commits the first one
    whose output stays within `_MAX_LINE - tail_reserve`.
    Falls back to the last candidate when all overflow (the
    spec C1 "emit + warn" rule).
    """

    def test_commits_first_candidate_that_fits(self) -> None:
        e = format_java.Emitter()

        def p1() -> None:
            e.write("short")

        def p2() -> None:
            e.write("x" * 100)

        index = format_java.try_priorities(e, [p1, p2])
        assert index == 0
        assert e.finish() == b"short\n"

    def test_falls_through_to_later_candidates(self) -> None:
        e = format_java.Emitter()

        def p1() -> None:
            e.write("x" * 100)  # overflow

        def p2() -> None:
            e.write("ok")

        index = format_java.try_priorities(e, [p1, p2])
        assert index == 1
        assert e.finish() == b"ok\n"

    def test_commits_last_when_all_overflow(self) -> None:
        # spec C1: emit + warn — when no candidate fits, the
        # last one is left committed rather than refused.
        # Both candidates emit past `_MAX_LINE`; the test
        # references the constant so it remains correct if
        # the line-length cap is ever changed.
        e = format_java.Emitter()
        long_first = "a" * (format_java._MAX_LINE + 10)
        long_last = "b" * (format_java._MAX_LINE + 20)

        def p1() -> None:
            e.write(long_first)

        def p2() -> None:
            e.write(long_last)

        index = format_java.try_priorities(e, [p1, p2])
        assert index == 1
        assert e.finish() == (long_last + "\n").encode("utf-8")

    def test_buffer_rolled_back_between_candidates(
        self,
    ) -> None:
        # Partial output from a failed candidate must not leak
        # into the committed output.
        e = format_java.Emitter()

        def p1() -> None:
            e.write("PARTIAL")
            e.write("x" * 80)  # combined: overflow

        def p2() -> None:
            e.write("CLEAN")

        format_java.try_priorities(e, [p1, p2])
        out = e.finish()
        assert b"PARTIAL" not in out
        assert out == b"CLEAN\n"

    def test_respects_tail_reserve(self) -> None:
        # With `tail_reserve = 5`, the effective max is
        # `_MAX_LINE - 5`, so an emission of `_MAX_LINE - 2`
        # chars overflows and should fall through to the next
        # candidate. Anchored to the constant so the test
        # stays correct if `_MAX_LINE` is ever changed.
        reserve = 5
        e = format_java.Emitter()
        e.set_tail_reserve(reserve)

        def p1() -> None:
            e.write("x" * (format_java._MAX_LINE - 2))

        def p2() -> None:
            e.write("y" * (format_java._MAX_LINE - reserve - 5))

        index = format_java.try_priorities(e, [p1, p2])
        assert index == 1

    def test_preserves_prior_buffer_state(self) -> None:
        # Content emitted BEFORE try_priorities is not touched
        # by rollback — only the speculative emissions are
        # rolled back.
        e = format_java.Emitter()
        e.write("PREFIX ")

        def p1() -> None:
            e.write("y" * 80)  # overflow

        def p2() -> None:
            e.write("ok")

        format_java.try_priorities(e, [p1, p2])
        assert e.finish() == b"PREFIX ok\n"


# ---------------------------------------------------------------------------
# Leaf-node dispatch
# ---------------------------------------------------------------------------


def _find_first(node, type_name: str):
    """Return the first descendant of `node` with the given type."""
    if node.type == type_name:
        return node
    for child in node.children:
        found = _find_first(child, type_name)
        if found is not None:
            return found
    return None


@pytest.mark.parametrize("src_bytes, node_type, expected", [
    (b"class A { int x = 42; }",
     "decimal_integer_literal", "42"),
    (b"class A { long L = 0xffL; }",
     "hex_integer_literal", "0xffL"),
    (b"class A { int o = 077; }",
     "octal_integer_literal", "077"),
    (b"class A { int b = 0b1010; }",
     "binary_integer_literal", "0b1010"),
    (b"class A { double d = 1.5e-3; }",
     "decimal_floating_point_literal", "1.5e-3"),
    (b"class A { char c = 'a'; }",
     "character_literal", "'a'"),
    (b'class A { String s = "hello"; }',
     "string_literal", '"hello"'),
    (b"class A { Object o = null; }",
     "null_literal", "null"),
    (b"class A { boolean b = true; }",
     "true", "true"),
    (b"class A { boolean b = false; }",
     "false", "false"),
    (b"class A { void m() { this.x = 1; } }",
     "this", "this"),
    (b"class A { void m() { super.x = 1; } }",
     "super", "super"),
    # The first identifier in any class declaration is the class
    # name, which gives a stable target across grammar versions.
    (b"class HelloWorld {}",
     "identifier", "HelloWorld"),
    (b"class A { String s; }",
     "type_identifier", "String"),
    # Triple-quoted text blocks (Java 15+) are still 'string_literal'
    # in the tree-sitter-java grammar. The leaf emitter re-indents
    # contents so the closing `"""` lands at +4 from the introducing
    # column. For this raw-emitter test the indent_level is 0 and
    # the source already has the closing `"""` at col 4, so the
    # rendered output matches the source byte-for-byte (delta == 0).
    (b'class A { String s = """\n    block\n    """; }',
     "string_literal", '"""\n    block\n    """'),
])
def test_leaf_emit_writes_verbatim(
    src_bytes: bytes, node_type: str, expected: str
) -> None:
    """Each registered leaf emitter writes the node's source text."""
    tree = format_java.parse_source(src_bytes)
    assert not format_java.has_parse_errors(tree)
    node = _find_first(tree.root_node, node_type)
    assert node is not None, f"no {node_type!r} node in {src_bytes!r}"

    emitter = format_java.Emitter()
    format_java._emit_node(emitter, src_bytes, node)
    assert emitter.finish() == (expected + "\n").encode("utf-8")


class TestFormatterWarnings:
    """Cover the formatter's non-blocking advisory channel.

    `format_source(source, warnings_out=...)` populates the
    supplied list with `FormatterWarning` records for layout
    corner cases the formatter cannot fully canonicalize
    (currently: source-preserved arg lists whose continuation
    columns fall below the surrounding indent level — the
    string-literal-with-low-author-chosen-break shape).

    The advisory is informational only; the formatter still
    emits an 80-char-compliant layout. The warning surfaces to
    stderr via `format_file.py` / `format_java.py --format` so
    adopters know which spots warrant manual literal splitting.
    """

    def test_no_warning_for_canonical_code(self) -> None:
        src = (
            b"public class A {\n"
            b"    void m() { f(x); }\n"
            b"}\n"
        )
        warnings: list[format_java.FormatterWarning] = []
        format_java.format_source(src, warnings_out=warnings)
        assert warnings == []

    def test_warning_for_source_preserve_overflow(self) -> None:
        # Under 0.5.0 item 4: source-preserve column-remaps the
        # arg list to `block + 4`. When the contained string
        # literal is long enough that the remapped line still
        # exceeds 80 chars, the formatter fires a
        # `FormatterWarning` advisory (the literal can't be
        # split by the formatter — that's a developer code
        # change). The line will overflow on disk; checkstyle
        # is expected to surface the LineLength violation, and
        # the advisory tells the developer which site to split.
        src = (
            b"public class A {\n"
            b"    void m() {\n"
            b"        if (true) {\n"
            b"            if (true) {\n"
            b"                throw new RuntimeException(\n"
            b'      "some quite long error message that the developer authored at low column");\n'
            b"            }\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )
        warnings: list[format_java.FormatterWarning] = []
        format_java.format_source(src, warnings_out=warnings)
        # Exactly one overflow-advisory site in this input;
        # the uniqueness filter ensures we see it once even
        # if the wrap-engine speculates over the same node at
        # multiple indent levels.
        assert len(warnings) == 1
        # Under 0.5.2 F, source-preserve declines when a
        # shift-up would overflow: this input (source at col
        # 6, target col deeper) falls through to the wrap
        # engine, which fires the "argument list could not
        # fit within 80 chars" advisory. Pinning the wrap-
        # engine message ensures a regression that re-enabled
        # the mechanical shift-up (which would fire the older
        # "source-preserved arg list overflows" message
        # instead) would be caught.
        for warning in warnings:
            assert warning.line > 0
            assert warning.column > 0
            assert "argument list" in warning.message
            assert (
                "could not fit within 80 chars" in warning.message
            )

    def test_warning_for_binary_wrap_overflow(self) -> None:
        # Item 11: when the binary cascade commits its C1
        # emit + warn fallback with a line wider than 80
        # chars, a `FormatterWarning` advisory fires. Driven
        # by a long string literal that doesn't fit at any
        # break point the wrap engine can choose.
        src = (
            b"public class A {\n"
            b"    void m() {\n"
            b"        if (this.isClosed()) {\n"
            b"            throw new IllegalStateException(\n"
            b'                "This WorkerThreadPool has already been marked '
            b'as closed and the "\n'
            b'                    + "threads have been shutdown.");\n'
            b"        }\n"
            b"    }\n"
            b"}\n"
        )
        warnings: list[format_java.FormatterWarning] = []
        format_java.format_source(src, warnings_out=warnings)
        assert len(warnings) >= 1
        sites = [w.message for w in warnings]
        assert any(
            "binary expression wrap could not fit" in m
            for m in sites
        )

    def test_warnings_unique_by_source_position(self) -> None:
        # Speculative wrap-engine emits can revisit the same
        # arg-list at different indent_level values; the
        # advisory must be made unique by (line, column) so the
        # developer doesn't see duplicate hits.
        src = (
            b"public class A {\n"
            b"    void m() {\n"
            b"        if (true) {\n"
            b"            if (true) {\n"
            b"                throw new RuntimeException(\n"
            b'      "some quite long error message that the developer authored at low column");\n'
            b"            }\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )
        warnings: list[format_java.FormatterWarning] = []
        format_java.format_source(src, warnings_out=warnings)
        # Sanity: the input intentionally triggers the
        # advisory, so we expect at least one warning — an
        # empty list would make the uniqueness assertion
        # vacuously true and mask a regression where the
        # advisory stops firing entirely.
        assert len(warnings) >= 1
        positions = [(w.line, w.column) for w in warnings]
        assert len(positions) == len(set(positions))

    def test_warning_for_assignment_expression_overflow(self) -> None:
        # 0.6.0: `_emit_assignment_expression` mirrors
        # `_emit_variable_declarator`'s Step 3 backtrack pattern
        # and fires the C1 emit-and-warn advisory when the
        # committed break-at-`=` shape still overflows because
        # the RHS cannot be broken further (long literal). The
        # input below is a bare re-assignment (`msg = "…";`) at
        # deep indent — inline overflows, break-at-`=` also
        # overflows because the string literal cannot be split
        # by the formatter, so the advisory fires.
        src = (
            b"public class A {\n"
            b"    void m() {\n"
            b"        String msg = null;\n"
            b"        if (true) {\n"
            b"            if (true) {\n"
            b"                msg "
            b'= "a quite long string literal that the developer '
            b'placed at a low column";\n'
            b"            }\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )
        warnings: list[format_java.FormatterWarning] = []
        format_java.format_source(src, warnings_out=warnings)
        assert len(warnings) >= 1
        sites = [w.message for w in warnings]
        assert any(
            "assignment wrap could not fit" in m for m in sites
        )

    def test_warning_for_variable_declarator_overflow(self) -> None:
        # 0.6.0: `_emit_variable_declarator` fires the C1
        # emit-and-warn advisory when its break-at-`=` shape
        # still overflows (matches assignment_expression's
        # sibling behavior). The input is a
        # variable_declarator at deep indent whose RHS is a
        # single atomic literal.
        src = (
            b"public class A {\n"
            b"    void m() {\n"
            b"        if (true) {\n"
            b"            if (true) {\n"
            b"                String s "
            b'= "a quite long string literal that the developer '
            b'placed at a low column";\n'
            b"            }\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )
        warnings: list[format_java.FormatterWarning] = []
        format_java.format_source(src, warnings_out=warnings)
        assert len(warnings) >= 1
        sites = [w.message for w in warnings]
        assert any(
            "variable declarator wrap could not fit" in m
            for m in sites
        )

    def test_warning_omits_when_warnings_out_is_none(self) -> None:
        # API contract: when caller doesn't supply
        # `warnings_out`, format_source still emits formatted
        # output normally; the warnings are simply discarded.
        src = (
            b"public class A {\n"
            b"    void m() {\n"
            b"        if (true) {\n"
            b"            if (true) {\n"
            b"                throw new RuntimeException(\n"
            b'      "some quite long error message that the developer authored at low column");\n'
            b"            }\n"
            b"        }\n"
            b"    }\n"
            b"}\n"
        )
        # No exception, just discards the warnings.
        format_java.format_source(src)


class TestAnnotationTypeDeclaration:
    """Cover `_emit_annotation_type_declaration` and
    `_emit_annotation_type_element_declaration` end-to-end via
    `format_source`. The fixture harness exercises golden-file
    equality; these unit tests pin specific shape decisions
    (Allman brace, no body padding for empty types, the
    `default` clause, modifier preservation) without depending
    on the full fixture infrastructure.
    """

    def test_empty_annotation_type_uses_allman_brace(self) -> None:
        # Bare `@interface` with no members should emit the
        # Allman brace shape with no body padding — the inside
        # of `{` and `}` is empty, with `}` on its own line.
        src = b"public @interface Empty {}\n"
        out = format_java.format_source(src)
        assert out == (
            b"public @interface Empty\n"
            b"{\n"
            b"}\n"
        )

    def test_element_with_default_clause(self) -> None:
        # Element-shape emitter must produce `TYPE NAME() default
        # VALUE;` with single spaces around `default` and no space
        # before the `()` parameter list.
        src = (
            b"public @interface Configured {\n"
            b'    String value() default "";\n'
            b"}\n"
        )
        out = format_java.format_source(src)
        assert out == (
            b"public @interface Configured\n"
            b"{\n"
            b'    String value() default "";\n'
            b"}\n"
        )

    def test_element_without_default_clause(self) -> None:
        # Required elements (no `default`) emit `TYPE NAME();`
        # with no trailing `default` token.
        src = (
            b"public @interface Required {\n"
            b"    String name();\n"
            b"}\n"
        )
        out = format_java.format_source(src)
        assert out == (
            b"public @interface Required\n"
            b"{\n"
            b"    String name();\n"
            b"}\n"
        )

    def test_multiple_elements_mix_required_and_defaulted(
        self,
    ) -> None:
        # Mixed element list with primitive default, string
        # default, and a required (no-default) element — covers
        # the dispatch through several value-expression shapes.
        src = (
            b"public @interface Config {\n"
            b'    String value() default "";\n'
            b"    int priority() default 0;\n"
            b"    Class<?>[] types();\n"
            b"}\n"
        )
        out = format_java.format_source(src)
        assert out == (
            b"public @interface Config\n"
            b"{\n"
            b'    String value() default "";\n'
            b"    int priority() default 0;\n"
            b"    Class<?>[] types();\n"
            b"}\n"
        )

    def test_modifiers_and_meta_annotations_preserved(self) -> None:
        # Modifiers on an annotation type include both keyword
        # modifiers (e.g. `public`) and meta-annotations applied
        # to the annotation type itself (`@Retention(...)`). All
        # of them must survive the format pass and stay one-
        # annotation-per-line above the declaration.
        src = (
            b"import java.lang.annotation.Retention;\n"
            b"import java.lang.annotation.RetentionPolicy;\n"
            b"\n"
            b"@Retention(RetentionPolicy.RUNTIME)\n"
            b"public @interface Marker {}\n"
        )
        out = format_java.format_source(src)
        assert out == (
            b"import java.lang.annotation.Retention;\n"
            b"import java.lang.annotation.RetentionPolicy;\n"
            b"\n"
            b"@Retention(RetentionPolicy.RUNTIME)\n"
            b"public @interface Marker\n"
            b"{\n"
            b"}\n"
        )


class TestEmitNodeDispatch:
    """Verify the dispatch helper's error path."""

    def test_unknown_node_type_raises(self) -> None:
        # `module_declaration` is intentionally out-of-scope for
        # 0.3.0 (see the plan's "Out of scope: module-info.java")
        # — no consumer project uses Java modules, and the
        # grammar diverges enough to deserve its own phase. The
        # dispatcher's refusal path is exercised by trying to
        # emit a module declaration: `No emitter registered`.
        src = (
            b"module com.foo { requires java.base; }"
        )
        tree = format_java.parse_source(src)
        stmt = _find_first(tree.root_node, "module_declaration")
        assert stmt is not None
        emitter = format_java.Emitter()
        with pytest.raises(
            NotImplementedError, match="No emitter registered"
        ):
            format_java._emit_node(emitter, src, stmt)

    # block is now a registered emitter (Phase 2i) for the
    # control-flow same-line-brace form. Method-declaration
    # bodies continue to be emitted inline by
    # `_emit_method_declaration` (Allman form), which doesn't
    # dispatch through `block`. The former
    # `test_block_not_yet_handled` is dropped now that the
    # dispatch is registered.


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    script = (
        Path(__file__).resolve().parent.parent / "format_java.py"
    )
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class TestCli:
    """Exercise the script's CLI surface end-to-end."""

    def test_check_grammar_succeeds(self) -> None:
        result = _run_cli(["--check-grammar"])
        assert result.returncode == 0, result.stderr
        assert "grammar OK" in result.stdout

    def test_version_reports_pin(self) -> None:
        result = _run_cli(["--version"])
        assert result.returncode == 0
        assert format_java.__version__ in result.stdout
        assert (
            format_java.GRAMMAR_VERSION["tree-sitter-java"]
            in result.stdout
        )

    def test_no_args_exits_nonzero(self) -> None:
        # format_java.py is deliberately not the end-user entry
        # point during incremental rollout — running with no
        # flags must fail loudly rather than silently no-op or
        # damage the input.
        result = _run_cli([])
        assert result.returncode != 0
        assert "not the end-user formatter entry point" in (
            result.stderr.lower()
        )

    def test_parse_unknown_file_exits_nonzero(
        self, tmp_path: Path
    ) -> None:
        missing = tmp_path / "does_not_exist.java"
        result = _run_cli(["--parse", str(missing)])
        assert result.returncode != 0
        assert "no such file" in result.stderr.lower()

    def test_parse_clean_file(self, tmp_path: Path) -> None:
        java = tmp_path / "OK.java"
        java.write_text(
            "public class OK { public int x = 1; }\n",
            encoding="utf-8",
        )
        result = _run_cli(["--parse", str(java)])
        assert result.returncode == 0, result.stderr
        assert "clean" in result.stdout
        assert "root=program" in result.stdout

    def test_parse_broken_file_writes_error_to_stderr(
        self, tmp_path: Path
    ) -> None:
        java = tmp_path / "Broken.java"
        java.write_text(
            "public class Broken { public void run() {\n",
            encoding="utf-8",
        )
        result = _run_cli(["--parse", str(java)])
        assert result.returncode != 0
        # The diagnostic line itself should be on stderr, not just
        # the word "errors" — verifies the routing decision in
        # format_java.py:_main() rather than incidental output.
        assert f"parsed {java}" in result.stderr
        assert "errors)" in result.stderr
        # The success diagnostic should NOT be on stdout when the
        # parse failed — that's the asymmetry the routing fixes.
        assert "clean" not in result.stdout
        assert f"parsed {java}" not in result.stdout


# ---------------------------------------------------------------------------
# Nested-call wrap helpers (0.7.0)
# ---------------------------------------------------------------------------


def _first_arg_list_of(snippet: str):
    """Return the FIRST `argument_list` node in a method body.

    `snippet` is a single statement; it is wrapped in a minimal
    class so it parses. Pre-order search means the outermost call's
    argument list is found first, which is the node the nested-call
    predicates are asked about.
    """
    src = (
        "class A { void m() { " + snippet + " } }"
    ).encode()
    tree = format_java.parse_source(src)
    found = []

    def visit(node) -> None:
        if node.type == "argument_list":
            found.append(node)
        for child in node.children:
            visit(child)

    visit(tree.root_node)
    assert found, f"no argument_list parsed from: {snippet}"
    return found


class TestIsNestedOrChainedCall:
    """Lock the traversal in `_is_nested_or_chained_call`.

    The predicate decides where the 0.7.0 nested-call rules apply,
    so its coverage is a behavioral contract rather than an
    implementation detail. The False cases are as important as the
    True ones: each is a parent shape the rules deliberately do NOT
    reach, and a silent change there would widen the rules without
    anyone noticing.
    """

    @pytest.mark.parametrize(
        "snippet, expected",
        [
            # Positional argument of another call.
            ("outer(inner(a, b));", True),
            ("outer(x, inner(a, b));", True),
            # Receiver of a method chain.
            ("builder(a, b).build();", True),
            # Constructors count as calls in both positions.
            ("outer(new Foo(a, b));", True),
            ("new Foo(a, b).bar();", True),
            # An EXPRESSION-bodied lambda is transparent: the inner
            # call is still embedded in `run(…)`, and the reader
            # still has to track both at once.
            ("run(() -> inner(a, b));", True),
            ("run(x, () -> inner(a, b));", True),
            ("run(() -> new Foo(a, b));", True),
            # Curried lambdas resolve to the enclosing construct.
            ("run(a -> b -> inner(a, b));", True),
            # A BLOCK-bodied lambda is opaque: the call is a
            # statement at its own indent, sharing its line with
            # nothing, so the greedy shapes read fine.
            ("run(() -> { inner(a, b); });", False),
            ("run(() -> { var y = inner(a, b); });", False),
            # A lambda that is not itself embedded stays False.
            ("var f = () -> inner(a, b);", False),
            # Parent shapes the rules deliberately do not reach.
            ("var x = (inner(a, b));", False),
            ("var x = (Cast) inner(a, b);", False),
            ("var x = flag ? inner(a, b) : other;", False),
            ("var x = inner(a, b) + other;", False),
            ("var x = inner(a, b).field;", False),
            ("var x = inner(a, b)[0];", False),
            ("inner(a, b);", False),
        ],
    )
    def test_traversal(self, snippet: str, expected: bool) -> None:
        arg_lists = _first_arg_list_of(snippet)
        # The OUTERMOST argument_list is the one under test for the
        # False cases (a bare statement call, a cast, etc.); for the
        # True cases the inner call's list is what qualifies. Assert
        # that SOME list matches for True and NONE for False.
        results = [
            format_java._is_nested_or_chained_call(node)
            for node in arg_lists
        ]
        assert any(results) is expected, (
            f"{snippet!r} -> {results}"
        )

    def test_never_raises_on_detached_node(self) -> None:
        """A `program`-rooted argument list has no owning call."""
        tree = format_java.parse_source(b"class A { }")
        assert (
            format_java._is_nested_or_chained_call(tree.root_node)
            is False
        )


class TestIsAnonymousClass:
    """`new Foo() { … }` owns its rows; `new Foo()` does not."""

    def test_anonymous_class_detected(self) -> None:
        tree = format_java.parse_source(
            b"class A { void m() { "
            b"run(new Runnable() { public void r() { } }); } }"
        )
        found = []

        def visit(node) -> None:
            if node.type == "object_creation_expression":
                found.append(node)
            for child in node.children:
                visit(child)

        visit(tree.root_node)
        assert found
        assert format_java._is_anonymous_class(found[0]) is True

    def test_plain_constructor_is_not_anonymous(self) -> None:
        tree = format_java.parse_source(
            b"class A { void m() { run(new Foo(a)); } }"
        )
        found = []

        def visit(node) -> None:
            if node.type == "object_creation_expression":
                found.append(node)
            for child in node.children:
                visit(child)

        visit(tree.root_node)
        assert found
        assert format_java._is_anonymous_class(found[0]) is False

    def test_non_creation_node_is_not_anonymous(self) -> None:
        tree = format_java.parse_source(b"class A { }")
        assert (
            format_java._is_anonymous_class(tree.root_node) is False
        )


class TestGroupInlineTags:
    """`{@tag …}` runs become one atomic token — when they fit."""

    def test_link_with_signature_is_one_token(self) -> None:
        words = "call to {@link Foo#bar(int, Map)} now".split()
        assert format_java._group_inline_tags(words, 60) == [
            "call", "to", "{@link Foo#bar(int, Map)}", "now",
        ]

    def test_nested_braces_close_by_depth(self) -> None:
        words = "see {@code {a, b}} here".split()
        assert format_java._group_inline_tags(words, 60) == [
            "see", "{@code {a, b}}", "here",
        ]

    def test_oversize_tag_is_left_split(self) -> None:
        """Grouping a tag wider than the budget would overflow the
        line, which no later tier could repair — so it stays split."""
        words = "x {@link Very#long(Signature, Here)} y".split()
        assert format_java._group_inline_tags(words, 12) == words

    def test_tag_spanning_two_words_is_joined(self) -> None:
        words = "a {@code x} b".split()
        assert format_java._group_inline_tags(words, 60) == [
            "a", "{@code x}", "b",
        ]

    def test_self_contained_tag_untouched(self) -> None:
        """Already one token, so depth never opens."""
        words = "a {@code} b".split()
        assert format_java._group_inline_tags(words, 60) == words

    def test_unterminated_tag_does_not_consume_rest(self) -> None:
        words = "a {@link Foo bar baz".split()
        assert format_java._group_inline_tags(words, 60) == words


class TestSplitsInlineTag:
    """Detect a `{@…}` opening on one line and closing on another."""

    @pytest.mark.parametrize(
        "lines, expected",
        [
            (["a {@link", "Foo} b"], True),
            (["a {@link Foo} b"], False),
            (["a", "b"], False),
            (["{@code {x,", "y}}"], True),
            (["plain", "{@link Foo} tail"], False),
            # Prose braces are not a tag: counting every brace
            # reported a split here and refused good candidates.
            (["the set {a,", "b} of things"], False),
            # A nested body closes where it REALLY closes —
            # cancelling on the first `}` called these unsplit.
            (["{@code new int[]{1, 2}", "}"], True),
            (["{@code {a, b}", "tail}"], True),
            (["{@code Map<K, {V}>", "extra}"], True),
        ],
    )
    def test_detection(
        self, lines: list[str], expected: bool
    ) -> None:
        assert format_java._splits_inline_tag(lines) is expected


class TestMinRaggedLines:
    """Minimum-raggedness fill charges the LAST line too."""

    def test_equalizes_rather_than_packing(self) -> None:
        """Greedy packs 3/3/1 and strands a lone token; charging
        the last line's slack too spreads it 2/2/3 instead."""
        tokens = ["aaaa"] * 7
        assert format_java._greedy_fill(tokens, 14) == [
            "aaaa aaaa aaaa", "aaaa aaaa aaaa", "aaaa",
        ]
        assert format_java._min_ragged_lines(tokens, 14, 3) == [
            "aaaa aaaa", "aaaa aaaa", "aaaa aaaa aaaa",
        ]

    def test_uses_fewer_lines_when_they_suffice(self) -> None:
        """Balance never buys evenness at the cost of a line: six
        tokens fit two full lines, so two is the answer."""
        assert format_java._min_ragged_lines(["aaaa"] * 6, 14, 3) == [
            "aaaa aaaa aaaa", "aaaa aaaa aaaa",
        ]

    def test_respects_the_hard_cap(self) -> None:
        lines = format_java._min_ragged_lines(["aaaa"] * 7, 14, 3)
        assert all(len(line) <= 14 for line in lines)

    def test_never_exceeds_max_lines(self) -> None:
        lines = format_java._min_ragged_lines(["aaaa"] * 7, 14, 3)
        assert len(lines) <= 3

    def test_empty_input(self) -> None:
        assert format_java._min_ragged_lines([], 40, 3) == []

    def test_infeasible_returns_none(self) -> None:
        """Six 4-char tokens cannot be placed in one 14-char line."""
        assert (
            format_java._min_ragged_lines(["aaaa"] * 6, 14, 1)
            is None
        )

    def test_oversize_token_gets_its_own_line(self) -> None:
        """Per spec C1 the overflow is emitted and warned, not
        looped on — so a solution must still be produced."""
        tokens = ["short", "x" * 40, "tail"]
        lines = format_java._min_ragged_lines(tokens, 20, 3)
        assert lines is not None
        assert "x" * 40 in lines


class TestJavadocBalancedReflow:
    """0.7.0's layout is the FLOOR: the candidate is adopted only
    when it strictly improves, so this can never regress."""

    PREFIX = "     * "

    def _legacy(self, words: list[str]) -> list[str]:
        return format_java._balanced_reflow_words(
            words,
            format_java._MAX_LINE - len(self.PREFIX),
            only_when_orphaned=True,
        )

    def test_three_line_orphan_is_distributed(self) -> None:
        text = (
            "Returns the total number of milliseconds that elapsed "
            "from the moment this batch was first created until the "
            "point at which it was finally closed."
        )
        words = text.split()
        legacy = self._legacy(words)
        new = format_java._javadoc_balanced_reflow(
            words, self.PREFIX
        )
        assert len(legacy) == 3
        assert len(legacy[-1].split()) == 1        # the orphan
        assert new != legacy
        assert len(new) == 3                       # costs no line
        assert len(new[-1].split()) > 3            # orphan gone

    def test_split_inline_tag_is_joined(self) -> None:
        words = (
            "The identifier of the {@link SampleRequestHandler} "
            "that accepted this particular request."
        ).split()
        legacy = self._legacy(words)
        new = format_java._javadoc_balanced_reflow(
            words, self.PREFIX
        )
        assert format_java._splits_inline_tag(legacy)
        assert not format_java._splits_inline_tag(new)

    def test_paragraph_without_orphan_is_left_alone(self) -> None:
        """No orphan and no split tag means nothing to fix —
        rewriting it would churn a code base to buy nothing."""
        words = (
            "The number of milliseconds to sleep between checks on "
            "the locks required for tasks that have been postponed."
        ).split()
        assert format_java._javadoc_balanced_reflow(
            words, self.PREFIX
        ) == self._legacy(words)

    def test_never_costs_a_line(self) -> None:
        for text in (
            "Returns the total number of milliseconds that elapsed "
            "from the moment this batch was first created until the "
            "point at which it was finally closed.",
            "The identifier of the {@link SampleRequestHandler} "
            "that accepted this particular request.",
            "Indicates whether the pending request should be "
            "retried automatically after a transient failure has "
            "been detected by the surrounding retry policy.",
        ):
            words = text.split()
            new = format_java._javadoc_balanced_reflow(
                words, self.PREFIX
            )
            assert len(new) <= len(self._legacy(words))
            assert all(
                len(line)
                <= format_java._MAX_LINE - len(self.PREFIX)
                for line in new
            )

    def test_unstable_candidate_is_rejected(self) -> None:
        """A candidate that puts a long tag at the head of a line
        can change how the NEXT pass groups the paragraph, because
        `_emit_javadoc_block` splits there. Such a candidate is
        refused however good it looks."""
        words = (
            "Checks whether this element can be merged with other "
            "mergeable elements that are identical to it for a "
            "single call to "
            "{@link SampleHandler#handleElement(String, Map, int, "
            "Registry)} with an incrementally increased "
            "multiplicity."
        ).split()
        assert format_java._javadoc_balanced_reflow(
            words, self.PREFIX
        ) == self._legacy(words)

    def test_stability_check_sees_the_oscillation(self) -> None:
        """The rejected layout above really is unstable — replaying
        one pass over it does not reproduce it."""
        candidate = [
            "Checks whether this element can be merged with other",
            "mergeable elements that are identical to it for a",
            "single call to",
            "{@link SampleHandler#handleElement(String, Map, int, "
            "Registry)}",
            "with an incrementally increased multiplicity.",
        ]
        assert not format_java._javadoc_reflow_is_stable(
            candidate, self.PREFIX
        )


class TestJavadocReflowIsBoundary:
    """A candidate line that would end a prose run on the next pass.

    Mirrors both boundary mechanisms in `_emit_javadoc_block`. The
    `@`-block-tag case is the one that matters: modelling only the
    `{@`/`<` starters let reflow move a word like `@Override` to the
    head of a line, which the next pass read as structural and
    repacked around — output becoming a function of previous output.
    """

    @pytest.mark.parametrize(
        "line, expected",
        [
            ("{@link Foo} leads the line", True),
            ("<p>", True),
            ("<li>an item", True),
            ("@Override so the compiler can verify", True),
            ("@param name The thing", True),
            ("  an indent of its own is structural", True),
            ("", True),
            ("ordinary prose continues here", False),
            ("prose mentioning {@link Foo} mid-line", False),
            ("prose mentioning @Override mid-line", False),
        ],
    )
    def test_boundary(self, line: str, expected: bool) -> None:
        assert (
            format_java._javadoc_reflow_is_boundary(line) is expected
        )

    def test_agrees_with_the_prose_predicate(self) -> None:
        """Every non-prose line is a boundary, by construction."""
        for line in (
            "@since 1.0", "<ul>", "  hanging", "CSOFF: LineLength",
        ):
            assert not format_java._javadoc_is_prose_line(line)
            assert format_java._javadoc_reflow_is_boundary(line)


class TestTagDescriptionSkipsStabilityCheck:
    """`@param`/`@return`/`@throws` descriptions are re-flattened by
    their own handler rather than split at `{@`/`<`/`@`, so the
    prose-path stability check does not apply to them."""

    PREFIX = "     *                  "

    WORDS = (
        "The principle to filter on which can be <code>null</code> "
        "to indicate only the counts not associated with a specific "
        "principle should be included, or <code>\"*\"</code> to "
        "indicate no filtering, or a specific principle."
    ).split()

    def test_skip_changes_the_outcome(self) -> None:
        """Guards the flag: with the check applied this candidate is
        refused, so the two calls must differ."""
        with_skip = format_java._javadoc_balanced_reflow(
            self.WORDS, self.PREFIX, splits_at_boundaries=False
        )
        with_check = format_java._javadoc_balanced_reflow(
            self.WORDS, self.PREFIX, splits_at_boundaries=True
        )
        assert with_skip != with_check

    def test_skip_still_respects_the_floor(self) -> None:
        """Skipping the stability check does not skip the floor: no
        extra line, nothing over budget."""
        max_content = format_java._MAX_LINE - len(self.PREFIX)
        legacy = format_java._balanced_reflow_words(
            self.WORDS, max_content, only_when_orphaned=True
        )
        result = format_java._javadoc_balanced_reflow(
            self.WORDS, self.PREFIX, splits_at_boundaries=False
        )
        assert len(result) <= len(legacy)
        assert all(len(line) <= max_content for line in result)
        assert sorted(" ".join(result).split()) == sorted(self.WORDS)


class TestDeclarationSemicolonReserve:
    """A declaration's value must wrap knowing a `;` follows it.

    The declarator cascade's own tier checks always added `+ 1` for
    the semicolon, but those only choose between shapes — the
    value's INTERNAL wrap engine saw only `tail_reserve`, packed to
    exactly 80, and the `;` landed in column 81. The result was
    idempotent, so it survived every reformat and silently turned
    compliant source non-compliant.
    """

    def _format(self, body: str) -> list[str]:
        src = (
            "public class T\n{\n    void t()\n    {\n"
            + body
            + "\n    }\n}\n"
        ).encode()
        out = format_java.format_source(src, warnings_out=[])
        return out.decode().split("\n")

    def test_semicolon_does_not_land_in_column_81(self) -> None:
        lines = self._format(
            "        String fromStatic = SpecifiedOption"
            ".sourceDescriptor(COMMAND_LINE, CONFIG, \"--config\");"
        )
        assert all(len(line) <= 80 for line in lines), [
            (len(x), x) for x in lines if len(x) > 80
        ]

    def test_still_reports_a_value_with_no_split_point(
        self,
    ) -> None:
        """The reserve fixes off-by-one overflow, not impossibility.
        A single over-long token must still emit-and-warn — and the
        warning must be the declarator's own, not any warning from
        anywhere in the file."""
        warnings: list[object] = []
        src = (
            "public class T\n{\n    void t()\n    {\n"
            "        String single = "
            "ThisIsOneExtremelyLongAtomicIdentifierThatCannot"
            "BeSplitAnywhereAtAllEver;\n    }\n}\n"
        ).encode()
        format_java.format_source(src, warnings_out=warnings)
        assert len(warnings) == 1
        message = str(
            getattr(warnings[0], "message", warnings[0])
        )
        assert "variable declarator" in message
        # 86, not 87, because a declarator-level advisory for the
        # same construct de-duplicates the post-semicolon one away
        # and the survivor reports one column short. Pre-existing,
        # and tracked as its own task — when it is fixed this
        # assertion must move to 87. It is asserted rather than
        # left loose so the fix cannot land unnoticed.
        assert "max line width 86" in message

    def test_array_rhs_also_reserves_the_semicolon(self) -> None:
        """`_emit_variable_declarator_with_array_rhs` runs its own
        cascade and returns before the four sites above, so it needs
        the reserve independently. Without it this emits an
        81-character line, and the result is idempotent."""
        src = (
            "class T\n{\n    private static final String[] NAME = "
            "new String[] { \"e0zzzzzz\", \"e1zzzzzz\" };\n}\n"
        ).encode()
        warnings: list[object] = []
        out = format_java.format_source(src, warnings_out=warnings)
        lines = out.decode().split("\n")
        assert all(len(line) <= 80 for line in lines), [
            (len(x), x) for x in lines if len(x) > 80
        ]
        assert not warnings


class TestReceiverReserveIgnoresArgumentLayout:
    """The reserve a chain receiver wraps against must not depend on
    how the trailing call's arguments were laid out in source.

    It used to be `1 + len(name) + len(FIRST SOURCE LINE of args)`,
    so `.append(\\n    x)` reserved 8 while `.append(x)` reserved 21.
    The formatter mapped each layout onto the other and a
    declaration alternated between them forever — a true two-cycle,
    not merely a second pass.

    Note these two inputs are both fixed points at the pre-fix
    baseline AND produce identical output there: the shapes only
    diverge once the receiver sits close to the margin, which
    reserving the declaration semicolon is what pushed it into. So
    this class guards the reserve computation, and goes red when
    that computation alone is reverted — not when the whole release
    is.
    """

    WRAPPED = (
        "public class T\n{\n    void t()\n    {\n        if (x)\n"
        "        {\n            StringBuilder errorMessage\n"
        "                = new StringBuilder(\n"
        "                    \"Invalid message consumer specified: \""
        ").append(\n                        consumerType);\n"
        "        }\n    }\n}\n"
    )
    INLINE = (
        "public class T\n{\n    void t()\n    {\n        if (x)\n"
        "        {\n            StringBuilder errorMessage = "
        "new StringBuilder(\n"
        "                \"Invalid message consumer specified: \""
        ").append(consumerType);\n        }\n    }\n}\n"
    )

    def test_both_layouts_reach_the_same_output(self) -> None:
        a = format_java.format_source(
            self.WRAPPED.encode(), warnings_out=[]
        )
        b = format_java.format_source(
            self.INLINE.encode(), warnings_out=[]
        )
        assert a == b

    def test_each_layout_is_a_fixed_point_after_one_pass(
        self,
    ) -> None:
        for text in (self.WRAPPED, self.INLINE):
            once = format_java.format_source(
                text.encode(), warnings_out=[]
            )
            twice = format_java.format_source(
                once, warnings_out=[]
            )
            assert once == twice


class TestSecondPassConvergence:
    """Two shapes that only settled on a SECOND format.

    Both were decisions that read source layout the formatter then
    rewrote, so pass 1 answered from the author's layout and pass 2
    answered from pass 1's output. Neither fix changes the fixed
    point — they reach it one pass sooner.
    """

    def _passes(self, body: str, n: int = 3) -> list[bytes]:
        out = [body.encode()]
        for _ in range(n):
            out.append(
                format_java.format_source(
                    out[-1], warnings_out=[]
                )
            )
        return out[1:]

    _FIXTURES = (
        Path(__file__).resolve().parent / "fixtures"
    )

    @property
    def FOR_HEADER(self) -> str:
        """Read from the fixture so the two cannot drift apart."""
        return (
            self._FIXTURES
            / "condition_wrap"
            / "12_for_clause_wrap_escalates_whole_header"
            / "input.java"
        ).read_text()

    @property
    def WRAPPED_CONDITION(self) -> str:
        return (
            self._FIXTURES
            / "need_braces"
            / "23_wrapped_source_condition_still_collapses"
            / "input.java"
        ).read_text()

    def test_for_header_converges_on_the_first_pass(self) -> None:
        first, second, third = self._passes(self.FOR_HEADER)
        assert first == second == third

    def test_for_clause_wrap_breaks_the_whole_header(self) -> None:
        """Not the partial break the Anti-pattern section forbids —
        two clauses packed and one stranded beneath."""
        text = self._passes(self.FOR_HEADER)[0].decode()
        assert "line != null;\n" in text
        assert "; line\n" not in text

    def test_wrapped_condition_converges_on_the_first_pass(
        self,
    ) -> None:
        first, second, third = self._passes(self.WRAPPED_CONDITION)
        assert first == second == third

    def test_wrapped_condition_still_collapses_to_tier_1(
        self,
    ) -> None:
        """The emitter collapses the condition to one row regardless,
        so declining Tier 1 because the SOURCE spanned rows only
        deferred the collapse to the next pass."""
        text = self._passes(self.WRAPPED_CONDITION)[0].decode()
        assert (
            "if (obj == null || this.getClass() != obj.getClass()) "
            "return false;" in text
        )

