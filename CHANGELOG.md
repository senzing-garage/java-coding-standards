# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog], [markdownlint],
and this project adheres to [Semantic Versioning].

## [0.2.0] - 2026-04-30

**Note:** This release closes the longstanding gap that the bulk-
format Python scripts didn't actually format Java code — only
brace placement, javadoc reflow, and short-circuit `if` rules. A
file with mis-indented code or over-80-character lines passed
through the orchestrator unchanged, leaving developers to chase
those issues by hand or via VS Code's built-in formatter (which
itself was disabled due to brace-placement conflicts).

The orchestrator is now a true single-command formatter. Running
`format_file.py path/to/File.java` produces a file that satisfies
`mvn -Pcheckstyle validate`, regardless of caller (CLI, VS Code
runonsave, Claude Code PostToolUse hook, CI pre-commit).

### Added

- `tooling/jdt-formatter/` — small Java CLI shim around the
  Eclipse JDT formatter (`org.eclipse.jdt:org.eclipse.jdt.core
  3.42.0`). Reads the existing `tooling/ide/java-formatter.xml`
  profile and formats Java files in place. Built as a fat JAR
  (`jdt-formatter.jar`) via `mvn package`; the committed JAR
  ships with the repo so consumers don't need a one-time build
  step on first use.
- `tooling/scripts/tests/test_format_file_jdt_pipeline.py` — new
  pytest module with 9 fixtures × 4 cases covering the
  orchestrator's combined JDT-then-scripts behavior, including
  the four user-reported failure modes (over-indented brace,
  long line, bad spacing, missing braces around assignment-style
  if body) and a baseline-excludes protection check.
- `tooling/scripts/tests/fixtures/orchestrator/` — fixture corpus
  for the pipeline tests (4 cases, byte-comparable
  input.java/expected.java pairs).
- `.github/workflows/rebuild-jdt-formatter-jar.yaml` — CI
  workflow that rebuilds `jdt-formatter.jar` when Dependabot
  opens a PR against `tooling/jdt-formatter/pom.xml`. Force-
  pushes the rebuilt JAR onto the Dependabot branch so the PR
  diff shows pom.xml + JAR atomically.

### Changed

- `tooling/scripts/format_file.py` — orchestrator now runs an
  Eclipse JDT formatter pass first (general Java formatting:
  indent, line wrap, continuation-indent, ternary tiers,
  operator-on-continuation, alignment, whitespace), then the
  existing five `fix_*.py` scripts in canonical order
  (overrides: Allman brace placement, javadoc no-orphan reflow,
  short-circuit `if` rules). The five scripts are unchanged in
  behavior; their 190-test corpus is unchanged.
- `adoption/claude-md-templates/vscode-settings-snippet.json` —
  comment block clarifies the rationale for keeping
  `[java].editor.formatOnSave: false`: redhat.java's built-in
  format-on-save would run JDT a second time redundantly with
  emeraldwalk.runonsave invoking the orchestrator. The
  orchestrator runs JDT once internally with the right ordering.
- `.github/workflows/pytest.yaml` — adds a JDK 17 setup step and
  rebuilds `jdt-formatter.jar` from source before invoking
  pytest. Locks the source-and-JAR consistency on every CI run.
- `.github/dependabot.yml` — Maven `directory` retargeted from
  `/` (no manifest) to `/tooling/jdt-formatter`. Dependabot now
  tracks `org.eclipse.jdt:org.eclipse.jdt.core` with the
  standard 21-day cooldown.

### Migration

Consumer projects bumping their submodule pin to this release
will, on next `format_file.py` invocation:

1. Pick up the JDT pass automatically — no consumer action
   required.
2. Produce a one-time format-compliance diff for any source that
   wasn't previously fully compliant (especially indent, line
   wrap, alignment). Commit as a follow-up "format compliance"
   pass.
3. Subsequent runs are idempotent (verified by the new
   pipeline test corpus).

