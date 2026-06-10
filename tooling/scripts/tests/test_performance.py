"""Performance gate for the formatter.

The plan's verification step 9 (Performance gates) sets a
concrete bar: formatting a 100-file Java codebase completes
in under 10 seconds warm (file-system cache hot, tree-sitter
grammar already loaded).

This test loads 100 .java files from a corpus, primes the
caches by running one untimed warm-up pass, then times a
second pass and asserts total wall-clock time under 10s. It
also reports the per-file median + p95 + max so a regression
shows up as a clear printable metric rather than a single
binary pass/fail.

Default corpus: `senzing-commons-java/src/` (same as
`test_fuzz_corpus.py`). Set `SENZING_JAVA_FUZZ_CORPUS` to a
different absolute path to benchmark against a larger
codebase.

The test `skip`s cleanly when fewer than 100 files are
available so a stripped-down checkout doesn't fail CI.
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import format_java


# Concrete bar from the original plan: 100 files, warm, under
# 10 seconds total.
_FILE_COUNT_TARGET = 100
_TOTAL_TIME_BUDGET_S = 10.0


def _resolve_corpus() -> Path | None:
    env = os.environ.get("SENZING_JAVA_FUZZ_CORPUS")
    if env:
        p = Path(env)
        return p if p.is_dir() else None
    submodule = Path(__file__).resolve()
    consumer_root = submodule.parents[4]
    src = consumer_root / "src"
    return src if src.is_dir() else None


_CORPUS = _resolve_corpus()
_CORPUS_FILES: list[Path] = (
    sorted(_CORPUS.rglob("*.java"))[:_FILE_COUNT_TARGET]
    if _CORPUS
    else []
)


@pytest.mark.skipif(
    len(_CORPUS_FILES) < _FILE_COUNT_TARGET,
    reason=(
        f"Need at least {_FILE_COUNT_TARGET} Java files for the "
        f"perf gate; found {len(_CORPUS_FILES)}. Set "
        f"SENZING_JAVA_FUZZ_CORPUS to a larger corpus."
    ),
)
def test_warm_format_100_files_under_10s(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """100-file warm format < 10s.

    Reads all 100 files into memory first (so the timed loop
    measures pure formatter cost, not disk I/O), runs one
    untimed warm-up pass to prime caches, then times the
    second pass.
    """
    # Read source bytes once; the timed loop reuses the
    # in-memory copies so disk I/O doesn't skew the measurement.
    sources: list[tuple[Path, bytes]] = []
    for p in _CORPUS_FILES:
        try:
            sources.append((p, p.read_bytes()))
        except OSError as exc:  # pragma: no cover — defensive
            pytest.fail(f"could not read {p}: {exc}")

    # Warm-up pass — discards results, primes grammar cache,
    # JIT (cpython-side), python class dispatch caches, etc.
    for _, src in sources:
        try:
            format_java.format_source(src)
        except (NotImplementedError, ValueError):
            # Refusals are fine — they exercise the dispatch
            # path; just keep the loop warm.
            pass

    # Timed pass.
    per_file: list[float] = []
    refused = 0
    parse_err = 0
    t0 = time.perf_counter()
    for _, src in sources:
        t_start = time.perf_counter()
        try:
            format_java.format_source(src)
        except NotImplementedError:
            refused += 1
        except ValueError:
            parse_err += 1
        per_file.append(time.perf_counter() - t_start)
    total = time.perf_counter() - t0

    median = statistics.median(per_file)
    p95 = (
        statistics.quantiles(per_file, n=20)[-1]
        if len(per_file) >= 20
        else max(per_file)
    )
    longest = max(per_file)

    # `capsys.disabled()` lets the report print regardless of
    # whether pytest is capturing stdout. Useful for CI logs
    # so a slowdown is visible without re-running with `-s`.
    with capsys.disabled():
        print(
            f"\n[perf] {len(sources)} files in {total:.3f}s "
            f"(median {median * 1000:.1f}ms, "
            f"p95 {p95 * 1000:.1f}ms, "
            f"max {longest * 1000:.1f}ms; "
            f"refused {refused}, parse-errors {parse_err})"
        )

    assert total < _TOTAL_TIME_BUDGET_S, (
        f"perf gate failed: {total:.3f}s > {_TOTAL_TIME_BUDGET_S}s "
        f"budget for {len(sources)} files"
    )
