"""Smoke tests for the canonical AST-based Java formatter scaffolding.

Phase 2a only verifies the parser/grammar wiring. Emission tests
arrive with subsequent phases.
"""

from __future__ import annotations

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

    def test_class_with_extends_not_yet_supported(self) -> None:
        with pytest.raises(
            NotImplementedError, match="superclass"
        ):
            format_java.format_source(b"class A extends B {}")

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
        # Multi-exception throws on one line (Phase 2p covers
        # only the single-line form; wrap-priority phase
        # handles the priority-2 one-per-line form).
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

    def test_parameter_with_modifier_not_yet_supported(
        self,
    ) -> None:
        # `final int x` carries a modifier on the parameter,
        # which lands with parameter-annotation support in the
        # annotation phase.
        with pytest.raises(
            NotImplementedError,
            match="formal_parameter with modifiers",
        ):
            format_java.format_source(
                b"class A { void m(final int x) {} }"
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
            b'enum E { ACTIVE("act"), INACTIVE("inact"); }'
        )
        assert out == (
            b"enum E\n"
            b"{\n"
            b'    ACTIVE("act"),\n'
            b'    INACTIVE("inact");\n'
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

    def test_for_multi_init_not_yet_supported(self) -> None:
        # Comma-separated init expressions
        # (`for (i = 0, j = 0; ...)`) — the grammar surfaces
        # them as multiple children sharing the `init` field
        # name; the naive `child_by_field_name` lookup would
        # silently drop all but the first. Refuse loudly.
        with pytest.raises(
            NotImplementedError, match="comma-separated init"
        ):
            format_java.format_source(
                b"class A { void m() { "
                b"for (i = 0, j = 0; i < n; i++) {} } }"
            )

    def test_for_multi_update_not_yet_supported(self) -> None:
        with pytest.raises(
            NotImplementedError, match="comma-separated update"
        ):
            format_java.format_source(
                b"class A { void m() { "
                b"for (int i = 0; i < n; i++, j++) {} } }"
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
        # Multi-line javadoc with content already at the
        # correct indent for class-body level. The emitter
        # preserves interior indents verbatim via
        # `write_raw_lines`.
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

    def test_field_with_text_block_initializer_not_yet_supported(
        self,
    ) -> None:
        # Text blocks inside an indented context need indent-aware
        # emission per the "Text Blocks" spec section; the Phase
        # 2c emitter refuses rather than produce content lines
        # mis-aligned at column 0.
        with pytest.raises(
            NotImplementedError,
            match="indented context",
        ):
            format_java.format_source(
                b'class A { String s = """\nhello\n"""; }'
            )


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
    # in the tree-sitter-java grammar; verbatim preservation covers
    # them since the B4 spec section forbids reflow of contents.
    (b'class A { String s = """\nblock\n"""; }',
     "string_literal", '"""\nblock\n"""'),
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


class TestEmitNodeDispatch:
    """Verify the dispatch helper's error path."""

    def test_unknown_node_type_raises(self) -> None:
        # switch_expression is intentionally not yet registered;
        # switch (statements + expressions) lands in its own
        # phase with all the modern Java pattern-matching rules.
        src = (
            b"class A { String m(int x) { "
            b"return switch (x) { case 1 -> \"one\"; "
            b"default -> \"other\"; }; } }"
        )
        tree = format_java.parse_source(src)
        stmt = _find_first(tree.root_node, "switch_expression")
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
