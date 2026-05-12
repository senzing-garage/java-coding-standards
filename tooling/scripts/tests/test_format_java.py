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
