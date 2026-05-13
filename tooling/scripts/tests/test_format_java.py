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


class TestFormatSourceStub:
    """Confirm format_source() raises until the emitter lands."""

    def test_format_source_raises(self) -> None:
        with pytest.raises(NotImplementedError):
            format_java.format_source(b"public class Foo {}\n")


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
        tree = format_java.parse_source(b"class A {}")
        root = tree.root_node
        # `program` is not a leaf emitter — Phase 2b doesn't yet
        # handle structural nodes.
        emitter = format_java.Emitter()
        with pytest.raises(
            NotImplementedError, match="No emitter registered"
        ):
            format_java._emit_node(emitter, b"class A {}", root)

    def test_class_declaration_not_yet_handled(self) -> None:
        tree = format_java.parse_source(b"class A {}")
        class_decl = _find_first(tree.root_node, "class_declaration")
        assert class_decl is not None
        emitter = format_java.Emitter()
        with pytest.raises(NotImplementedError):
            format_java._emit_node(emitter, b"class A {}", class_decl)


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
        # The emitter is not implemented; running with no flags
        # should fail loudly rather than silently no-op or
        # damaging the input.
        result = _run_cli([])
        assert result.returncode != 0
        assert "not yet implemented" in result.stderr.lower()

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
