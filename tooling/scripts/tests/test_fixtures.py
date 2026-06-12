"""Fixture-driven golden tests for `format_source`.

Each subdirectory under `tests/fixtures/<category>/<case>/`
contains an `input.java` and an `expected.java`; this module
discovers them at collection time and parametrizes a single
test that asserts the formatter's output for `input.java`
matches `expected.java` byte-for-byte. New fixture pairs
become live the moment they're checked in.

Conventions for new cases:

- Use SYNTHETIC code, not snippets pulled from consumer
  projects. The fixture pair captures the FORM (e.g. "long
  class declaration with several bounded type parameters")
  that triggers the wrap-priority logic, not the literal
  code from any one codebase. This keeps the fixtures
  portable across adopter projects and protects against
  consumer-code churn invalidating the contract.

- One scenario per case. Each case directory should
  exercise a single wrap-priority path so a failure
  pinpoints the regression. Combined scenarios belong in
  the consumer adoption gate (mvn -Pcheckstyle), not here.

- Categories track the wrap-priority sections of the spec
  doc. The current set:

      allman_braces/            — brace-placement rules
      class_header_wrap/        — extends/implements wrap
      condition_wrap/           — if/while/for + tail_reserve
      javadoc_inline_tags/      — `{@code}`, `{@link}` etc.
      javadoc_reflow/           — paragraph reflow
      javadoc_tags/             — `@param`/`@return` etc.
      line_comment_reflow/      — `//` reflow + directive exempt
      method_chain_wrap/        — `.method()` chain wrap
      method_decl_wrap/         — non-generic param wrap
      need_braces/              — Tier-1 brace synthesis
      ternary_wrap/             — `?:` cascade
      text_block/               — triple-quoted indent-shift
      throws_alignment/         — throws-clause wrap
"""

from __future__ import annotations

from pathlib import Path

import pytest

import format_java


_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _collect_fixture_cases() -> list[tuple[str, Path]]:
    """Walk `fixtures/<category>/<case>/` and return one entry
    per case containing both `input.java` and `expected.java`.

    Returns `(test_id, case_dir)` pairs; the test id is
    `<category>/<case>` so pytest output stays readable.
    """
    if not _FIXTURES_DIR.is_dir():
        # Fail loudly rather than silently collecting zero
        # cases — a missing fixtures dir means the test suite
        # would pass with no coverage. The skip-with-message
        # surfaces the problem in pytest's output.
        pytest.skip(
            f"fixtures directory not found: {_FIXTURES_DIR}",
            allow_module_level=True,
        )
    out: list[tuple[str, Path]] = []
    for category in sorted(_FIXTURES_DIR.iterdir()):
        if not category.is_dir() or category.name.startswith("."):
            continue
        for case in sorted(category.iterdir()):
            if not case.is_dir() or case.name.startswith("."):
                continue
            if not (case / "input.java").is_file():
                continue
            if not (case / "expected.java").is_file():
                continue
            out.append(
                (f"{category.name}/{case.name}", case)
            )
    return out


_CASES = _collect_fixture_cases()


@pytest.mark.parametrize(
    "case_dir",
    [c for _, c in _CASES],
    ids=[i for i, _ in _CASES],
)
def test_fixture_golden(case_dir: Path) -> None:
    """`format_source(input.java)` must equal `expected.java`
    byte-for-byte, AND a second pass on the output must be a
    fixed point (idempotency).

    Calibration gate: the entire fixture suite is the
    contract surface for the formatter's emitted shape. A
    regression here means a real behavior change — either
    the formatter started producing a different layout
    (genuine regression) or the spec/fixture changed
    intentionally and the other side needs updating.

    The idempotency check is essential because the wrap
    engine's decisions thread through tail-reserve and
    speculative emission; a subtle change to the way one
    wrap decision sees its surrounding context can produce
    a different shape on the second pass that still happens
    to match `expected.java` on the first. By asserting
    `format(actual) == actual`, we lock the second-pass
    behavior to the same fixed point.
    """
    input_bytes = (case_dir / "input.java").read_bytes()
    expected_bytes = (case_dir / "expected.java").read_bytes()
    actual = format_java.format_source(input_bytes)
    assert actual == expected_bytes
    second_pass = format_java.format_source(actual)
    assert second_pass == actual, (
        "formatter is not idempotent on this fixture's output"
    )
