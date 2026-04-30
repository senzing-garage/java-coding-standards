"""Unit tests for individual helper functions across the format scripts.

These complement the fixture-driven tests by exercising edge cases on
the helper functions directly. When a fixture-driven test fails, the
helper tests narrow the diagnosis to a specific function.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import _cli
import fix_allman_braces


# ---------------------------------------------------------------------------
# fix_allman_braces helpers
# ---------------------------------------------------------------------------


class TestIsControlFlowOrSpecial:
    """Lines that should keep same-line braces."""

    @pytest.mark.parametrize("line", [
        "if (cond) {",
        "if (cond)  {",
        "if(cond) {",
        "else {",
        "else if (cond) {",
        "for (int i = 0; i < n; i++) {",
        "while (cond) {",
        "do {",
        "try {",
        "try (Resource r = open()) {",
        "catch (Exception e) {",
        "finally {",
        "switch (x) {",
        "synchronized (this) {",
        "static {",
        "Runnable r = new Runnable() {",
        "() -> {",
        "result = list.stream().forEach(x -> {",
    ])
    def test_should_keep_same_line(self, line: str) -> None:
        assert fix_allman_braces.is_control_flow_or_special(line) is True

    @pytest.mark.parametrize("line", [
        "public void foo() {",
        "private static int bar() {",
        "public class Foo {",
        "public interface Bar {",
        "public enum Color {",
    ])
    def test_method_class_should_not(self, line: str) -> None:
        assert fix_allman_braces.is_control_flow_or_special(line) is False


class TestIsClassInterfaceEnum:
    @pytest.mark.parametrize("line", [
        "public class Foo {",
        "class Foo {",
        "public interface Bar {",
        "interface Bar {",
        "public enum Color {",
        "enum Color {",
        "abstract class Foo {",
        "final class Foo {",
        "public static class Inner {",
    ])
    def test_matches(self, line: str) -> None:
        assert fix_allman_braces.is_class_interface_enum(line) is True

    @pytest.mark.parametrize("line", [
        "public void foo() {",
        "if (x) {",
        "Runnable r = new Runnable() {",
    ])
    def test_does_not_match(self, line: str) -> None:
        assert fix_allman_braces.is_class_interface_enum(line) is False


class TestFindWrapOpenerIndent:
    """Paren-balance walk-back to find the line that opens a wrap."""

    def test_balanced_on_start_line_returns_start_indent(self) -> None:
        # Method header on its own line — balanced parens, return that line's indent.
        lines = [
            "public class Foo\n",
            "{\n",
            "  public void foo() {\n",
            "  }\n",
            "}\n",
        ]
        assert fix_allman_braces.find_wrap_opener_indent(
            lines, 2, "  "
        ) == "  "

    def test_unbalanced_walks_back_one_level(self) -> None:
        # Closing line of a wrapped while condition; balance becomes 0
        # on the `while (...` line above.
        lines = [
            "public class Foo\n",
            "{\n",
            "    public void m()\n",
            "    {\n",
            "        while (this.size()\n",
            "                < other.size()) {\n",
            "        }\n",
            "    }\n",
            "}\n",
        ]
        assert fix_allman_braces.find_wrap_opener_indent(
            lines, 5, "                "
        ) == "        "

    def test_unbalanced_walks_back_through_nested_wrap(self) -> None:
        # try-with-resources whose innermost resource has a wrapped call;
        # walk-back should reach the `try (` line, not the resource list.
        lines = [
            "public class Foo\n",
            "{\n",
            "    public void m()\n",
            "    {\n",
            "        try (Connection c = open();\n",
            "             Statement s = c.createStatement();\n",
            "             ResultSet r = s.executeQuery(\n"
            "                 \"SELECT 1\")) {\n",
            "        }\n",
            "    }\n",
            "}\n",
        ]
        # Index 6 is the deeply-nested closing line.
        result = fix_allman_braces.find_wrap_opener_indent(
            lines, 6, "                 "
        )
        assert result == "        "

    def test_string_literal_parens_dont_confuse_count(self) -> None:
        # A string literal containing parens shouldn't shift the balance.
        lines = [
            "        try (Statement s = createStatement()) {\n",
        ]
        # Balanced after string-stripping; returns this line's indent.
        assert fix_allman_braces.find_wrap_opener_indent(
            lines, 0, "        "
        ) == "        "

    def test_returns_default_when_no_opener_found(self) -> None:
        lines = ["        unbalanced));\n"]
        # Walks off the top of the file without finding balance; returns default.
        assert fix_allman_braces.find_wrap_opener_indent(
            lines, 0, "        "
        ) == "        "


# ---------------------------------------------------------------------------
# _cli helpers
# ---------------------------------------------------------------------------


class TestExclude:
    @pytest.mark.parametrize("path,patterns,expected", [
        ("src/main/java/Foo.java", [], False),
        ("src/main/java/Foo.java", ["**/Foo.java"], True),
        ("src/main/java/com/x/Generated.java", ["**/Generated*.java"], True),
        ("target/build/Foo.java", ["target/**"], True),
        ("src/main/java/Foo.java", ["target/**"], False),
        (
            "tooling/scripts/tests/fixtures/allman_braces/01/input.java",
            ["**/tooling/scripts/tests/fixtures/**"],
            True,
        ),
    ])
    def test_exclude_patterns(
        self, path: str, patterns: list[str], expected: bool
    ) -> None:
        assert _cli._excluded(Path(path), patterns) is expected


class TestBaselineExcludes:
    def test_fixtures_excluded_by_default(self) -> None:
        assert _cli._excluded(
            Path("tooling/scripts/tests/fixtures/allman_braces/01/input.java"),
            list(_cli.BASELINE_EXCLUDES),
        ) is True

    def test_target_excluded_by_default(self) -> None:
        assert _cli._excluded(
            Path("target/classes/com/x/Foo.java"),
            list(_cli.BASELINE_EXCLUDES),
        ) is True

    def test_normal_source_not_excluded(self) -> None:
        assert _cli._excluded(
            Path("src/main/java/com/x/Foo.java"),
            list(_cli.BASELINE_EXCLUDES),
        ) is False


class TestLoadExcludeFile:
    def test_reads_patterns_skipping_comments_and_blanks(
        self, tmp_path
    ) -> None:
        f = tmp_path / "excludes.txt"
        f.write_text(
            "# generated files\n"
            "**/Generated*.java\n"
            "\n"
            "# build output\n"
            "target/**\n",
            encoding="utf-8",
        )
        result = _cli._load_exclude_file(f)
        assert result == ["**/Generated*.java", "target/**"]

    def test_missing_file_returns_empty(self, tmp_path) -> None:
        f = tmp_path / "no-such-file"
        assert _cli._load_exclude_file(f) == []