The JAR is committed in the submodule, so no first-use Maven
build is required on developer machines. JDK 17+ is required
to invoke `java -jar`; consumer projects already require it for
their Maven build.

## [0.1.0] - 2026-04-30

**Note:** First substantive release. The `[0.0.0]` entry below was
the senzing-garage repository-creation placeholder; this release
ships the actual standards content, tooling, FAQ server, adoption
playbook, and pytest suite.

### Added
- Initial directory layout: `checkstyle/`, `docs/`, `tooling/`, `mcp/`,
  `adoption/`.
- Canonical `docs/java-coding-standards.md` (912-line standards doc).
- Shared FAQs:
  `building/java-formatting-standards`,
  `building/javadoc-reflow-conventions`,
  `conventions/adding-new-faqs`,
  `testing/system-stubs-and-output-capture`.
- Bulk-format Python scripts in `tooling/scripts/`:
  `fix_allman_braces`, `fix_javadoc_reflow`, `fix_javadoc_inline_tags`,
  `fix_javadoc_tags`, `fix_need_braces`, plus the
  `format_file.py` orchestrator and the shared `_cli.py` helper.
- Generic FAQ MCP server (`mcp/faq_server.py`) with `--server-name`,
  `--faqs-dir`, `--shared-faqs-dir` CLI args and PEP 723 inline
  metadata pinning `mcp==1.27.0`.
- Eclipse JDT formatter profile at `tooling/ide/java-formatter.xml`.
- Adoption playbook: `ADOPTION.md`, `adopt-standards-prompt.md`,
  `slash-commands/init-java.md`, `claude-md-templates/`,
  `verification-checklist.md`.
- `SECURITY.md` documenting the maintained invariants.
- `README.md` with the consumer-adoption quickstart.
- `tooling/scripts/tests/` — pytest suite (190 tests) for the bulk-
  format scripts: per-script fixture-driven cases, helper unit
  tests, idempotency cross-cut, and orchestrator tests. 43 fixture
  pairs across the five scripts. Required to pass before merge via
  `.github/workflows/pytest.yaml` (Python 3.10–3.13 × ubuntu-latest
  + macos-latest matrix).
- `tooling/scripts/_cli.py` `BASELINE_EXCLUDES` — always-applied
  exclusion patterns covering `tooling/scripts/tests/fixtures/**`
  and `target/**`. Fixtures must stay deliberately non-compliant;
  without these, auto-format hooks running `format_file.py`
  silently rewrite fixture inputs.
- `CONTRIBUTING.md` "Testing" section documenting how to run the
  suite, the test layout, and how to add new fixtures.

### Changed

- `tooling/scripts/_cli.py` `_excluded()` — leading-`**/` patterns
  now also match at path depth zero (gitignore-style approximation),
  so `**/fixtures/**` matches a top-level `fixtures/foo.java`.
- `tooling/scripts/fix_allman_braces.py` — corrected wrong-indent
  Allman split on wrapped control-flow conditions and method
  parameter lists. Replaced the `'(' in stripped` heuristic with a
  paren-balance check, added `find_wrap_opener_indent()` for
  paren-balance walk-back through nested wraps, and added a Case 5
  cleanup pass that re-aligns previously-buggy outputs from older
  script versions.
- `adoption/adopt-standards-prompt.md` — Step 7 (.gitignore) is no
  longer a strict no-op: it adds no new rules but mandates
  `git check-ignore -v` against each created path and `!` exception
  lines for any matches. Step 13 documents that the orchestrator
  smoke test will produce a non-zero diff for projects coming from
  older script vintages, with a second-pass idempotency gate.
- `adoption/claude-md-templates/claude-hooks-snippet.json` — the
  SessionStart freshness fetch uses `git -c http.lowSpeedLimit=1000
  http.lowSpeedTime=3 fetch` so it aborts after 3 s in slow or
  unreliable network conditions instead of hanging on a degraded
  connection.

## [0.0.0] - 2026-04-29

### Changes/Additions/Fixes in version 0.0.0
