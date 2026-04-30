"""Cross-cutting idempotency tests for every fixture.

For each (script, fixture) pair, running the script against the
fixture's expected.java must produce zero further changes — i.e.
the desired output is a fixed point of the transformation. This
catches a whole class of subtle bugs:

- A script that "tweaks" a file forever (oscillating output).
- Two scripts that disagree (script A produces output B re-formats).
- Off-by-one errors that produce different output on round trips.

If any expected.java in the fixture corpus fails this gate, either
the fixture was authored incorrectly, the script is non-idempotent
on that input, or two scripts are stepping on each other's output.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from conftest import fixture_cases

# (script_module_name, fixture_category) pairs to exercise.
SCRIPT_MAP = [
    ("fix_allman_braces", "allman_braces"),
    ("fix_javadoc_reflow", "javadoc_reflow"),
    ("fix_javadoc_inline_tags", "javadoc_inline_tags"),
    ("fix_javadoc_tags", "javadoc_tags"),
    ("fix_need_braces", "need_braces"),
]


def _all_fixtures():
    """Yield (script_module_name, case_dir) for every fixture across
    every category."""
    for module_name, category in SCRIPT_MAP:
        for case in fixture_cases(category):
            yield module_name, case


@pytest.mark.parametrize(
    "module_name,case",
    list(_all_fixtures()),
    ids=lambda v: v.name if hasattr(v, "name") else v,
)
def test_expected_is_fixed_point(
    module_name: str, case: Path, tmp_path: Path
) -> None:
    """Running script against expected.java must produce no change."""
    module = importlib.import_module(module_name)
    expected_text = (case / "expected.java").read_text(encoding="utf-8")

    target = tmp_path / "Source.java"
    target.write_text(expected_text, encoding="utf-8")

    module.process_file(target)

    after = target.read_text(encoding="utf-8")
    assert after == expected_text, (
        f"\nNon-idempotent: {module_name} on {case.name}.\n"
        f"--- expected.java (input AND expected fixed point) ---\n"
        f"{expected_text}\n"
        f"--- actual after running script ---\n{after}\n"
    )


@pytest.mark.parametrize(
    "module_name,case",
    list(_all_fixtures()),
    ids=lambda v: v.name if hasattr(v, "name") else v,
)
def test_double_pass_converges(
    module_name: str, case: Path, tmp_path: Path
) -> None:
    """Running script twice on input.java must produce same output as once.

    The first pass transforms input to its target. The second pass on
    that output must be a no-op. (Equivalent to: applying the script
    repeatedly converges in a single step.)
    """
    module = importlib.import_module(module_name)
    input_text = (case / "input.java").read_text(encoding="utf-8")

    target = tmp_path / "Source.java"
    target.write_text(input_text, encoding="utf-8")

    module.process_file(target)
    after_first = target.read_text(encoding="utf-8")

    module.process_file(target)
    after_second = target.read_text(encoding="utf-8")

    assert after_second == after_first, (
        f"\nSecond pass changed output: {module_name} on {case.name}.\n"
        f"--- after first pass ---\n{after_first}\n"
        f"--- after second pass ---\n{after_second}\n"
    )
