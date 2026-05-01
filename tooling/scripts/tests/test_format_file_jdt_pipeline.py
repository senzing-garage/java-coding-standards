"""End-to-end tests for the format_file.py orchestrator's JDT-then-scripts
pipeline.

These tests exercise the orchestrator as a black box via subprocess —
the same way the Claude Code PostToolUse hook, emeraldwalk.runonsave,
and CLI invocations exercise it. They verify the contract:

    format_file.py path/to/File.java
        produces a file that satisfies java-coding-standards.md,
        regardless of caller, with no IDE in the loop.

Distinct from the per-script fixture tests under
fixtures/{allman_braces,javadoc_*,need_braces}/ — those exercise
each fix_*.py in isolation. The fixtures here run the *combined*
JDT + scripts pipeline.

Requires the jdt-formatter.jar to be built. The pytest CI workflow
rebuilds it from source before invoking pytest; for local
development run `mvn package` once in tooling/jdt-formatter/.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import fixture_cases

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
STANDARDS_ROOT = SCRIPTS_DIR.parent.parent
JDT_JAR = STANDARDS_ROOT / "tooling" / "jdt-formatter" / "jdt-formatter.jar"


@pytest.fixture(scope="session", autouse=True)
def _require_jdt_jar() -> None:
    """Skip the orchestrator suite cleanly if the JAR or `java` are
    missing, with a clear hint at what to do.
    """
    if shutil.which("java") is None:
        pytest.skip(
            "JDK is required for orchestrator tests; install JDK 17+",
        )
    if not JDT_JAR.is_file():
        pytest.skip(
            f"jdt-formatter.jar not found at {JDT_JAR}; run "
            f"'mvn package' in tooling/jdt-formatter/ first",
        )


@pytest.mark.parametrize(
    "case",
    fixture_cases("orchestrator"),
    ids=lambda c: c.name,
)
def test_pipeline_produces_expected_output(case: Path, tmp_path: Path) -> None:
    """Run input.java through the orchestrator; assert output matches
    expected.java byte-for-byte.
    """
    target = tmp_path / "Source.java"
    target.write_text(
        (case / "input.java").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "format_file.py"), str(target)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"orchestrator exited {result.returncode}\n"
        f"stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    )

    expected = (case / "expected.java").read_text(encoding="utf-8")
    actual = target.read_text(encoding="utf-8")
    assert actual == expected, (
        f"\n--- expected ---\n{expected}\n--- actual ---\n{actual}\n"
    )


@pytest.mark.parametrize(
    "case",
    fixture_cases("orchestrator"),
    ids=lambda c: c.name,
)
def test_pipeline_idempotent(case: Path, tmp_path: Path) -> None:
    """Running the orchestrator twice in succession must produce the
    same output as a single run. Catches non-converging transformations
    and JDT-vs-script tug-of-war on brace placement.
    """
    target = tmp_path / "Source.java"
    target.write_text(
        (case / "input.java").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    cmd = [sys.executable, str(SCRIPTS_DIR / "format_file.py"), str(target)]

    r1 = subprocess.run(cmd, capture_output=True, text=True)
    assert r1.returncode == 0, r1.stderr
    after_first = target.read_text(encoding="utf-8")

    r2 = subprocess.run(cmd, capture_output=True, text=True)
    assert r2.returncode == 0, r2.stderr
    after_second = target.read_text(encoding="utf-8")

    assert after_second == after_first, (
        f"\nNon-idempotent pipeline on {case.name}.\n"
        f"--- after first pass ---\n{after_first}"
        f"--- after second pass ---\n{after_second}"
    )


def test_pipeline_skips_excluded_paths(tmp_path: Path) -> None:
    """A path matching BASELINE_EXCLUDES (e.g. a fixture under
    tooling/scripts/tests/fixtures/) must not be touched by the
    orchestrator even when passed explicitly. Same protection that
    protects test fixtures from the PostToolUse hook.
    """
    fixture_like = (
        tmp_path / "tooling" / "scripts" / "tests" / "fixtures" / "x"
    )
    fixture_like.mkdir(parents=True)
    target = fixture_like / "input.java"
    deliberately_buggy = "public class Foo {\n}\n"
    target.write_text(deliberately_buggy, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "format_file.py"), str(target)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert target.read_text(encoding="utf-8") == deliberately_buggy
