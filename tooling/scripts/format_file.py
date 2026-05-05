#!/usr/bin/env python3
"""Orchestrator: run JDT formatter then the six Python override scripts
in canonical order against one or more Java files.

The pipeline:

    JDT formatter (general-purpose Java formatting)
        ↓
    fix_allman_braces.py     — Allman brace placement override
    fix_javadoc_reflow.py
    fix_javadoc_inline_tags.py
    fix_javadoc_tags.py
    fix_need_braces.py       — short-circuit if rules
    fix_throws_alignment.py  — throws-clause column alignment

JDT handles the bulk of the standard (indent, line wrap, alignment,
continuation-indent, ternary tiers, operator-on-continuation). The
six Python scripts override the rules JDT can't express in a single
profile (Allman braces for type/method but same-line for control flow,
column-aligned throws-clause continuations), plus rules our standards
add beyond what JDT or checkstyle catch (no-orphan-words javadoc
reflow, short-circuit if collapse, etc.).

Used by:
- VSCode `Format Java file to Senzing standards` task.
- VSCode `emeraldwalk.runonsave` extension (format-on-save).
- Claude Code `PostToolUse` hook (auto-format every Edit/Write).
- CLI / pre-commit / CI.

Same input → same output, regardless of caller.

Exit code: 0 on success, non-zero if any pass failed.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_ORDER: tuple[str, ...] = (
    "fix_allman_braces.py",
    "fix_javadoc_reflow.py",
    "fix_javadoc_inline_tags.py",
    "fix_javadoc_tags.py",
    "fix_need_braces.py",
    "fix_throws_alignment.py",
)

# format_file.py lives at tooling/scripts/; the formatter module +
# profile sit two directories up.
_STANDARDS_ROOT = Path(__file__).resolve().parent.parent.parent
_JDT_PROFILE = _STANDARDS_ROOT / "tooling" / "ide" / "java-formatter.xml"
_JDT_DIR = _STANDARDS_ROOT / "tooling" / "jdt-formatter"
_JDT_POM = _JDT_DIR / "pom.xml"
_JDT_LOCAL_BUILD = _JDT_DIR / "target" / "jdt-formatter.jar"

# GitHub Releases hosting the JAR + SHA-256 sidecar. Override via
# env var for forks or air-gapped mirrors.
_RELEASE_BASE = os.environ.get(
    "SENZING_STANDARDS_RELEASE_BASE",
    "https://github.com/senzing-garage/java-coding-standards/releases/download",
)


def _read_pom_version() -> str | None:
    """Return the <version> element from the JDT formatter pom.xml,
    or None if the pom is missing or fails to read. The version drives
    the GitHub Release URL the JAR is downloaded from.
    """
    if not _JDT_POM.is_file():
        return None
    try:
        text = _JDT_POM.read_text(encoding="utf-8")
    except OSError:
        return None
    # The project version is the first <version>...</version> element.
    # <modelVersion>...</modelVersion> uses a different tag name and
    # doesn't match. Subsequent <version> elements are dependency
    # versions (e.g. `<version>${jdt.version}</version>`) — ignore
    # them; we only want the project's own version.
    match = re.search(r"<version>([^<]+)</version>", text)
    return match.group(1).strip() if match else None


def _cache_dir() -> Path:
    """Where downloaded JARs live. Honors XDG_CACHE_HOME and a project-
    specific override env var so air-gapped sites can pre-populate.
    """
    override = os.environ.get("SENZING_STANDARDS_CACHE_DIR")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "senzing-java-coding-standards"


def _download(url: str, dest: Path) -> None:
    """Download `url` to `dest` atomically. Raises on HTTP errors."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as resp:
        with open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out)
    tmp.replace(dest)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_from_source() -> Path | None:
    """Run `mvn package` in the formatter module to produce the JAR
    locally. Returns the JAR path on success, None on failure or if
    Maven is not available. Used as the bootstrap path before the
    first release exists, and as the offline fallback.
    """
    if shutil.which("mvn") is None:
        return None
    if not _JDT_POM.is_file():
        return None
    try:
        subprocess.run(
            ["mvn", "-B", "-q", "package"],
            cwd=_JDT_DIR,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None
    return _JDT_LOCAL_BUILD if _JDT_LOCAL_BUILD.is_file() else None


def _resolve_jar() -> Path | None:
    """Locate the JDT formatter JAR. Resolution order:

    1. Local Maven build at `tooling/jdt-formatter/target/jdt-formatter.jar`.
       Used by CI (which runs `mvn package` before pytest) and by
       developers who built locally for testing.
    2. Cached download at
       `<cache>/jdt-formatter-v<version>.jar`. Used after the first
       download from the matching GitHub Release.
    3. Download from
       `<release-base>/v<version>/jdt-formatter.jar`. The release
       also publishes `jdt-formatter.jar.sha256`; we download both
       and verify the JAR matches before caching.
    4. Build from source via `mvn package` (bootstrap before the
       first release; offline fallback when downloads fail).

    Returns the path to the resolved JAR, or None if all paths fail.
    """
    # 1. Local Maven build.
    if _JDT_LOCAL_BUILD.is_file():
        return _JDT_LOCAL_BUILD

    version = _read_pom_version()
    if version is None:
        return _build_from_source()

    # 2. Cache hit.
    cache_path = _cache_dir() / f"jdt-formatter-v{version}.jar"
    if cache_path.is_file():
        return cache_path

    # 3. Download from release.
    base = f"{_RELEASE_BASE.rstrip('/')}/v{version}"
    jar_url = f"{base}/jdt-formatter.jar"
    sha_url = f"{base}/jdt-formatter.jar.sha256"
    try:
        sha_path = cache_path.with_suffix(cache_path.suffix + ".sha256")
        _download(sha_url, sha_path)
        _download(jar_url, cache_path)
        expected = sha_path.read_text(encoding="utf-8").split()[0].lower()
        actual = _sha256(cache_path)
        if expected != actual:
            print(
                f"ERROR: SHA-256 mismatch for {jar_url}\n"
                f"  expected: {expected}\n"
                f"  actual:   {actual}",
                file=sys.stderr,
            )
            cache_path.unlink(missing_ok=True)
            sha_path.unlink(missing_ok=True)
            return None
        return cache_path
    except urllib.error.URLError as exc:
        print(
            f"WARNING: could not download JDT formatter JAR from "
            f"{jar_url}: {exc}. Falling back to local source build.",
            file=sys.stderr,
        )
        cache_path.unlink(missing_ok=True)
        sha_path.unlink(missing_ok=True)

    # 4. Build from source.
    return _build_from_source()


def _resolve_target_paths(forwarded_args: list[str]) -> list[Path]:
    """Same path resolution the underlying scripts use, but extracted
    here so we can call JDT against the file list directly. Mirrors
    `_cli.iter_target_files` semantics (positional paths + --src-dirs
    fallback + --exclude / --exclude-from filtering).

    Reuses `_cli.build_parser` so the parser definition stays in one
    place — adding a flag in _cli.py picks up here automatically.
    """
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import _cli

    parser = _cli.build_parser(prog="format_file", description="")
    # Tolerate unknown flags (e.g. --help) so they pass through cleanly
    # to the per-script invocations later.
    args, _ = parser.parse_known_args(forwarded_args)
    return list(_cli.iter_target_files(args))


# Cap on paths-per-JVM-invocation. With paths averaging ~80 chars,
# 500 leaves ~80 KB on the command line — well under the typical
# Linux ARG_MAX (~2 MB) and macOS (~256 KB) limits, with comfortable
# headroom for the env block. Bulk passes against very large
# codebases will run JDT in multiple JVM invocations; each cold
# start is ~1 s amortized over 500 files.
_JDT_BATCH_SIZE = 500


def _file_signature(path: Path) -> tuple[int, str] | None:
    """Return `(size, sha256-hex)` for `path`, or `None` if missing.

    `None` lets a deleted file compare unequal to its prior tuple
    signature without a special case at the call site. Guards both
    `stat()` and `_sha256()` so a deletion between the two calls
    still resolves to `None` instead of raising. Catches
    `FileNotFoundError` only, not `OSError` broadly: a permission
    flip mid-pass is a genuine anomaly and should fail loud rather
    than silently count as "modified" in the summary.
    """
    try:
        size = path.stat().st_size
        return (size, _sha256(path))
    except FileNotFoundError:
        return None


def run_jdt_pass(paths: list[Path]) -> int:
    """Run the Eclipse JDT formatter against `paths`. Returns 0 on
    success or the first non-zero exit code if any batch fails. The
    path list is chunked at `_JDT_BATCH_SIZE` to keep each JVM
    invocation's command line well under typical OS ARG_MAX limits.
    """
    if not paths:
        return 0
    if not _JDT_PROFILE.is_file():
        print(
            f"ERROR: JDT formatter profile not found at {_JDT_PROFILE}",
            file=sys.stderr,
        )
        return 2
    if shutil.which("java") is None:
        print(
            "ERROR: 'java' not found on PATH; required to run the JDT "
            "formatter pass. Install JDK 17+ or remove this script "
            "invocation from your hooks.",
            file=sys.stderr,
        )
        return 2

    jar_path = _resolve_jar()
    if jar_path is None:
        print(
            "ERROR: JDT formatter JAR could not be located. Tried, in "
            "order: tooling/jdt-formatter/target/jdt-formatter.jar, "
            "the local cache, the GitHub Release for the version pinned "
            "in pom.xml, and a fallback `mvn package` build. Install "
            "Maven (or `cd tooling/jdt-formatter && mvn package` once) "
            "if you're working offline.",
            file=sys.stderr,
        )
        return 2

    first_failure = 0
    for i in range(0, len(paths), _JDT_BATCH_SIZE):
        batch = paths[i:i + _JDT_BATCH_SIZE]
        cmd = [
            "java",
            "-jar",
            str(jar_path),
            str(_JDT_PROFILE),
            *(str(p) for p in batch),
        ]
        result = subprocess.run(cmd)
        if result.returncode != 0 and first_failure == 0:
            first_failure = result.returncode
    return first_failure


def main() -> int:
    here = Path(__file__).resolve().parent
    forwarded_args = sys.argv[1:]

    # Stage 1: JDT pass against resolved paths.
    # We resolve paths Python-side so JDT only sees real .java files
    # (and so we honor BASELINE_EXCLUDES, --exclude, etc. before
    # invoking the JVM). For pure --help passthrough or non-path args
    # the path list will be empty and the JDT call is a no-op.
    try:
        target_paths = _resolve_target_paths(forwarded_args)
    except SystemExit as exc:
        # argparse exits with code 0 on --help; treat that as a clean
        # passthrough (the underlying scripts will print their own
        # usage and exit). Any other code indicates a real argparse
        # failure (missing required arg, type-conversion error, etc.) —
        # warn so the skipped JDT pass doesn't go unnoticed, but still
        # let the underlying scripts run so their error reporting
        # surfaces too.
        if exc.code not in (0, None):
            print(
                f"WARNING: path resolution exited {exc.code}; "
                f"skipping JDT pass.",
                file=sys.stderr,
            )
        target_paths = []

    failures: list[tuple[str, int]] = []
    if target_paths:
        # JDT (unlike the override scripts) doesn't print a
        # modified-count of its own; snapshot signatures so we can
        # synthesize one after the subprocess returns.
        pre_signatures = {p: _file_signature(p) for p in target_paths}
        rc = run_jdt_pass(target_paths)
        if rc != 0:
            failures.append(("jdt-formatter", rc))
        jdt_modified = sum(
            1 for p in target_paths
            if _file_signature(p) != pre_signatures[p]
        )
        print(
            f"\nJDT pass: {len(target_paths)} files processed, "
            f"{jdt_modified} modified."
        )

    # Stage 2: existing Python override scripts in canonical order.
    for script in SCRIPT_ORDER:
        script_path = here / script
        if not script_path.is_file():
            print(
                f"ERROR: missing script {script_path}",
                file=sys.stderr,
            )
            return 2

        cmd = [sys.executable, str(script_path), *forwarded_args]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            failures.append((script, result.returncode))

    if failures:
        print("\nFailures:", file=sys.stderr)
        for name, rc in failures:
            print(f"  {name}: exit {rc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
