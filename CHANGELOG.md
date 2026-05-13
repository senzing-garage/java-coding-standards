# Changelog

All notable changes to this project will be documented in this file.

The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
[markdownlint](https://dlaa.me/markdownlint/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `tooling/scripts/format_java.py` — Phase 2a scaffolding for
  the new canonical AST-based Java formatter. Loads the
  `tree-sitter-java` grammar, exposes `parse_source` /
  `parse_file` / `has_parse_errors`, and stubs `format_source` to
  raise `NotImplementedError`. CLI provides `--check-grammar`,
  `--parse FILE`, and `--version`. The emitter dispatch (the
  actual formatting logic) lands in subsequent phases; this
  commit verifies the grammar pin and the parser wiring only.
- Phase 2b token-stream emission: `Emitter` class (column /
  indent / line tracking, A5-spec trailing-whitespace strip on
  `newline()` and `finish()`, exact EOF-newline guarantee,
  `write_raw_lines()` for B4-spec verbatim multi-line content
  like text blocks), `_emit_node()` dispatcher, and
  `_LEAF_EMITTERS` registry covering 14 leaf node types
  (decimal / hex / octal / binary integer literals,
  decimal / hex floating-point literals, character and string
  literals, `null_literal`, `true` / `false`, `this` / `super`,
  `identifier`, `type_identifier`). The dispatcher raises
  `NotImplementedError` on any node type not yet registered —
  the explicit "this construct isn't supported yet" signal
  during incremental rollout.
- Phase 2c recursive walk: structural emitters for `program`,
  `class_declaration`, `field_declaration`, and
  `variable_declarator`. Also registers the primitive type
  nodes (`integral_type`, `floating_point_type`,
  `boolean_type`, `void_type`) as verbatim emitters. The
  dispatch table (previously `_LEAF_EMITTERS`) renamed to
  `_NODE_EMITTERS` to reflect that it now covers both leaf
  tokens and structural nodes.
  `format_source()` is now FUNCTIONAL for the supported subset:
  a single top-level class with no modifiers / type parameters /
  extends-implements, whose body contains primitive-typed or
  named-typed field declarations with optional literal
  initializers. Anything outside that subset raises
  `NotImplementedError` from the dispatcher (the explicit
  "not yet supported" signal — the formatter never silently
  emits non-spec output). Allman brace placement is enforced,
  with class members packed (no blank lines between fields
  per the "Blank-Line Rules Between Class Members" spec
  section, since Phase 2c doesn't yet handle javadoc).
  `format_source()` also now rejects parse-error input with a
  `ValueError` rather than producing garbled output.
- Phase 2d keyword modifiers: `_emit_modifiers` handler for
  the `modifiers` node, plus dispatch wiring in
  `_emit_class_declaration` and `_emit_field_declaration` so
  classes and fields can carry keyword modifiers (`public`,
  `private`, `protected`, `static`, `final`, `abstract`,
  `volatile`, `synchronized`, `native`, `strictfp`,
  `transient`, `default`). Modifier order is preserved from
  the source; the formatter does not reorder modifiers
  (checkstyle enforces JLS conventional order separately).
  Annotations within `modifiers` (`marker_annotation`,
  `annotation`, etc.) remain refused — they have their own
  per-annotation wrapping rules from the "Annotations" spec
  section and land in a later phase.
- Phase 2e expression emitters: `binary_expression` (space
  around the operator per "Whitespace and Operator Spacing"
  spec section's binary-operator row), `unary_expression`
  (no space between operator and operand), `update_expression`
  (prefix and postfix `++` / `--` forms, no space), and
  `parenthesized_expression` (no spaces inside parens).
  Field-initializer expressions now support arithmetic,
  comparison, boolean, shift, and bitwise binary operators;
  unary negation / `!` / `~`; pre- and post-increment /
  decrement; and arbitrary nesting via parentheses. The
  ternary operator (`condition ? a : b`) still refuses — it
  has its own multi-tier wrapping rules and lands in a later
  phase.
- Phase 2j loop statements: `_emit_for_statement` (classic
  three-part header `for (init; cond; update) BODY` with
  single space after each non-empty header separator per the
  "Whitespace and Operator Spacing" spec section's
  "After semicolons in for headers" row; empty `for (;;)`
  case handled with no interior spaces).
  `_emit_enhanced_for_statement` covers the for-each form
  `for (TYPE NAME : VALUE) BODY` with single space on each
  side of `:`. `_emit_while_statement` emits
  `while (cond) BODY`. `_emit_do_statement` emits
  `do BODY while (cond);` with the cuddled `} while` per
  "Closing Brace Rules". All four use the same-line-brace
  control-flow form via the existing `_emit_block` emitter.
  After Phase 2j the formatter handles realistic loop-
  bearing methods like
  `for (int i = 0; i < n; i++) { use(i); }` and
  `for (String s : items) { print(s); }`. Refusals: all
  four loop emitters refuse brace-less bodies (those land
  with the short-circuit-conditionals phase); the classic
  for-statement also refuses comma-separated init or
  update expressions (`for (i = 0, j = 0; ...; i++, j++)`)
  since the grammar surfaces those as multiple children
  sharing the same field name and `child_by_field_name`
  would silently drop all but the first — multi-init /
  multi-update support lands with the wrap-priority phase.
- Phase 2i if/else control flow: `_emit_block` for the
  same-line-brace control-flow block shape (per the
  "Brace Placement / Same-Line Style" spec section);
  `_emit_if_statement` for `if (cond) { ... }`, cuddled
  `} else { ... }`, and recursive `else if` chains via the
  grammar's `alternative` field. Method-declaration bodies
  continue to be emitted inline by
  `_emit_method_declaration` (Allman form), which doesn't
  dispatch through the new `block` emitter. Refusals:
  brace-less Tier 1 short-circuit form
  (`if (x) return;`) — short-circuit handling lands in
  its own phase; multi-line condition wrapping (Allman
  `{` on its own line per the
  "Exception: Multi-Line Conditions" spec rule) — lands
  with wrap-priority logic. After Phase 2i the formatter
  handles realistic conditional code:
  `if (x == 1 && y != 2) { compute(); } else { other(); }`.
- Phase 2h statement emitters in method bodies:
  `_emit_method_declaration` extended to emit body statements
  with proper +4 indent and one-statement-per-line layout.
  New emitters: `_emit_return_statement` (handles both
  `return;` and `return EXPR;`), `_emit_expression_statement`
  (for assignment-as-statement, method-call statement, update
  statement), and `_emit_assignment_expression` (space-space
  around any assignment operator — `=`, `+=`, `-=`, `*=`,
  `/=`, `%=`, `&=`, `|=`, `^=`, `<<=`, `>>=`, `>>>=` — per
  the "Whitespace and Operator Spacing" spec section's
  assignment-operator row, with the operator text recovered
  from the `operator` field). `local_variable_declaration`
  shares the existing `_emit_field_declaration` emitter
  since the two have identical grammar shapes (modifiers +
  type + variable_declarator(s) + `;`). After Phase 2h the
  formatter accepts realistic method bodies like
  `int compute() { int r = a + b; return r; }`. Refusals:
  control-flow statements (`if`, `for`, `while`, `do`, `try`,
  `switch`) — each will land with its own phase carrying the
  same-line-brace and condition-wrapping rules from the spec's
  "Brace Placement / Same-Line Style" and per-construct
  sections. The legacy
  `test_method_with_body_not_yet_supported` test was removed
  (promoted to the new statement tests).
- Phase 2g method declarations with empty bodies:
  `_emit_method_declaration` emits the signature line in
  `[modifiers] TYPE NAME(formal_parameters)` shape and places
  the body braces in Allman style on their own lines per the
  "Brace Placement / Allman Style" spec section.
  `_emit_formal_parameters` emits comma-separated parameters
  on a single line (wrap-priority logic from the
  "Method and Constructor Declarations / Parameter Placement"
  spec section deferred). `_emit_formal_parameter` emits
  `TYPE NAME`. `_emit_array_type` emits `Type[]` for array
  parameter types (typical `String[] args` in main methods),
  stripping any developer-written interior whitespace per
  the spec's "Multi-dimensional arrays" subsection. The
  formatter now accepts inputs like
  `public class Main { public static void main(String[] args) {} }`
  and produces the expected Allman-braced multi-line output.
  Refusals: throws clauses (later phase — throws-clause
  wrapping), type parameters on methods (later phase —
  generic types), abstract / interface methods (later phase —
  interface bodies), parameter annotations (later phase —
  annotations), and method bodies containing statements
  (later phase — statement emitters). The legacy
  `test_method_declaration_not_yet_supported` test was
  removed (promoted to a positive `test_empty_method_body`
  assertion); `test_unknown_node_type_raises` was retargeted
  to use `return_statement` since `method_declaration` is now
  supported.
- Phase 2f single-line expression operations: `field_access`
  (no spaces around the dot), `instanceof_expression`
  (non-pattern form — single space on each side of the
  `instanceof` keyword), `cast_expression` (single space
  after the closing cast paren per the spec's
  "Cast expressions" subsection), `method_invocation`
  (single-line form only — wrap-priority logic from the
  "Method Call Arguments" spec section is deferred to a
  later phase), and `argument_list` (comma-space-separated
  arguments, single-line form only). The pattern-binding
  form of instanceof (`obj instanceof Type t`) refuses
  with `NotImplementedError`; it lands with the pattern-
  matching emitters. Method invocations with explicit type
  arguments (`obj.<Type>method(...)`) also refuse; they
  land with the generic-type emitters. The single-line
  argument-list form does NOT yet honor the four-priority
  wrapping rules; calls whose single-line emission exceeds
  80 chars currently emit as-is (no warn) — the
  width-measurement + Pn → Pn+1 promotion logic from the
  spec's "Method Call Arguments" section lands in a later
  phase.
- `tooling/scripts/requirements.txt` — runtime dependency pins
  for the formatter: `tree-sitter==0.25.2` and
  `tree-sitter-java==0.23.5`. Python 3.10+ required.
- `tooling/scripts/tests/test_format_java.py` — smoke tests for
  the Phase 2a scaffolding (15 tests), extended in Phase 2b with
  Emitter and leaf-dispatch tests, and in Phase 2c with
  format_source-end-to-end tests, idempotency tests, and
  unsupported-construct rejection tests, (Phase 2d)
  modifier-emission tests including modifier-order preservation
  and annotation refusal, and (Phase 2e) expression-form
  initializer tests covering arithmetic / comparison / boolean /
  shift / bitwise binary operators, unary `-` / `!` / `~`,
  pre- and post-increment, parenthesization, and ternary
  refusal, and (Phase 2f) single-line expression-operation
  tests covering field access, method calls (with / without
  receiver, with / without arguments, with compound
  arguments), cast expressions, non-pattern instanceof, and
  refusals for the pattern-binding instanceof, record-pattern
  instanceof, explicit-type-witness method call, and
  intersection-type cast forms, and (Phase 2g) method-
  declaration tests covering empty body, modifiers,
  parameter list (zero, one, multiple, array-typed), packed
  field+method members, and refusals for the body-with-
  statements (lifted in Phase 2h), throws, type-parameter,
  and abstract-method forms, and (Phase 2h) statement-emitter
  tests covering return-with-value, return-without-value,
  return-with-expression, expression-statement (method call,
  assignment), compound assignment operators (`+=` / `*=`),
  local variable declarations (single, multiple, with
  modifier), the if-statement-not-yet-registered (now
  lifted; retargeted to for-statement) dispatcher fail-mode,
  (Phase 2i) if/else tests covering simple if-with-block,
  if-else, else-if chain, compound boolean condition, empty
  consequence block, and the brace-less Tier 1 refusal, and
  (Phase 2j) loop tests covering classic for with LVD init,
  bare-expression init, empty `for (;;)`, while loop,
  do-while with cuddled `} while (cond);`, enhanced-for
  with primitive type, enhanced-for with named type,
  and refusals for multi-init and multi-update comma-
  separated forms (130 tests total).

### Changed

- `tooling/scripts/tests/requirements.txt` — now pulls in the
  runtime requirements via `-r ../requirements.txt` so the
  formatter under test has its `tree-sitter` /
  `tree-sitter-java` imports available.
- `.github/workflows/pytest.yaml` — added Python 3.14 to the
  CI matrix alongside 3.10–3.13.
- `.github/dependabot.yml` — added `pip` ecosystem coverage for
  `/tooling/scripts` and `/tooling/scripts/tests` with the
  standard 21-day cooldown so the new `tree-sitter` and
  `tree-sitter-java` pins receive routine update PRs through
  the same gate as the existing Maven and GitHub Actions
  ecosystems.
- `docs/java-coding-standards.md` — substantially expanded and
  rewritten in preparation for the 0.3.0 architectural shift to
  the pure-Python AST-based formatter. The document now covers
  all 25 spec sections (A1–A5 introductory, B1–B12 modern-syntax
  constructs, C1–C8 cross-cutting clarifications), promotes the
  Indentation section to a top-level rule, adds the explicit
  "4 spaces, no tab characters" directive, adds a Trailing
  Whitespace / End-of-File Newline section, and revises the
  Tooling section to describe `tooling/scripts/format_java.py`
  (the upcoming tree-sitter-java AST formatter) as the canonical
  emitter invoked via the `format_file.py` thin wrapper. The
  legacy "Claude Prompt for Java Formatting" section and the
  per-script "Scripted Formatting Notes" section are removed —
  they described the JDT-pipeline-plus-six-override-scripts
  architecture that 0.3.0 supersedes.

### Notes

These entries are the in-progress work on the
`caceres-abandon-jdt-1` branch for the 0.3.0 release. Phase 1
(spec doc), Phase 2a (scaffolding), Phase 2b (token-stream
emission), Phase 2c (minimal structural emitters), Phase 2d
(keyword modifiers), Phase 2e (expression emitters —
binary / unary / update / parenthesized), Phase 2f
(single-line expression operations — field access, method
invocation, cast, instanceof), Phase 2g (method declarations
with empty bodies, formal parameters, array-type parameter
types), Phase 2h (statement emitters in method bodies —
return / expression-statement / local-variable-declaration /
assignment-expression), Phase 2i (if/else control flow —
block emitter, if-with-block, cuddled else, else-if chains),
and Phase 2j (loop statements — classic for, enhanced-for,
while, do-while with cuddled `} while`) have landed, but
`format_java.py` is not yet wired into the format-on-save /
pre-commit hook — the legacy JDT-plus-six-script pipeline at
`format_file.py` is still the active entry point. FAQ refresh
and adoption-template updates are held back until the commit
that removes JDT and activates `format_java.py`, so every
committed snapshot on this branch has an internally-consistent
FAQ-vs-code state.

## [0.2.8] - 2026-05-05

**Note:** Net-pipeline summary line + mtime preservation on
net-zero runs. Supersedes the JDT-only summary line shipped in
0.2.7 — that line was technically accurate but cosmetically
misleading: JDT re-serializes its output even when no formatting
decisions changed, so the summary reported "JDT modified N
files" on every run even when the override scripts undid all of
JDT's byte-level edits and `git diff` was clean.

The 0.2.8 fix snapshots every target's content + atime + mtime
before the pipeline starts, runs JDT and the six override scripts
(unchanged behavior), then compares each file's final content to
the pre-pipeline snapshot. Two consequences:

- The summary line now reports the **net** modified count
  (`Pipeline: <N> files processed, <M> modified.`), so a fully
  spec-compliant codebase reports `0 modified` and matches what
  `git diff` shows.

- Files whose final content is bit-identical to the input have
  their original mtime restored via `os.utime()`. JDT's
  out-of-band write no longer churns IDE reloads, Maven/Gradle
  build caches, or `make`-style timestamp tracking on net-zero
  runs.

### Fixed

`tooling/scripts/format_file.py`:

- Replaced the `_file_signature` helper (which returned a
  size+hash 2-tuple) with `_file_snapshot`, which also captures
  the file's atime and mtime in nanoseconds. The two extra
  fields support the new mtime restore. `FileNotFoundError` is
  the only exception caught; `PermissionError` and other
  `OSError` subclasses propagate intentionally — a permission
  flip mid-pass is a genuine anomaly that should fail loud
  rather than silently count as "modified" in the summary.

- New `_restore_mtime(path, atime_ns, mtime_ns)` helper. Wraps
  `os.utime()` in a broad `try`/`except OSError` and prints a
  one-line `WARNING: could not restore mtime on <path>: <exc>`
  to stderr on any failure. The mtime restore is purely
  cosmetic and must never abort the pipeline.

- `main()` restructured into three explicit stages. Stage 1
  takes a pre-pipeline snapshot of every target. Stage 2 runs
  the JDT pass and the six override scripts (unchanged
  behavior). Stage 3 takes a post-pipeline snapshot, prints the
  net summary, and restores mtimes on bit-identical files. The
  `JDT pass: ...` line from 0.2.7 is replaced by
  `Pipeline: ...`. The summary prints unconditionally when the
  target list is non-empty, including when JDT or an override
  script exited non-zero. The Stage 3 comparison loop catches
  `OSError` per-file, so one unreadable file emits
  `WARNING: could not re-snapshot <path>: <exc>` and is counted
  as modified, rather than crashing the whole orchestrator.

### Tests

- `tooling/scripts/tests/test_format_file.py` — five tests
  renamed `test_jdt_summary_*` -> `test_pipeline_summary_*` and
  their assertions updated from `JDT pass:` to `Pipeline:`. One
  test renamed `test_file_signature_returns_none_for_missing`
  -> `test_file_snapshot_returns_none_for_missing` to track the
  helper rename.

- Three new tests:
  - `test_pipeline_preserves_mtime_when_net_zero` pins a target's
    mtime to a known past value, runs the pipeline against a
    spec-compliant input, and asserts the mtime is unchanged
    after the run.

  - `test_pipeline_advances_mtime_when_modified` does the same
    pin, but with non-compliant input the pipeline rewrites,
    and asserts the mtime DID advance — confirming the restore
    is contingent on byte-content equality, not unconditional.

  - `test_restore_mtime_warns_on_oserror` calls `_restore_mtime`
    on a non-existent path and asserts the helper emits a
    `WARNING` to stderr without raising.

- Total test count: 288 -> 291 (three new tests; no fixture
  changes).

### Migration

Adopting projects pinned to `v0.2.7` should:

1. Bump the submodule pin to `v0.2.8`.

2. The `JDT pass: ...` line that 0.2.7 emitted is replaced by
   a `Pipeline: ...` line of the same shape. Any downstream
   tooling that grepped for `JDT pass:` needs to grep for
   `Pipeline:` instead.

3. On idempotent runs (codebases already in spec-compliant
   shape), the `M modified` count drops to 0 and target file
   mtimes are preserved. IDE / build-cache churn from
   `format_file.py` invocations should disappear in steady
   state.

## [0.2.7] - 2026-05-05

**Note:** Observability fix. The orchestrator now prints a JDT-pass
summary line so users can see how many files were rewritten by the
JDT stage. Previously, a `format_file.py` run that ended with six
"modified 0" rows from the override scripts could hide the fact
that JDT had just rewritten dozens of files in the same pass. No
behavior change to formatting itself; pure reporting.

Surfaced during 0.2.6 adoption in `sz-sdk-java`: an 82-file JDT
rewrite (the wrong-shape `throws`-clause delta) was invisible in
the orchestrator's stdout because none of the Python override
scripts touched those files (JDT had already shaped them
correctly). The user verified the rewrite via `git diff`, but the
orchestrator's own output gave no hint.

### Fixed

- `tooling/scripts/format_file.py` — added a JDT-pass summary line
  emitted between the JDT subprocess and the first override
  script. Format:

  ```
  JDT pass: <N> files processed, <M> modified.
  ```

  Implementation: snapshot `(size, sha256)` for every target file
  before the JDT subprocess runs; recompute after; count entries
  whose pre/post signatures differ. Hashing reuses the existing
  `_sha256(path)` helper (streams in 1 MiB chunks), so memory
  stays bounded on bulk passes over thousands of files. Cost is
  rounding-error compared to JVM startup for the JDT subprocess
  (typical Java sources are KB-scale; a 5,000-file bulk pass
  adds well under a second of disk I/O on SSD).

  The new helper `_file_signature(path)` returns
  `(size, sha256-hex)` for an existing file, or `None` for a
  missing one (so a stat-after-delete doesn't raise; a deleted
  file's `None` compares unequal to its prior signature, which
  correctly counts it as "modified" without a special case at
  the call site).

  The summary line prints unconditionally when the path list is
  non-empty, including when the JDT pass exited non-zero — the
  modified count up to the failure point is more informative than
  silence.

### Changed

- Every shared FAQ under `docs/faqs/` now starts with an H1
  heading (`#`) instead of H2 (`##`), with the rest of each
  file's heading hierarchy shifted up one level to match. The
  H2-as-title convention had accumulated across all five FAQs
  and was flagged in PR review as a CommonMark / GitHub-renderer
  structural error (a document with no H1 is treated as
  title-less by many tools). Sweep covers
  `conventions/adding-new-faqs.md`,
  `conventions/cspell-word-list-policy.md`,
  `building/java-formatting-standards.md`,
  `building/javadoc-reflow-conventions.md`, and
  `testing/system-stubs-and-output-capture.md`. No content
  changes; only heading levels.

### Tests

- `tooling/scripts/tests/test_format_file.py::test_jdt_summary_*`
  — five new unit tests covering: summary line is emitted on a
  successful single-file pass, the count is 0 when no JDT change
  is needed (already-formatted input), `_file_signature` returns
  `None` for a missing file, the summary line is still emitted
  when the JDT subprocess exits non-zero (so a partial-failure
  run is observable in stdout), and the summary line is skipped
  when the resolved target list is empty (so a `--help` passthrough
  doesn't emit a confusing "processed 0, modified 0" line).
- Total test count: 283 → 288 (five new unit tests; no fixture
  changes).

### Migration

No migration needed. Adopting projects pinned to `v0.2.6` should:

1. Bump the submodule pin to `v0.2.7`.
2. Re-run `format_file.py` from the project root or as part of
   normal use; expect one new line of output per invocation that
   resolves to a non-empty target list
   (`JDT pass: <N> files processed, <M> modified.`). Invocations
   that resolve to an empty target list (e.g. `--help`
   passthrough) are unchanged. No diff to source files
   attributable to this change — the summary line is purely
   cosmetic.

## [0.2.6] - 2026-05-05

**Note:** Two-part fix to the multi-exception `throws`-clause
shape produced by the orchestrator. The 0.2.5 JDT profile
force-split every multi-exception clause onto multiple lines
(even when the assembled clause fit within 80 chars) and
indented continuations under `throws` instead of
column-aligning them with the first exception. The spec example
at `docs/java-coding-standards.md` lines 198-213 prescribes
neither shape: stay on one line if the clause fits; otherwise
wrap with each subsequent exception column-aligned under the
first.

The fix has two pieces because JDT alone cannot produce the
spec layout. The JDT alignment value flip eliminates the
premature wrap (Bug 1) and gets `throws` onto its own line.
A new post-JDT override script — `fix_throws_alignment.py` —
then reformats the wrap continuations so they column-align
with the first exception (Bug 2). Together they produce the
spec example output byte-for-byte for both same-line and
column-aligned-wrap cases.

### Fixed

- `tooling/ide/java-formatter.xml` — flipped two settings:
  - `alignment_for_throws_clause_in_method_declaration`: 21 → 33.
  - `alignment_for_throws_clause_in_constructor_declaration`: 21 → 33.

  Bit decomposition of value 33: `M_INDENT_ON_COLUMN (32)` +
  `M_COMPACT_SPLIT (1)`. Pre-0.2.6 was 21 (`M_FORCE (16)` +
  `M_NEXT_PER_LINE_SPLIT (5)` = always wrap to next line, then
  one exception per line). The new value places `throws` on its
  own line (single-indent past the method declaration, per the
  spec) and packs as many exceptions as fit within 80 chars on
  the same line as `throws`. JDT alone, however, cannot
  column-align continuations when wrapping is needed — that's
  what the new script handles.

- `tooling/scripts/fix_throws_alignment.py` — **new** override
  script in the orchestrator pipeline (Tier 6, runs last). For
  any method or constructor `throws` clause it finds, the script
  collects all exception types across single- or multi-line
  inputs, then re-emits the clause in spec layout:
  - Same-line if the assembled clause fits within 80 chars.
  - Otherwise, each subsequent exception on its own continuation
    line, with leading whitespace = method indent + 4 (single
    indent for `throws`) + `len("throws ")` so the first
    character of every exception lands directly under the first
    exception of the `throws` line.

  The script is idempotent (running twice produces the same
  output as running once), defensive (skips any line whose body
  contains a brace `{` or `}`, which is the only structural
  punctuation that cannot legitimately appear inside a clean
  `throws` clause; parens are allowed because they show up in
  annotation argument lists like `@MyAnno(level=ERROR)` and a
  paren-aware comma splitter handles those), and tolerant of
  qualified type names (`java.io.IOException`).

- `tooling/scripts/format_file.py` — added
  `fix_throws_alignment.py` to `SCRIPT_ORDER` after
  `fix_need_braces.py`. Pipeline now runs six override scripts
  after JDT instead of five. Top-of-file docstring updated to
  describe the new Tier 6 step.

### Tests

- `tooling/scripts/tests/fixtures/throws_alignment/` — thirteen
  new fixtures exercising the new script in isolation: single-
  exception class method, single-exception interface, multi-
  exception fits, multi-exception wraps with column alignment,
  compact-packed input re-aligns, qualified type names, already-
  correct idempotency, single-exception under-80 (idempotent),
  single-exception genuinely-over-80 (kept as-is), leading
  annotations on exception types preserved, generic type
  parameters as throws types, constructor throws wraps column-
  aligned, and annotation arguments containing commas
  (`@MyAnno(a=1, b=2)`) — the last guards the paren-aware
  splitter against fragmenting the exception list on inner
  commas. All use generic `Foo` / `AlphaException` /
  `BetaException` / `GammaException` /
  `AReallyLongExceptionTypeName*` /
  `AnUnreasonablyLongExceptionTypeName*` /
  `AnAbsurdlyLongExceptionTypeName*` placeholders — no Senzing
  or SDK identifiers anywhere.
- `tooling/scripts/tests/fixtures/orchestrator/12_throws_clause_multi_exception_fits_one_line`
  — locks in Bug 1 fix end-to-end (three exceptions totaling
  under 80 chars; expected output keeps them on the same line
  as `throws`).
- `tooling/scripts/tests/fixtures/orchestrator/13_throws_clause_multi_exception_wraps_column_aligned`
  — locks in the post-JDT script's column-aligned wrap
  end-to-end (three deliberately-long exception names; expected
  output places the first on the `throws` line, continuations
  paren-aligned under it).
- `tooling/scripts/tests/test_format_file.py::test_canonical_script_order`
  — extended to assert the new six-script pipeline order.
- Total test count: 264 → 282. Breakdown of the +18: 13 new
  fixture cases under `throws_alignment/` × 1 parametrized test
  each = 13; 1 new unit test (`test_returns_tuple`) = 1; 2 new
  orchestrator fixtures under `orchestrator/` × 2 parametrized
  tests each (`test_pipeline_produces_expected_output` and
  `test_pipeline_idempotent`) = 4. The
  `test_canonical_script_order` assertion was extended in place
  (existing test, no count delta).

### Migration

Adopting projects pinned to `v0.2.5` should:

1. Bump the submodule pin to `v0.2.6`.
2. Re-run
   `python3 .java-coding-standards/tooling/scripts/format_file.py`
   from the project root. Expect a small targeted diff at every
   multi-exception `throws` site that was previously force-split
   by 0.2.5; those clauses should re-flow back onto a single
   line (when they fit) or column-align under the first
   exception (when they need to wrap). The bulk count varies by
   project — adoption of 0.2.5 typically left dozens-to-hundreds
   of such sites in a wrong-shape state per consumer codebase.
3. Re-run `mvn -Pcheckstyle validate` from the project root.
   The 0.2.5 wrong-shape clauses didn't fail checkstyle (the
   spec rule has no checkstyle module), so this is mostly a
   readability-and-spec-compliance follow-up.

## [0.2.5] - 2026-05-04

**Note:** Two fixes in this release.

1. **SessionStart hook redesign.** The 0.2.4 attempt at fixing
   the freshness-nudge visibility (redirect `echo` to stderr)
   does not actually work in practice. Empirically verified end-
   to-end against the live origin: Claude Code does not surface
   stderr from `SessionStart` hooks to the user's terminal
   because `SessionStart` is a **non-blocking** hook event — for
   non-blocking events, only stdout reaches the model (as
   captured context) and stderr is dropped from a user-
   visibility standpoint. There is no documented user-visible-
   message channel for `SessionStart` direct-to-terminal at all.

   0.2.5 replaces the broken stderr approach with a stdout-based
   relay-instruction wrapper that the model surfaces to the user
   reliably. The hook also switches the comparison target from
   "behind upstream/main" to "behind latest released tag" via
   `git ls-remote --tags origin`, which (a) eliminates the side
   effect that the prior hook had on the local submodule clone
   (the previous template did `git fetch origin main`, which
   advances the local `origin/main` ref every session start) and
   (b) stops nudging on unreleased commits sitting on `main`.

2. **Javadoc reflow off-by-one.** `fix_javadoc_tags.py` had a
   fast-path for single-line `@param` / `@return` / `@throws`
   inputs that emitted them unchanged regardless of length. When
   the JDT pass re-indented a tag line that fit at the old indent
   but no longer does at the new one (typical when a 2-space-
   indented codebase gets converted to 4-space indent), the
   single-line input could land at 81+ chars and the fast-path
   pass-through left it on disk. The fix closes the off-by-one
   so single-line tag inputs that exceed 80 chars after JDT
   re-indentation now reflow correctly under the 80-char ceiling.

### Fixed

- `adoption/claude-md-templates/claude-hooks-snippet.json` —
  replaced the SessionStart hook command. New command:
  - Uses `git ls-remote --tags origin` (read-only against origin)
    instead of `git fetch -q origin main` (mutates the local
    clone). Eliminates the per-session-start advance of the local
    `refs/remotes/origin/main` ref.
  - Compares the local pin against the latest released tag
    (highest `sort -V`) at origin, not against `main` HEAD.
    Stops nudging on unreleased commits.
  - Resolves both "latest tag's commit SHA" and "current
    commit's tag name (if any)" from the same `ls-remote`
    output by matching `git rev-parse HEAD` against the
    remote's tag→SHA table, with `^{}` suffixes stripped.
    Importantly, this works on submodule clones whose local
    refspec does not fetch tags (the default) —
    `git tag --points-at HEAD` would have returned empty in
    that common case, producing a false "current pin is
    untagged" nudge even when HEAD was at the latest released
    tag.
    The SHA-against-remote-table approach is robust to any
    local tag state.
  - Filters out dereferenced annotated-tag refs
    (`refs/tags/X^{}`) that `ls-remote` emits alongside the
    primary refs, via `grep -v "\^{}$"`.
  - Sanitizes the resolved `$latest` and `$current` tag names —
    rejects (silently exits) if either contains characters
    outside `[A-Za-z0-9._-]`. Defends against an attacker with
    origin write access pushing a tag whose name contains
    crafted text that would otherwise be rendered verbatim
    into the model-relay message. Pure semver tags pass
    through unchanged. Low-severity in practice (requires
    repo write access) but the defense is cheap.
  - When the local pin is out of date, emits an explicit relay
    instruction to **stdout** beginning with
    `INSTRUCTION FOR ASSISTANT (from SessionStart hook): ...`
    that directs the model to surface a verbatim "Heads up:"
    message to the user at the start of its first response.
    Claude Code captures stdout from SessionStart hooks as
    model context, so this is the documented user-visibility
    channel that actually works for SessionStart.
  - Each step uses `... || exit 0` to fall through silently on
    failure (network down, submodule missing, no tags, etc.).
  - The `_comment` block at the top of the snippet was rewritten
    to document the new design and explain why stderr / `exit 2`
    were tried in 0.2.4 and don't work.

- `adoption/adopt-standards-prompt.md` Step 5 — rewrote the
  SessionStart sub-step to describe the new model-relay-via-
  stdout mechanism, the tag-based comparison target, and why
  direct-to-terminal channels don't work for `SessionStart` in
  Claude Code. Updated the migration sub-step to detect any
  pre-0.2.5 hook by checking for any one of three git-plumbing
  substrings: `git fetch -q origin main` (the legacy 0.2.0–0.2.4
  read-write fetch), `git rev-list --count HEAD..origin/main`
  (the legacy 0.2.0–0.2.4 upstream comparison), or
  `git tag --points-at HEAD` (a draft-0.2.5 intermediate that
  used local-tag lookup, broken on fresh submodule clones —
  see the SHA-against-`ls-remote`-table fix above). All three
  are eliminated in the final 0.2.5 hook, so any match flags
  the hook for replacement. The path anchor
  `.java-coding-standards` is also required to avoid
  false-positive matches on user-customized hooks for unrelated
  submodules.

- `tooling/scripts/fix_javadoc_tags.py` — fixed the fast-path
  for single-line `@tag` inputs. The script now checks whether
  the reconstructed single-line output exceeds `MAX_LINE` (80);
  if so, it falls through to the multi-word wrap logic instead
  of emitting unchanged. The reflow logic itself was already
  correct (uses `<= max_content` for boundary acceptance); the
  fast path just bypassed it. Added an inline comment
  explaining the failure mode the new check guards against.

### Tests

- `tooling/scripts/tests/fixtures/javadoc_tags/07_single_line_param_overshoots_eighty`
  — new fixture reproducing the bug: a single-line `@param`
  input at 81 chars. Expected output wraps the description with
  the continuation aligned at the description-start column,
  matching the multi-line shape `fix_javadoc_tags.py` produces
  for already-wrapped `@param` blocks.
- Total test count: 261 → 264 (one new fixture × per-script +
  per-script-idempotency + cross-script-idempotency = 3 tests).

### Migration

Adopting projects pinned to `v0.2.0`–`v0.2.4` should:

1. Bump the submodule pin to `v0.2.5`.
2. **For the SessionStart hook**, update the command in
   `.claude/settings.json`. Two paths:
   - **Re-run `/init-java`** (recommended). The 0.2.5 adoption
     prompt detects any pre-0.2.5 hook (matching any one of
     `git fetch -q origin main`,
     `git rev-list --count HEAD..origin/main`, or
     `git tag --points-at HEAD`) and offers a one-step
     replacement, preserving any other SessionStart entries.
   - **Hand-patch.** Replace the `command` string in the
     `SessionStart` hook with the value from the 0.2.5
     `claude-hooks-snippet.json` template.
3. **For the javadoc reflow fix**, re-run
   `python3 .java-coding-standards/tooling/scripts/format_file.py`
   from the project root. Expect a small targeted diff at sites
   where a single-line `@param` / `@return` / `@throws` input
   exceeded 80 chars after JDT re-indentation; those lines now
   wrap correctly. No diff at sites that were already
   well-wrapped or under 80 chars.
4. Re-run `mvn -Pcheckstyle validate` from the project root.
   Any remaining `LineLength` violations in javadoc tag
   descriptions should clear; if any remain, they are
   source-side issues unrelated to this fix.

To verify the SessionStart fix end-to-end, with the submodule
artificially one tag behind the latest origin tag:

```bash
cd .java-coding-standards
git fetch --tags origin -q   # populate local tag refs (submodule
                             # clones don't have them by default)
git reset --hard <previous-tag> -q
cd ..
claude --continue
```

The model should surface a verbatim message in its first
response: `Heads up: .java-coding-standards has a newer release
available (X.Y.Z); current pin is X.Y.W. Run /init-java to
refresh.` (where X.Y.Z is the latest released tag and X.Y.W is
the previously-pinned tag, or `untagged` if HEAD points at an
unreleased commit).

## [0.2.4] - 2026-05-04

**Note:** Two fixes in this release:

1. **SessionStart hook visibility.** The `SessionStart` hook
   shipped in `adoption/claude-md-templates/claude-hooks-snippet.json`
   since 0.2.0 has been writing its "submodule is behind upstream"
   nudge to stdout. Per the Claude Code hooks documentation,
   stdout from a `SessionStart` hook is captured as additional
   context for the model and is **not** shown to the user;
   stderr is what appears in the user's terminal banner at
   session start. Result: the freshness-nudge integration
   described in the adoption prompt has been **non-functional
   from the user's perspective** in every consumer project that
   ran `/init-java` against 0.2.0–0.2.3 — the hook fired, the
   model saw the message, the user (the intended audience) saw
   nothing.

2. **Remaining JDT LineLength regressions.** 0.2.3 fixed the
   first-wrap over-indent on string-concat-in-method-call
   patterns. A separate, longstanding JDT issue produced **52
   `LineLength` violations** of three other shapes: assignments
   to long string literals, class declarations with long
   generic-parameter lists, and variable declarations with long
   generic types. Each shape had a relevant
   `org.eclipse.jdt.core.formatter.alignment_for_*` key set to
   `0` (NO_ALIGNMENT — never wrap), so JDT joined the
   pre-formatted source onto a single over-80 line at every
   site. Plus `wrap_before_assignment_operator` was `false`,
   which would put `=` at the end of the previous line on a
   wrap rather than starting the continuation line per the
   spec's "operator starts the continuation line" rule.

### Fixed

- `adoption/claude-md-templates/claude-hooks-snippet.json` — the
  `SessionStart` hook's `echo` is now redirected to stderr
  (`>&2`) so the nudge surfaces in the user's terminal at
  session start. The `_comment` block at the top of the snippet
  was extended to document the stdout/stderr distinction so
  future maintainers don't regress the fix.
- `adoption/adopt-standards-prompt.md` Step 5 (hooks merge) —
  added a `### Migration` sub-step that scans an existing
  `.claude/settings.json` for the buggy 0.2.0–0.2.3 SessionStart
  command (matches "NOTE: .java-coding-standards is " without
  the stderr redirect) and offers to replace it via
  `AskUserQuestion`. Catches every consumer project on its next
  `/init-java` refresh without requiring users to know the bug
  existed. The accompanying SessionStart explanation now
  documents why the redirect is load-bearing.
- `tooling/ide/java-formatter.xml` — flipped four JDT keys to
  let the formatter wrap long declarations at split points the
  spec already permits:
  - `alignment_for_assignment` 0 → 16: JDT will now wrap at the
    `=` operator when an assignment exceeds 80 chars (covers
    `static final String FOO = "long literal";` and
    `Map<...> name = new ...<>();`).
  - `alignment_for_type_parameters` 0 → 16: JDT will wrap inside
    a class's `<...>` declaration when the type-parameter list
    pushes the line past 80 chars.
  - `alignment_for_type_arguments` 0 → 16: same for
    type-argument lists on method calls and generic instantiations.
  - `wrap_before_assignment_operator` false → true: when the
    `=` wrap fires, the `=` starts the continuation line per
    the spec's "operator starts the continuation line" rule.

  Value 16 = M_FORCE (no other flags), which combined with
  `continuation_indentation=1` (from 0.2.3) produces a +4
  per-level wrap — matching the spec's continuation indent.

### Tests

- `tooling/scripts/tests/fixtures/orchestrator/09_long_assignment_wraps_at_eq`
  — generic `static final String NAME = "long path...";` that
  exceeds 80 chars; expected output wraps at `=` with `=`
  starting the continuation line.
- `tooling/scripts/tests/fixtures/orchestrator/10_long_generic_class_decl_wraps`
  — generic class declaration with `<E extends ..., B extends ...>`
  that exceeds 80; expected output wraps inside the angle
  brackets at the comma between type parameters.
- `tooling/scripts/tests/fixtures/orchestrator/11_long_generic_var_decl_wraps_at_eq`
  — generic local variable declaration with nested generics
  that exceeds 80; expected output wraps at `=`.
- Total test count: 255 → 261 (three new fixtures × two
  pipeline-test variants).

### Migration

Adopting projects pinned to `v0.2.0`–`v0.2.3` should:

1. Bump the submodule pin to `v0.2.4`.
2. **For the SessionStart hook**, update the command in
   `.claude/settings.json`. Two paths:
   - **Re-run `/init-java`** (recommended). The 0.2.4 adoption
     prompt detects the missing `>&2` and offers to fix it in
     place, preserving any other SessionStart entries.
   - **Hand-patch.** In `.claude/settings.json`, locate the
     SessionStart hook's `command` string and append `>&2`
     immediately after the closing quote of the `echo`
     argument (just before `|| true`):

     ```diff
     - && echo "NOTE: ... refresh." || true
     + && echo "NOTE: ... refresh." >&2 || true
     ```

3. **For the JDT LineLength fix**, re-run
   `python3 .java-coding-standards/tooling/scripts/format_file.py`
   from the project root. Expect a small targeted diff at each
   long-declaration site (assignments, generic class
   declarations, generic variable declarations). The diff
   should be review-friendly compared to 0.2.3's wider
   continuation-indent reflow.
4. Re-run `mvn -Pcheckstyle validate` from the project root.
   `LineLength` violations from these three categories should
   clear; any remaining violations (e.g., long string literals
   inside `// CSOFF: LineLength` blocks, or items already
   exempted by the `static final.*<.*>` ignore pattern) are
   pre-existing and unaffected.

To verify the SessionStart fix end-to-end, quit and resume
Claude Code with the submodule artificially one commit behind
upstream:

```bash
cd .java-coding-standards
git reset --hard HEAD~1
cd ..
claude --continue
```

The nudge
`NOTE: .java-coding-standards is 1 commits behind upstream/main. Run /init-java to refresh.`
should appear in the terminal banner before the input prompt.

## [0.2.3] - 2026-05-04

**Note:** Third orchestrator-regression fix in the 0.2.x series.
0.2.2 closed the `} catch / else / finally` and Tier 1 collapse
bugs but left a per-wrap-level over-indent: every JDT line wrap
added +8 of indent rather than the documented +4 per wrap level.
For shallow wraps the over-indent was cosmetic (cumulating to +8
from base instead of the documented +4); for nested wraps it
cumulated to +16 on double-wraps and +24 on triple-wraps, where
the documented cumulative effect is +8 and +12 respectively. The
overshoot pushed wrapped lines in string-concat-in-method-call
patterns past the 80-character limit. 0.2.3 corrects the per-wrap
indent so JDT output matches the spec example in
`docs/java-coding-standards.md` byte-for-byte:

```java
    throw new IllegalArgumentException(
        "Cannot specify a secondary value when "
            + "the primary value is null.  primary=[ "
            + primary + " ], secondary=[ "
            + secondary + " ]");
```

— first wrapped argument at single-indent (+4) past the
statement base; each subsequent operator continuation at
single-indent past the previous wrap (cumulating to +8 past
the statement base, matching the "8 spaces from base" wording
in the rule statement).

### Fixed

- `tooling/ide/java-formatter.xml` line 34 — flipped
  `continuation_indentation` from `2` to `1`. JDT applies this
  setting per wrap level, not cumulatively across wraps. With
  `2` (= 2 × indentation_size = 8 spaces), the first wrap
  landed at +8 from base and each subsequent wrap added another
  +8, producing the +16 / +24 / ... cascade the regression
  report cataloged. With `1` (= 1 × indentation_size = 4 spaces)
  per wrap level, the cumulative indent matches the spec
  example: first wrap +4, subsequent wraps +4 from each
  previous wrap (so +8 from base for double-wraps, +12 for
  triple, etc.).

  This release also reframes a long-standing wording ambiguity
  in the standards doc. Pre-0.2.3, the "General Continuation
  Indentation" section read "Continuation lines use 8 spaces
  (double indent) from the base indentation of the statement"
  — that wording described the cumulative effect for second-
  and-deeper wraps; the first wrap is single-indent (+4 from
  base), as the spec example shows. The same release rewrites
  that section and the four short-form summaries elsewhere in
  the docs to make the per-level vs cumulative distinction
  explicit. The `continuation_indentation` JDT setting is the
  per-level value (now `1`); the cumulative effect is what the
  rule describes.

### Tests

- `tooling/scripts/tests/fixtures/orchestrator/08_string_concat_spec_layout`
  — new end-to-end fixture that reproduces the spec example
  layout byte-for-byte. Locks in the fix and forestalls future
  regressions.
- `tooling/scripts/tests/fixtures/orchestrator/01_user_failure_cases/expected.java`
  and `03_long_line_wrapping/expected.java` — updated. Both
  fixtures previously locked in the buggy double-indent JDT
  output; the new expected files match the spec-aligned
  single-indent layout. No other fixtures changed.
- Total test count: 253 → 255 (one new fixture × two pipeline
  test variants).

### Migration

Adopting projects pinned to `v0.2.2` should:

1. Bump the submodule pin to `v0.2.3`.
2. Re-run `python3 .java-coding-standards/tooling/scripts/format_file.py`
   from the project root. Expect a content diff on any file that
   contains multi-line method-call args or string concatenations
   — JDT's wrap indent moves from +8 to +4 per level, which
   re-formats the affected lines. For typical Senzing Java
   codebases this means **most non-trivial source files will
   re-flow at least one wrap**; review the generated diff in
   focused chunks (per-package or per-pattern) rather than as a
   single monolithic commit.
3. Re-run `mvn -Pcheckstyle validate` from the project root.
   `LineLength` violations introduced by the 0.2.2 over-indent
   should clear. Any remaining `LineLength` violations are
   source-side issues not addressed by this PR — typically:
   - long string literals that exceed 80 chars even at the
     spec's correct indent (shorten or split),
   - generic type parameter lists on class declarations that
     JDT does not wrap (`alignment_for_type_parameters=0` is
     unchanged in this release; if your project has these,
     hand-wrap or wrap in `// @formatter:off` /
     `// @formatter:on`).

## [0.2.2] - 2026-05-04

**Note:** This release fixes two orchestrator regressions that
surfaced when adopting the standards in a consumer project.
Running
`format_file.py` (bulk mode) against a codebase that **passes**
`mvn -Pcheckstyle validate` was producing **123 checkstyle
violations** across the same codebase — contradicting the
orchestrator's "compliant in, compliant out" contract. Both root
causes are inside the standards repo (the JDT profile and one
override script); consumer projects need only bump the submodule
pin.

### Fixed

- `tooling/ide/java-formatter.xml` — flipped four
  `insert_new_line_before_*` keys (catch/else/finally/while) from
  `insert` to `do not insert` so the JDT pass keeps `} catch`,
  `} else`, `} finally`, and `} while` (in `do/while`) on the
  same line as the closing brace. The shared
  `senzing-checkstyle.xml` rule `RightCurly{option=same}`
  requires same-line braces for `LITERAL_TRY`, `LITERAL_CATCH`,
  `LITERAL_FINALLY`, `LITERAL_IF`, `LITERAL_ELSE`, and
  `LITERAL_DO`. Before this fix, every try/catch and if/else
  block the JDT pass touched produced a checkstyle violation.

- `tooling/ide/java-formatter.xml` — flipped
  `format_guardian_clause_on_one_line` from `true` to `false`.
  With `true`, JDT was collapsing
  `if (cond) {\n stmt;\n }` (a Tier 2 braced shape) to
  `if (cond) { stmt; }` (a single-line braced shape that's
  neither Tier 1 nor Tier 2 of the Senzing standard). The
  override script `fix_need_braces.py` couldn't recognize the
  collapsed shape, so the result stayed on disk. With `false`
  JDT leaves the multi-line braced form alone, which the script
  now picks up (see below) and converts to Tier 1.

- `tooling/scripts/fix_need_braces.py` — added a new pass that
  detects the multi-line braced
  `if (cond) {\n stmt;\n }` shape and collapses to Tier 1
  brace-less form `if (cond) stmt;` when:
  - `stmt` is a short-circuit statement (`return`, `continue`,
    `break`, `throw`),
  - no `else` clause is paired with the `if`,
  - the brace-less form fits within 80 characters,
  - no comments or blank lines sit between the header, the body,
    or the closing brace (those would be lost in the collapse —
    the braced form is preserved when they're present).

  Note: this script targets the multi-line braced shape that JDT
  produces with `format_guardian_clause_on_one_line=false`. The
  full orchestrator (`format_file.py`) is the supported entry
  point for end-to-end formatting; running `fix_need_braces.py`
  standalone against a file that contains a single-line braced
  `if (cond) { stmt; }` will leave it unchanged.

- `tooling/ide/java-formatter.xml` line 306 — typo fix for an
  Eclipse JDT key. The previous spelling
  `keep_imple_if_on_one_line` was unrecognized by JDT and
  silently fell back to the default (which happened to match the
  intended `false`, so the bug was harmless). Renamed to the
  correct `keep_simple_if_on_one_line` so the value is actually
  applied.

### Changed

- `tooling/jdt-formatter/pom.xml` — bumps the Eclipse JDT
  dependency `org.eclipse.jdt:org.eclipse.jdt.core` from `3.42.0`
  to `3.45.0`. Routine version bump to stay current on the
  Eclipse 3.x line; no formatter behavior change observed (all 7
  orchestrator pipeline fixtures produce byte-identical output
  against the new dep).

### Tests

- `tooling/scripts/tests/fixtures/need_braces/` — 13 new
  fixtures cover the new behavior:
  - `10_braced_short_circuit_collapses_to_tier1` (return body)
  - `11_braced_non_short_circuit_kept` (method-call and
    assignment bodies stay braced)
  - `12_braced_if_else_pair_kept` (paired `else` blocks the
    collapse — both branches stay braced per the if/else rule)
  - `13_braced_short_circuit_too_long_kept` (line would exceed
    80 chars — stays braced)
  - `14_braced_short_circuit_with_comment_kept` (comment between
    header and body — stays braced to preserve the comment)
  - `15`/`16`/`17_braced_short_circuit_*` — `continue`, `break`,
    and `throw` body forms.
  - `18_braced_else_if_chain_kept` (`if {…} else if {…}` ladder
    — `m_close` correctly fails on `} else if (...) {` so neither
    branch collapses).
  - `19_braced_short_circuit_with_blank_line_kept` (blank line
    between header and body — collapse aborts).
  - `20_braced_short_circuit_trailing_comment_kept` (comment
    between body and close brace — collapse aborts).
  - `21_braced_short_circuit_nested_collapses` (nested braced
    short-circuit — outer kept, inner collapses to Tier 1).
  - `22_braced_short_circuit_with_paired_else_kept` (paired
    `else` whose `if` body would otherwise be Tier-1-eligible,
    in Allman form with `}` and `else` on separate lines — the
    `has_else` lookahead blocks the collapse, both branches
    stay braced. Fixture 12 covers the same case in the more
    common same-line `} else {` shape; fixture 22 specifically
    exercises the lookahead path that defends against legacy
    or hand-edited Allman-style sources).
- `tooling/scripts/tests/fixtures/orchestrator/` — three new
  end-to-end pipeline fixtures:
  - `05_keep_same_line_catch_else_finally`
  - `06_keep_same_line_do_while`
  - `07_braced_short_circuit_collapses`
- Total test count rises from 208 (0.2.1) to 253. (Each
  fixture is exercised by both its per-script test and the
  `test_idempotency.py::test_double_pass_converges`
  cross-script idempotency test, so each new need_braces
  fixture adds two tests.)

### Stylistic notes — investigated, deliberately not changed

The original regression report flagged two further "lower
priority, not failing checkstyle" stylistic differences. Both
were investigated; neither has a one-line JDT profile fix that
preserves the exact previous output without other regressions:

- **Hand-tuned column alignment of related field assignments**
  (`this.readWriteLock  = ...` / `this.instanceName   = ...`):
  JDT collapses extra whitespace by default. Setting
  `align_assignment_statements_on_columns=true` would auto-align
  but applies a JDT-internal scheme to _every_ assignment block,
  not just the ones the developer hand-tuned. The supported way
  to preserve developer-tuned alignment is to wrap the block in
  `// @formatter:off` … `// @formatter:on` (the profile already
  has `use_on_off_tags=true`).

- **Continuation-indent style change in long expressions and
  string concatenation**: the consumer project's source pre-fix
  used 4-space single-indent continuation, but the canonical
  `docs/java-coding-standards.md` rule (line 314) is **8 spaces
  (double indent)**. JDT applies the documented rule, so the
  diff against the prior code is JDT _correcting_ pre-existing
  non-compliance, not introducing regression. The corrected
  indent does push some lines over 80 characters when the
  literal text is too long; those need source-side fixes
  (shorter strings or different break points), not profile
  tuning.

### Migration

Adopting projects that pinned the standards submodule to
`v0.2.1` and ran the bulk orchestrator should:

1. Bump the submodule pin to `v0.2.2`.
2. Re-run `python3 .java-coding-standards/tooling/scripts/format_file.py`
   from the project root. Expect to see content changes from the
   continuation-indent and Tier 1 collapse fixes, and from any
   pre-existing source code that wasn't fully standards-compliant
   already.
3. Re-run `mvn -Pcheckstyle validate` from the project root.
   Files that were correctable should pass; any remaining
   violations are source-side issues to fix by hand (typically:
   long string literals that no longer fit at 8-space
   continuation indent).

If you hit a `LineLength` violation that JDT can't fix
automatically, shorten the literal, or wrap a deliberately-aligned
block in `// @formatter:off` / `// @formatter:on` if preserving
the layout matters more than a few characters of width.

## [0.2.1] - 2026-05-01

**Note:** This is a small follow-up to 0.2.0 that fixes the
layered-suppressions design so the project-local
`checkstyle-suppressions-local.xml` extension point actually takes
effect. 0.2.0 wired both the shared baseline and the project-local
file into `maven-checkstyle-plugin` 3.6.0 via a comma-separated
`<suppressionsLocation>` value, but the plugin silently honored
only the first path — generated-file carve-outs (e.g.
auto-generated wrapper classes in adopting projects) never
engaged. The fix
moves the wiring inside `senzing-checkstyle.xml` itself, where
checkstyle loads the filters reliably.

### Fixed

- `checkstyle/senzing-checkstyle.xml` now declares two
  `<module name="SuppressionFilter">` entries directly. The first
  loads the shared `senzing-checkstyle-suppressions.xml` via the
  canonical submodule mount path
  (`.java-coding-standards/checkstyle/senzing-checkstyle-suppressions.xml`),
  resolved relative to the Maven working directory. The second
  loads `checkstyle-suppressions-local.xml` from the project root
  the same way, with `optional="true"` so projects without a
  project-local file don't fail. (An earlier draft tried
  `${samedir}` for the shared path, but
  `maven-checkstyle-plugin` 3.6.0 does not auto-populate that
  property in this configuration — the working-directory-relative
  path is the reliable mechanism.)

### Changed

- `adoption/claude-md-templates/pom-checkstyle-profile.xml` no
  longer sets `<suppressionsLocation>`. The consumer pom is
  simpler — only `<configLocation>` is required. The header
  comment documents the new mechanism and notes that this
  supersedes the broken comma-separated wiring.
- `adoption/adopt-standards-prompt.md` step 3 (pom wiring) and
  step 11 (generated-file exclusions) updated to describe the new
  flow: create `checkstyle-suppressions-local.xml` at the project
  root and the shared config picks it up automatically — no pom
  edit required. When replacing an older checkstyle profile,
  delete any leftover `<suppressionsLocation>` line.
- `tooling/jdt-formatter/pom.xml` bumped from 0.2.0 to 0.2.1.
  `format_file.py` reads this version at runtime to construct the
  GitHub Release URL it downloads the JAR from
  (`.../releases/download/v<version>/jdt-formatter.jar`); the pom
  version must match the git tag.

### Migration

Adopting projects that pinned the standards submodule to
`v0.2.0` and ran the adoption flow at that version need to:

1. Bump the submodule pin to `v0.2.1`.
2. Re-run `/init-java`, or manually drop the
   `<suppressionsLocation>` line from the `checkstyle` profile in
   their `pom.xml`. Leaving it in is harmless (the plugin
   parameter becomes a no-op once the embedded filters fire) but
   misleading.
3. Re-run `mvn -Pcheckstyle validate` **from the project root**
   (not a sub-module directory — both suppressions paths now
   resolve relative to the Maven working directory). Project-local
   `checkstyle-suppressions-local.xml` rules will engage for the
   first time — confirm no regressions surface (e.g. files that
   were silently checked at 0.2.0 because the project-local
   suppressions weren't loading may now report new violations
   that the suppressions are explicitly silencing).

## [0.2.0] - 2026-04-30

**Note:** This release closes the longstanding gap that the
bulk-format Python scripts didn't actually format Java code —
only brace placement, javadoc reflow, and short-circuit `if`
rules. A file with mis-indented code or lines longer than 80
characters passed through the orchestrator unchanged, leaving
developers to chase those issues by hand or via VS Code's
built-in formatter (which itself was disabled due to
brace-placement conflicts).

The orchestrator is now a true single-command formatter. Running
`format_file.py path/to/File.java` produces a file that satisfies
`mvn -Pcheckstyle validate`, regardless of caller (CLI, VS Code
runonsave, Claude Code PostToolUse hook, CI pre-commit).

### Added

- `tooling/jdt-formatter/` — small Java CLI shim around the
  Eclipse JDT formatter
  (`org.eclipse.jdt:org.eclipse.jdt.core 3.42.0`).
  Reads the existing `tooling/ide/java-formatter.xml` profile
  and formats Java files in place. Source-only — the built fat
  JAR is published as a GitHub Release asset (see
  Release-asset distribution below) and never committed.
- `tooling/scripts/tests/test_format_file_jdt_pipeline.py` — new
  pytest module covering the orchestrator's combined
  JDT-then-scripts behavior, including the user-reported failure
  modes (over-indented brace, long line, bad spacing, missing
  braces around assignment-style if body) and a baseline-excludes
  protection check.
- `tooling/scripts/tests/test_jar_resolution.py` — unit tests for
  the JAR resolution helpers (cache hit, SHA-256 verification,
  download failure cleanup, version parsing).
- `tooling/scripts/tests/fixtures/orchestrator/` — fixture corpus
  for the pipeline tests (byte-comparable input.java/expected.java
  pairs).
- `.github/workflows/release.yaml` — on `v*` tag push, builds the
  JDT formatter JAR, computes its SHA-256, and publishes both as
  attachments on a GitHub Release. Triggered by the maintainer
  cutting a tag; no auto-commit of binaries.

### Changed

- `tooling/scripts/format_file.py` — orchestrator now runs an
  Eclipse JDT formatter pass first (general Java formatting:
  indent, line wrap, continuation-indent, ternary tiers,
  operator-on-continuation, alignment, whitespace), then the
  existing five `fix_*.py` scripts in canonical order
  (overrides: Allman brace placement, javadoc no-orphan reflow,
  short-circuit `if` rules). The five scripts are unchanged in
  behavior; their 190-test corpus is unchanged.
- `tooling/scripts/format_file.py` — JAR resolution: tries (1) a
  local Maven build at `tooling/jdt-formatter/target/jdt-formatter.jar`,
  (2) a cached download, (3) download from the matching GitHub
  Release with SHA-256 verification, (4) a Maven build-from-source
  fallback. Cache directory honors `XDG_CACHE_HOME` and a project-
  specific `SENZING_STANDARDS_CACHE_DIR` env var.
- `adoption/claude-md-templates/vscode-settings-snippet.json` —
  comment block clarifies the rationale for keeping
  `[java].editor.formatOnSave: false`: redhat.java's built-in
  format-on-save would run JDT a second time redundantly with
  emeraldwalk.runonsave invoking the orchestrator. The
  orchestrator runs JDT once internally with the right ordering.
- `.github/workflows/pytest.yaml` — adds a JDK 17 setup step and
  builds `jdt-formatter.jar` from source before invoking pytest,
  populating the local-build resolution path the suite expects.
- `.github/dependabot.yml` — Maven `directory` retargeted from
  `/` (no manifest) to `/tooling/jdt-formatter`. Dependabot now
  tracks `org.eclipse.jdt:org.eclipse.jdt.core` with the
  standard 21-day cooldown.

### Removed

- `tooling/jdt-formatter/jdt-formatter.jar` — the previously-
  committed binary. JARs are no longer in git history; they live
  on GitHub Releases. Addresses the supply-chain concern that
  Dependabot bumps were auto-committing opaque (un-reviewable)
  binary content.
- `.github/workflows/rebuild-jdt-formatter-jar.yaml` — no longer
  needed; the JAR isn't committed, so there's nothing to keep in
  sync on a Dependabot PR. The release workflow handles JAR
  publishing on demand.

### Release-asset distribution

The JDT formatter JAR is published as a GitHub Release asset
rather than committed to git. For each `v*` tag:

- `release.yaml` builds the JAR from source under
  `tooling/jdt-formatter/`.
- Computes a SHA-256 digest, written to a `.sha256` sidecar.
- Creates the GitHub Release and attaches both
  `jdt-formatter.jar` and `jdt-formatter.jar.sha256`.

`format_file.py` downloads the JAR (and sidecar) from the release
matching the version pinned in `tooling/jdt-formatter/pom.xml`,
verifies the SHA-256, and caches the result under
`~/.cache/senzing-java-coding-standards/`. Subsequent invocations
are zero-network. Override the cache location with
`SENZING_STANDARDS_CACHE_DIR`; override the release URL base with
`SENZING_STANDARDS_RELEASE_BASE` (for forks or air-gapped mirrors).

Why this matters: a compromised Maven dependency picked up by a
Dependabot bump used to be auto-committed as opaque binary
content with no human review. Now Dependabot bumps update only
`pom.xml` (text, reviewable) and the JAR is rebuilt deterministically
when a maintainer cuts a release tag.

### Migration

Consumer projects bumping their submodule pin to this release
will, on next `format_file.py` invocation:

1. Download the JAR from `https://github.com/senzing-garage/java-coding-standards/releases/download/v0.2.0/jdt-formatter.jar`
   (one-time per machine; cached afterward).
2. Pick up the JDT pass automatically — no further consumer
   action required.
3. Produce a one-time format-compliance diff for any source
   that wasn't previously fully compliant (especially indent,
   line wrap, alignment). Commit as a follow-up "format
   compliance" pass.
4. Subsequent runs are idempotent (verified by the pipeline
   test corpus).

JDK 17+ is required (already required for any consumer's Maven
build). For air-gapped environments, run `mvn package` once in
`tooling/jdt-formatter/` to populate the local build path; the
orchestrator finds it before attempting the download.

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
- `tooling/scripts/tests/` — pytest suite (190 tests) for the
  bulk-format scripts: per-script fixture-driven cases, helper
  unit tests, idempotency cross-cut, and orchestrator tests.
  43 fixture pairs across the five scripts. Required to pass
  before merge via `.github/workflows/pytest.yaml` (Python
  3.10–3.13 × ubuntu-latest + macos-latest matrix).
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
  SessionStart freshness fetch runs
  `git -c http.lowSpeedLimit=1000 http.lowSpeedTime=3 fetch`,
  so it aborts after 3 s in slow or unreliable network conditions
  instead of hanging on a degraded connection.

## [0.0.0] - 2026-04-29

### Changes/Additions/Fixes in version 0.0.0
