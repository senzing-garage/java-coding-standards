# Changelog

All notable changes to this project will be documented in this file.

The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
[markdownlint](https://dlaa.me/markdownlint/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- **Javadoc `<pre>` block preservation extended to HTML-escaped
  variants.** `_emit_javadoc_block`'s `<pre>` region detector
  now matches `&lt;pre&gt;` / `&lt;/pre&gt;` in addition to the
  raw `<pre>` / `</pre>` tags. Consumer trial surfaced ASCII
  class diagrams inside escaped `<pre>` blocks being reflowed
  as prose (data loss), because the diagram lives inside another
  HTML tag (`<h2>Class Diagram</h2> <pre>...</pre>`) that forces
  the `<` chars to be escaped. Locked by new fixture
  `javadoc_reflow/07_escaped_pre_block_preserved`.
- **Arg-list multi-arg cascade rejects P1 mixed-shape commit when
  arg's emission cascades through arg-list P4.** Consumer trial
  surfaced sites where P1's item-8 break-before-subsequent-args
  invariant produced the "arg 0 packed on call line with own args
  wrapped at line-start+4, args 1+ paren-aligned" mixed shape —
  `SzFlagTest.java:551` in sz-sdk-java. Adds a save-reset-check-
  restore cycle around `emit_p1` and rejects the commit when
  `Emitter._arg_list_p4_fired` transitions False→True during the
  emit. Falls through to P2 (which already rejects on P4) and
  ultimately P3 (paren-aligned one-per-line) — the spec-compliant
  shape.
- **Arg-list P3 rejects when arg 0 (packed with `(`) fires P4.**
  P3 packs arg 0 with the opening `(`; if arg 0's own emission
  cascades through arg-list P4, its anchor derives from the OUTER
  line's leading spaces (potentially much shallower than cont_col)
  — same deep-orphan pathology as P1. Tracks arg 0's P4 firing
  via a closure-scoped `[False]` list (distinguishes from args
  1+ firing P4 at deeper paren-align cols, which is spec-
  compliant and shouldn't reject). Fall-through to P4 (block+4
  one-per-line) produces the compact spec-compliant shape.
  Fixture `arg_list_wrap/04_item8_prev_arg_multi_row_breaks_next`
  updated: pre-0.6 emitted the mixed shape; now emits P3
  paren-aligned one-per-line.

## [0.6.0] - 2026-07-09

Formatter release covering all five in-scope items from
`.claude/060_SCOPE.md`: P0 source-preserve rework,
P1 assignment_expression wrap, P2 method-chain cascade
(five factory tiers, four constructor tiers, Q-CHAIN-1
through Q-CHAIN-5 resolutions), P3 cross-statement
smoothing (achieved by P0's local convergence), and P4 SQL
DDL detector. P5 (enum type_parameters / `permits`)
remains a JLS-refusal since neither is legal Java per
JLS §8.9.

### Additional fixes surfaced by consumer trial

- **P2 method-call arg-list re-tightened to two-line strict;
  new P3 paren-aligned one-per-line candidate added.** Per
  spec "Method Call Arguments / Priority 2 — Two-line,
  paren-aligned, comma-packed": P2 must fit "on exactly two
  lines" (call line + one continuation line). The pre-0.6
  `emit_p2_greedy` allowed N-line packed shapes, violating
  the spec. 0.6.0 enforces the two-line invariant via
  `p2_line_count <= 1` check on the emitted lines, and
  cascades to a new `emit_p3_paren_one_per_line` candidate
  when P2 doesn't fit. Multi-arg cascade for
  `_emit_argument_list` refactored from `try_priorities` to
  manual snapshot/restore since P2's line-count constraint
  can't be expressed as a pure width check. New cascade:
  P1 inline → P2 two-line packed → P3 paren-aligned
  one-per-line → P4 block+4 one-per-line (spec C1 emit-and-
  warn fallback). Fixture updates driven by this rule:
  `arg_list_wrap/08_shift_up_overflow_declines_source_preserve`
  (was 3-line greedy, now 6-arg one-per-line P3) and
  `arg_list_wrap/12_defect_3_nested_paren_contained`
  (was 3-line greedy, now 5-arg one-per-line P3).
- **Arg-list `emit_p2_greedy` also rejects pack when the
  packed arg's emission cascades through arg-list P4** (a
  packed arg like `this.getEntityId(reallyLongIdent)` that
  wraps its own inner arg produced the "split call on
  same line as previous arg" shape). Same detection
  mechanism as binary's `paren_inner_wrap` — checks
  `Emitter._arg_list_p4_fired` transition around each
  operand emit. Prefers break-then-inline over
  pack-then-inner-wrap when both take the same total line
  count. Directly surfaced by the consumer trial's
  `SzEngineGraphTest.java:702` `Arguments.of(...)` shape.
- **Nested arg-list P4 anchor changed from `block+4` to
  `line-start-col + 4`.** `_emit_argument_list`'s
  `emit_p4_multi_arg` and `emit_p4_single_arg_block_indent`
  previously anchored to `block + 4` (indent + 4 relative
  to the outer statement's block). That produced visually
  correct output for statement-top-level P4 emissions
  (where line-start equals block indent), but ORPHANED
  nested emissions when the outer context had its own
  continuation indent (chain-tail, nested-paren-aligned
  outer arg-list): a `SzRecordKeys.of(\n    avoidances)`
  inside `engine.findPath(<paren-aligned args at col 60>)`
  landed `avoidances` at col 25 — 35 columns LEFT of the
  enclosing paren. The new anchor is
  `line-start-col + 4` where `line-start-col` is the col
  of the first non-space char on the current in-progress
  line. Under the new rule, nested emissions land at
  `col 64` — visually contained inside the outer paren.
  For statement-top-level P4 emissions the two rules
  coincide, so most fixtures are unchanged; only nested
  cases shift.
  
  Anchor implementation: `_push_indent_to_col` bumps
  `_indent` to match the target col in 4-space grid units
  (with an `extra` remainder for non-mult-of-4 anchors
  like chain-tail `.` cols). This lets inner emissions
  that read `_indent` (e.g. a binary_expression arg's
  `+`-continuation `p2_col`) compute the correct
  anchor-relative col rather than the outer-block-relative
  col.
- **`Emitter._arg_list_p4_fired` flag replaces the
  `_operand_emitted_shallow_line` heuristic in binary
  wrap's `paren_inner_wrap` check.** The pre-0.6
  `_operand_emitted_shallow_line` check detected "operand's
  emission has a line with leading whitespace <
  align_col" — which was a good proxy for "arg-list P4
  wrapped a leaf arg" under the OLD `block+4` anchor.
  Under the new `line-start-col + 4` anchor, arg-list P4
  emissions no longer produce shallow lines (they're at
  contained cols). The shallow-line signal misses,
  causing binary paren-aligned to commit ugly 5-line
  cascades where +4-greedy compact would have committed
  under OLD. Direct signal `_arg_list_p4_fired` is set
  to True inside the P4 candidates and checked via
  save-reset-check-restore in `emit_greedy` and
  `emit_paren_aligned` — a precise signal for "operand's
  emission cascaded through arg-list P4" (as opposed to
  operand's own binary/chain/ternary wrap). Preserves
  `arg_list_wrap/03`'s compact 2-line shape while enabling
  defect 3's fix. Locked by new fixtures
  `arg_list_wrap/12_defect_3_nested_paren_contained`
  (nested fits inline) and
  `arg_list_wrap/13_defect_3_nested_wrap_paren_aligned`
  (nested wraps at outer-paren + 4). Fixture
  `method_chain_wrap/17_same_method_greedy_item8_inner_wrap`
  expected shape updated (literal shifts from col 13 to
  col 15 per the new chain-tail anchor).
- **Multi-interface `implements` clause collapse on class
  headers.** `_emit_extends_implements_p2_p3` previously
  had only P2 (both clauses on one line) and P3 (each
  clause on its own line) tiers. When the P3 `implements`
  line itself still exceeded 80 chars (a class implementing
  3+ long-named interfaces), the formatter committed a
  single-line P3 output that violated LineLength. Adds a
  P4 tier (`_emit_super_interfaces_broken`) that keeps the
  first interface on the `implements` line and breaks
  subsequent interfaces onto their own lines paren-aligned
  under the first interface's column. Locked by
  `class_header_wrap/10_p4_multi_interface_implements`.
  Consumer trial surfaced this on
  `data-mart-replicator/DataMartReportsServices.java`
  (4 interfaces, 142-char P3 line dropped to a multi-line
  paren-aligned shape).
- **P1 assignment_expression Step 1 / Step 2 fit-check
  loosened to per-line widths.** Both Step 1 (inline) and
  Step 2 (break-at-`=`) previously required the RHS to
  emit on a single line — Step 2 would reject any RHS that
  itself wrapped internally (e.g. a cast + call whose
  arg-list wraps to multi-line), even when every RHS line
  fit under `effective_max`. Consequence: assignments
  committed inline (Step 3) with 88-char line-1 shapes like
  `this.proxyEnvironment = (Type) obj.method(` — no
  break-at-`=` fallback fired. Both steps now use
  `last_lines_max_width(saved[0]) <= effective_max`,
  admitting RHS internal wraps. Locked by
  `assignment_wrap/04_break_at_op_when_rhs_wraps_multi_line`.
  Consumer trial surfaced this on
  `data-mart-replicator/SzReplicator.java:994, 1193`.

### Verification

- 674 pytest passing (`tooling/scripts/tests/`).
- Consumer trial across 3 repos:
  - `senzing-commons-java` — 4 files reformatted with the
    intended P0/P1F/P3F/P4-SQL-DDL improvements;
    `mvn -Pcheckstyle validate` BUILD SUCCESS with 0
    violations.
  - `sz-sdk-java` — 32 files reformatted; the two remaining
    formatter warnings are legitimate unsplittable literals
    (advisory-not-bug).
  - `data-mart-replicator` (first-time adoption) — 234
    files reformatted; both defects surfaced during trial
    fixed above; remaining ~150 over-80 lines are
    unsplittable string literals in assertion messages or
    source-preserved trailing comments (author-side work,
    not formatter defects).
- Idempotency verified on all new fixtures via the
  standard pytest golden-file suite.

### Added

- **P1 — assignment_expression wrap.** Bare `LHS OP RHS`
  reassignments (as distinct from `Type LHS = RHS`
  declarations, which have wrapped at `=` since 0.5.0) now
  get their own wrap-priority cascade. When the inline
  form overflows, the formatter breaks before the operator
  and puts the RHS on a continuation line at
  `block + 4` — mirroring the existing
  `_emit_variable_declarator` behavior. Fills the gap
  identified during the 0.5.3 consumer adoption pass on
  `senzing-commons-java`: bare `args = new String[] {...};`
  overflows at deep indent no longer emit silently as
  81-char LineLength violations. Locked by three new
  fixtures under `tests/fixtures/assignment_wrap/`.
- **P0 — `emit_p4_single_arg` two-candidate cascade with
  paren-deference.** `_emit_argument_list`'s single-arg P4
  fallback splits into two candidates in
  `try_priorities`' order: block+4 first, paren-defer
  second. Block+4 wins when the arg fits at the canonical
  single-indent col (short identifier / short method call
  / anything that comfortably fits); paren-defer wins as
  the spec C1 emit-and-warn fallback when neither col
  fits, placing the arg at `paren_expr_col + 3` — one `+4`
  step past the innermost enclosing
  `parenthesized_expression`'s `(`. That means:
    - **Long literal that can't be split** (canary
      `condition_wrap/09`): both cols overflow →
      paren-defer wins → literal at "col of enclosing `(`
      + 4", semantically aligned under its group.
    - **Long identifier that overflows at every col**
      (Case 5): same — paren-defer wins for the same
      semantic-alignment reason. Checkstyle catches the
      overflow and prompts the developer to rename.
    - **Short arg that fits at block+4** (e.g.
      `.asList(timers)` nested in a binary chain):
      block+4 wins as the first fitting candidate,
      preserving pre-0.6 shape and not destabilizing outer
      wraps.
  New `Emitter._paren_expr_col` slot is set only by
  `_emit_parenthesized_expression` — never by item 10's
  extension for single-arg binary args — so the deference
  rule discriminates grouping/control-flow parens from
  method-call parens. Locked by `condition_wrap/09`
  (positive canary — literal at col 24) and the new
  `arg_list_wrap/09_single_arg_literal_paren_deference`
  fixture (positive — literal at col 18 under an
  enclosing `if (!(...))`).
- **P3 — Cross-statement smoothing** (motivating example) is
  achieved naturally by the P0 source-preserve fall-through
  and the emit_p4_single_arg two-candidate cascade added in
  Phase 2/3. The scope-doc motivating example — three
  sibling `result.add(arguments(...))` calls in
  `JsonUtilitiesTest.java:3057-3062` that in 0.5.3 got
  three different wrap shapes because source-preserve
  echoed pre-existing developer layouts — now converges to
  a consistent paren-aligned shape across all three because
  each individual statement's wrap engine independently
  picks the same canonical layout. No non-local
  cross-statement machinery required. Locked by
  `arg_list_wrap/11_sibling_calls_paren_align_naturally`.
  If future consumer trials surface cases where sibling
  statements STILL diverge post-Phase-2/3, the non-local
  cross-statement smoothing described in
  `.claude/060_SCOPE.md` P3 will need to be built — but no
  such case is known today.
- **P4 — SQL DDL detector for string-concat chains.**
  Adds a heuristic detector to `_emit_binary_expression`
  that identifies hand-authored SQL DDL as a `+` chain
  where (a) all operands are `string_literal`, (b) the
  chain has at least 2 operators, and (c) the LEFTMOST
  operand's first alphabetic token matches a recognized
  SQL keyword (`create`, `insert`, `update`, `delete`,
  `select`, `alter`, `drop`, `with`, `merge`, `truncate`).
  When the detector fires, the binary emitter picks
  `emit_p3` (one operator per line at block+4) BEFORE
  attempting the greedy-pack candidates. Preserves the
  hand-authored one-clause-per-line SQL layout that greedy
  packing would otherwise collapse into an unreadable
  jumble. The pre-0.6 escape hatch (`// CSOFF`/`// CSON`
  markers) remains available for cases the detector gets
  wrong. Restricting the keyword match to the LEFTMOST
  operand keeps common English prose from triggering — a
  string opening `"The report was..."` doesn't match even
  if a later operand happens to start with `"with"`. New
  fixtures: `binary_wrap/04_sql_ddl_create_table`
  (positive) and `binary_wrap/05_prose_string_not_ddl`
  (negative — prose greedy-packs as before).
- **P2 — Q-CHAIN-4 backoff extended to the standard P2
  candidate.** `_emit_method_chain_wrapped`'s `emit_p2`
  (dot-align-under-receiver-`.`) now rejects itself when
  any chain segment's args wrap mid-emit — matching the
  Q-CHAIN-4 backoff already implemented for P1F and P3F in
  Phases 4a/4b. Reuses the existing
  `_segment_emit_is_legitimately_multi_line` helper so
  intentionally-multi-row args (lambda bodies, text blocks,
  developer-authored source-preserved arg lists) don't
  trigger backoff. When P2 backs off, the chain falls
  through to `emit_p3` (block+4). Cleaner than the
  pre-0.6-Phase-4c "mixed alignment" shape (dot-align chain
  col + deep paren-align args col). Fixture updates driven
  by this rule:
    - `method_chain_wrap/11_chain_with_wrap_engine_rewrapped_args`
      previously locked the mixed shape; new expected is
      all-block+4.
    - `method_chain_wrap/19_p1f_factory_backs_off_when_args_wrap`
      previously stopped at P2F; new expected falls further
      through to P4F since P2F now also backs off. The
      fixture now demonstrates the full P1F → P2F → P4F
      cascade.
- **P2 — outer-parenthesized-expression chain cascade
  (P3F / P2C).** Adds a new candidate to
  `_emit_method_chain_wrapped` that fires when the whole
  chain is wrapped in an enclosing
  `parenthesized_expression` (checked via
  `Emitter._paren_expr_col`, added in the P0 phase). Chain-
  tail segments land at `paren_expr_col + 4` per
  Q-CHAIN-1's resolution (consistent with the
  enum/class-header wrap convention). Shape by receiver
  kind:
    - **Factory / instance** (head is identifier /
      field-access): `head.segments[0]` stays on line 1;
      `segments[1:]` each on their own continuation line
      at `paren_expr_col + 4`. Locked by
      `method_chain_wrap/20_p3f_factory_paren_indent` and
      `method_chain_wrap/21_p3f_instance_paren_indent`.
    - **Constructor** (head is
      `object_creation_expression`): head alone on line 1;
      ALL segments break to continuation lines. Locked by
      `method_chain_wrap/22_p2c_constructor_paren_indent`.
  Tried BEFORE the standard P2 (block+4-agnostic dot-align)
  because paren-indent is preferred inside a grouping paren
  per Q-CHAIN-5. Falls through to P2 if widths overflow OR
  Q-CHAIN-4 backoff triggers (a chain segment's args
  wrapped mid-emit).
- **P2 — factory-chain P1F "deep dot" candidate.** Adds a
  new candidate to `_emit_method_chain_wrapped`'s cascade
  that fires when the chain receiver is a PascalCase
  identifier (Q-CHAIN-3 factory heuristic) AND the chain
  has at least 3 segments. Emits head + `.factoryMethod(...)`
  + `.firstChain(...)` on line 1, aligns subsequent chains
  to the FIRST CHAIN's `.` column — one chain-alignment
  step DEEPER than the pre-0.6 P2F shape (which aligned
  everything to the factory's `.`). Tried BEFORE P2F in
  the cascade; committed only when both widths fit AND no
  chain method's args wrapped (Q-CHAIN-4 backoff — an
  in-args wrap in P1F falls through to P2F for cleaner
  mixed-alignment avoidance). New helper
  `_chain_receiver_is_factory` classifies the receiver by
  the leftmost identifier's case:
  PascalCase → factory (P1F applies);
  camelCase / SCREAMING_SNAKE_CASE / `new` / constructor →
  instance / constructor (P1F skipped, existing cascade
  applies). Locked by two new fixtures:
  `method_chain_wrap/18_p1f_factory_deep_dot` (positive)
  and `method_chain_wrap/19_p1f_factory_backs_off_when_args_wrap`
  (Q-CHAIN-4 backoff). Existing fixtures 14 and 16 updated
  to reflect the new P1F preference for factory chains.
- **P0 — source-preserve fall-through when developer's deep
  indent would overflow.** `_emit_argument_list`'s source-
  preserve path previously preserved developer-authored
  continuation columns verbatim whenever they were at or
  past the target col (`paren_align_col + 4`) — a rule
  meant to preserve idempotency for wrap-engine output.
  Under 0.6.0, when the preserved shape still exceeds 80
  chars, the source-preserve path declines and falls
  through to the wrap engine, so the wrap engine's
  paren-aligned candidate emits at the correct enclosing
  paren instead of locking a stale developer column. This
  is what makes `condition_wrap/09`'s 68-char literal move
  from developer's arbitrary col 28 to the paren-aligned
  col 24 (via the paren-deference rule above). Idempotency
  holds: wrap-engine output at column X re-enters this
  branch on the next pass with `source_first_cont_col = X`
  and emits the same shape.

## [0.5.3] - 2026-07-07

Adoption-template + formatter release. Closes the
"test-source formatter advisories are toothless" gap by
flipping `maven-checkstyle-plugin`'s
`includeTestSourceDirectory` to `true` in the shared
template, then extends the AST formatter to wrap
enum-header `implements` clauses (previously it only
wrapped `class` and `interface` headers, forcing adopters
to `// CSOFF` markers for long-typed enum declarations).

### Changed

- **`adoption/claude-md-templates/pom-checkstyle-profile.xml`:
  gate `src/test/java` with checkstyle.** Adds
  `<includeTestSourceDirectory>true</includeTestSourceDirectory>`
  to the shared checkstyle profile template. Before 0.5.3,
  the plugin's default (`false`) silently skipped test
  sources — the formatter's `LineLength` overflow
  advisories in `src/test/java` printed at format time but
  never failed a build, so consumers accumulated
  test-source overflows without a forcing function to
  clean them up. This release turns the gate on for all
  consumers on their next `/init-java` run.

### Added

- **Enum-header wrap.** `_emit_enum_declaration` in
  `format_java.py` now mirrors the class-header
  snapshot-and-wrap flow: after emitting `[modifiers] enum
  NAME`, speculatively emit the `implements` clause on the
  same line; if it overflows 80 chars, restore and delegate
  to the existing `_emit_class_header_wrapped` helper
  (which drops the clause to a `start_col + 4` continuation
  line via the P2/P3 cascade). Fills a formatter gap
  surfaced during the `senzing-commons-java` 0.5.3
  adoption: 4 long-typed enum declarations
  (`ExtendedTestOption`, `EnvTestOption`,
  `OtherTestOption`, `PrimaryEnvTestOption`) previously
  had no valid formatter output — every manual wrap was
  reflowed back to single line, forcing `// CSOFF`
  suppressions. Now the formatter wraps them
  automatically. Locked by three new fixtures:
  `tests/fixtures/class_header_wrap/07_enum_implements_wrap/`
  (top-level P2 shape),
  `tests/fixtures/class_header_wrap/08_nested_enum_implements_wrap/`
  (nested enum, `start_col + 4` semantics), and
  `tests/fixtures/class_header_wrap/09_enum_p3_terminal_single_interface/`
  (single super-long interface committing at P3-terminal
  per spec C1 "emit + warn").

### Adopter action required

Consumers upgrading their submodule pin from 0.5.2 to
0.5.3 must:

1. Re-run `/init-java` to pick up the updated template.
   The adoption playbook step 3 wiring will surface the
   one-line delta and prompt to apply it to the local
   `pom.xml`.
2. Run `mvn -Pcheckstyle validate` and resolve any
   pre-existing test-source overflows: either manual
   literal splits (semantically no-op re-splits) or
   project-local `<suppress checks="LineLength"
   files="..."/>` entries in
   `checkstyle-suppressions-local.xml` for sites where a
   split would harm readability more than the overflow.

### Verification

- 660 formatter tests pass (was 657 at 0.5.2); +3 fixtures:
  `class_header_wrap/07_enum_implements_wrap` (top-level
  `PrimaryEnvTestOption`-shaped enum header, P2 shape),
  `class_header_wrap/08_nested_enum_implements_wrap`
  (nested enum inside a class, locking the `start_col + 4`
  continuation column semantics), and
  `class_header_wrap/09_enum_p3_terminal_single_interface`
  (single super-long interface committing at P3-terminal
  per spec C1 "emit + warn").
- Adoption template diff reviewed against maven-checkstyle-
  plugin 3.6.0 parameter docs — `includeTestSourceDirectory`
  is a plugin `<configuration>` parameter, not a system
  property; setting it in `<configuration>` is the
  documented mechanism.
- Round-trip tested against `senzing-commons-java`
  (companion PR #228, consumer-side 0.4.1 → 0.5.3
  adoption): the flag flips 23 previously-silent
  formatter advisories into hard checkstyle violations
  and drives the manual-cleanup follow-up on the
  consumer. The enum-wrap addition eliminates the need
  for `// CSOFF` markers on the 4 long-typed
  `CommandLineOption<T, U>`-implementing enum
  declarations under `src/test/java/com/senzing/cmdline/`.

## [0.5.2] - 2026-07-01

Bug-fix release adding a defensive guard to
`_emit_argument_list`'s source-preserve path so a mechanical
shift-up cannot produce an overflow shape the wrap engine
would have avoided. Narrow, no spec change; findings A–E from
the 0.5.2 investigation remain deferred to 0.6.

### Fixed

- **Source-preserve shift-up produced overflow lines.** When
  `_emit_argument_list`'s source-preserve path shifted a
  shallow-indent continuation up to its target column
  (`paren_align_col + 4` or `block + 4`), the shifted
  continuation could exceed 80 chars even though the source
  fit at its authored (shallower) column. The formatter
  ran the shift unconditionally and only reported the
  overflow via the post-emit advisory — leaving a
  preventable LineLength violation on disk. Fix: compute
  the max shifted line width before committing to
  source-preserve; when the shift would overflow, fall
  through to the wrap engine cascade (`emit_p1` →
  `emit_p2_greedy` → `emit_p4_multi_arg`), which commits
  the first candidate that fits. In practice `emit_p2_greedy`
  (paren-aligned, packed) wins most multi-arg cases; P4
  (one arg per line) only lands when neither prior
  candidate fits.
  The guard is narrow: it only inspects lines produced by
  the mechanical shift-up (source column shallower than
  target). When the source's authored column is at or
  deeper than the target column, the earlier "only shift
  UP" gate short-circuits to preserve the developer's
  chosen indent verbatim — the guard is never reached, and
  overflows in that path still ride the advisory (they
  need manual literal splits, unchanged from 0.5.1).

### Verification

- 657 formatter tests pass (was 656 at 0.5.1; +1 fixture
  `arg_list_wrap/08_shift_up_overflow_declines_source_preserve`
  locks the wrap-engine shape produced when the guard
  declines source-preserve). `condition_wrap/09` (deep-
  indent paren-align with long literal, developer-chosen
  deeper column) remains preserved verbatim as expected.

## [0.5.1] - 2026-06-24

Bug-fix release addressing four formatter defects (five
code-level fixes) surfaced during the 0.5.0 adoption pass
across `senzing-commons-java` and `sz-sdk-java`. All changes
are formatter output fixes; no spec changes.

### Fixed

- **Mid-statement line comments dropped in
  `variable_declarator`.** Comments positioned between `=`
  and the value RHS (e.g. javadoc `// @highlight region="x"`
  snippet markers on text-block assignments) were silently
  dropped by the AST walk, breaking `mvn javadoc:javadoc`
  under JDK 21 when the unpaired `@end region` closers
  failed validation. Fix: source-preserve the `= ...` region
  verbatim when mid-statement comments are detected,
  matching the 0.5.0 treatment of comments inside arg lists.
- **Trailing whitespace bypassed `Emitter.newline()`'s
  `rstrip` in source-preserve paths.** `write_raw_lines`
  intentionally preserves trailing whitespace for text-block
  content but had no opt-in for source-preserved CODE.
  Fix: added `strip_trailing_ws` parameter; all
  source-preserve-code call sites (conditions, arg lists,
  formal parameters, non-javadoc block comments) pass `True`.
- **Array initializer missing space before `{`.** Produced
  `new Type[]{ X }` instead of canonical `new Type[] { X }`
  for some inputs; idempotent on both forms, so the file
  accumulated mixed styles. Fix: emit a single space before
  `array_initializer` children of
  `array_creation_expression`.
- **Item-8 invariant not enforced for multi-arg arg lists.**
  Calls of the shape
  `assertEquals(arg1, longCallThatWraps(...), msg)` jammed
  the third argument onto the wrapped second argument's
  tail line. The 0.5.0 spec described this as
  "width-gate handles it implicitly" but the gate misses
  cases where the line happens to fit under 80 chars by
  coincidence. Fix: explicit
  "previous-arg-multi-row → break before next arg" check in
  both `emit_p1` and `emit_p2_greedy`.
- **Binary positional arg ignored arg-start column.** When
  a multi-arg call's positional argument was a
  `binary_expression`, the binary's continuation operators
  landed at `block + 4` instead of paren-aligning under the
  argument's first operand column. Fix: set
  `paren_align_col` to the arg's start column for the
  duration of a binary-typed positional arg's emit. Narrow
  to direct `binary_expression` (no paren unwrap) to avoid
  the idempotency drift that originally narrowed 0.5.0
  item 10 to single-arg.

### Verification

- 656 formatter tests pass (was 645 at 0.5.0; +10 new
  fixtures across `comment_preservation/`, `arg_list_wrap/`,
  and `array_initializer/`). The first 6 lock the headline
  fixes; the remaining 4 cover edge cases surfaced during the
  PR review pass (block-comment between `=` and value,
  array initializer without `new`, last-arg-multi-row in arg
  lists, idempotency lock for the P4 paren-aligned shape).
- `senzing-commons-java` reformat: 2151 / 2151 tests pass,
  `mvn -Pcheckstyle validate` BUILD SUCCESS, idempotent on
  2nd pass, zero trailing whitespace in source, array
  initializers normalized.
- The sz-sdk-java demo files containing javadoc `@snippet`
  markers no longer lose their `// @highlight` openers;
  `mvn javadoc:javadoc` under JDK 21 succeeds.

## [0.5.0] - 2026-06-23

Expands the formatter from the
"control-flow + grouping paren" wrap surface introduced in
0.4.3 to cover **every place a governing `(` exists**:
control-flow constructs (item 1), for-statement clause
parens (item 5), and single-arg call/constructor parens
whose argument is a binary expression (item 10). It also
adds the **greedy** wrap shape for non-boolean binary
chains (item 3), label/value pair-aligned wrap for the
canonical `toString()` pattern (item 2a), same-method
greedy chain wrap (item 2b), the **ternary paren-aligned
T1/T2/T3 cascade** (items 7 + 9), the
**multi-row-inner-forces-outer-break** invariant (item 8),
**context-aware source-preservation with no-fallback policy**
(item 4), and **comprehensive wrap-engine overflow
advisories** (item 11) so every site the formatter cannot
fit produces a `FormatterWarning` pointing the developer at
the source location to split.

### Changed

- **Spec C6 paren-alignment extended to control-flow required
  parens** (`_emit_parenthesized_expression`, item 1).
  0.4.3 restricted paren-aligned operator
  continuation to grouping parens (developer-authored `(...)`
  around an expression). 0.5.0 extends the rule to the
  syntactically-required parens of control-flow constructs:
  `if (cond)`, `while (cond)`, `for (...)`, `catch (...)`,
  `synchronized (...)`, `switch (...)`. Operator continuations
  inside a multi-line control-flow condition now align under
  the column immediately after the `(` instead of using the
  cumulative `+4` indent. The yields-to-source-preserve
  inversion check (added in 0.4.3) continues to apply — when an
  inner source-preserved arg list has continuation columns
  below the proposed paren-align column, paren-alignment is
  declined and the wrap engine falls back to the cumulative
  `+4` continuation. Implementation: removed
  `_PAREN_NOT_GROUPING_PARENT_TYPES` (the denylist that
  excluded control-flow parents) and simplified the
  `apply_paren_align` computation to always engage modulo the
  inversion check. Three existing fixtures had their expected
  output regenerated to reflect the new continuation columns;
  one new fixture
  (`condition_wrap/10_if_condition_paren_aligned`) locks the
  4-operand `if (a && b && c && d)` paren-align case.

- **Label/value-aware pair-aligned binary `+` wrap** (item 2a).
  When a `+` chain alternates string ↔ non-string with each
  subsequent string literal carrying a delimiter prefix from
  `{" ", ",", ";", "]", ")", "}", "|", ":"}` (the canonical
  Senzing `toString()` "label=[ " + value + " ], " pattern),
  the wrap engine breaks before each subsequent label so every
  continuation line carries one `label + value` pair.
  Continuation column is `paren_align_col` when set, else the
  +4 indent. The first label literal is the line anchor and
  doesn't need a delim prefix — that's the "lenient gate" the
  pattern uses to match the canonical Senzing diagnostic
  string. Tried BEFORE the paren-aligned / greedy candidates
  when the alternation matches. New fixture:
  `binary_wrap/02_pair_aligned_label_value`. The gate's no-
  match path falls through to greedy as before; new fixture
  `binary_wrap/03_pair_aligned_no_match_falls_to_greedy`
  locks the negative case.

- **Same-method method-chain greedy wrap** (item 2b). When
  every segment in a chain shares the same method name (the
  classic `.append(...).append(...).append(...)` pattern),
  the chain wraps with greedy packing instead of P2's strict
  dot-alignment one-per-segment. Each segment packs onto the
  current line until adding the next would overflow, then
  breaks at the dot-aligned column. Keeps multi-`.append(...)`
  builder calls horizontally dense while preserving the chain
  invariant that breaks at segment boundaries (not mid-segment).
  Gated on `_chain_segments_share_method_name` so mixed-method
  chains keep the existing one-per-line wrap. New fixtures:
  `method_chain_wrap/15_same_method_greedy_packs` and
  `method_chain_wrap/16_mixed_methods_keep_one_per_line`.

- **Greedy binary expression wrap for non-boolean operators**
  (item 3). Replaces the prior P2 (break-before-leftmost-only)
  plus paren-aligned one-per-line for `+`, `-`, `*`, `/`, `==`,
  `!=`, etc. The greedy candidate packs as many `OP operand`
  pairs per continuation line as fit within
  `_MAX_LINE - tail_reserve`; breaks at the operator boundary
  when adding the next pair would overflow. Boolean chains
  (`&&` / `||`) keep `emit_paren_aligned` (one-per-line) for
  vertical readability — the spec preference for boolean
  conjunction. Greedy naturally degenerates to one-per-line
  for long operands, so it's a strict improvement over the
  earlier paren-aligned candidate for the non-boolean case.
  New fixture: `binary_wrap/01_greedy_paren_aligned`. Existing
  `condition_wrap/04_expression_statement_tail_semicolon`
  regenerated to reflect the new greedy shape.

- **Context-aware source-preservation with no-fallback
  policy** (item 4). The source-preserve path
  (`_emit_argument_list`) no longer falls back to verbatim
  preservation when its remapped column would overflow.
  Instead it commits at the canonical column rule (governing
  paren → `paren_align_col + 4`; else `block + 4`), fires a
  `FormatterWarning` advisory, and lets checkstyle's
  LineLength surface the overflow — breaking the propagation
  cycle where source-preserved verbatim layouts silently
  re-appeared each format pass. The arg-list semantic opt-out
  expands to lambda / binary / method-invocation: when any arg
  is a multi-row construct of these types, source-preserve
  declines and the wrap engine re-emits the arg via its own
  cascade. The "only shift
  up, never down" idempotency rule preserves developer-chosen
  deeper continuation columns. New advisory message points
  the developer at the literal/expression to split.

- **For-statement clause paren-alignment** (item 5).
  `_emit_for_statement` now re-anchors each clause
  (initializer, condition, update) to `paren_align_col` when
  the header wraps multi-line, instead of source-preserving
  the clauses at their original (possibly stale, possibly
  hand-tuned) columns. Fixes a pre-existing bug where a
  for-loop at deep block indent kept its clauses at the
  source columns even after the surrounding context shifted.
  New helper `emit_header_paren_aligned()` unifies the
  single-row-overflow-fallback and multi-row-source-input
  paths. New fixture:
  `condition_wrap/11_for_loop_clauses_paren_aligned_at_deep_block`.

- **Ternary T1 newline-detection gate** (item 7). The
  `_emit_ternary_expression` T1 candidate (single-line
  ternary) now rejects when ANY nested emit introduced
  newlines — even if the resulting line widths all fit.
  Prevents the "looks single-line in total chars but
  actually wrapped internally" foot-gun where a ternary's
  consequence or alternative contains a multi-line construct
  that satisfies the width check but breaks the "single line"
  semantic the T1 shape promises.

- **Multi-row-inner-forces-outer-break invariant** (item 8).
  After each operand / clause emit in a wrap cascade, if the
  operand's OWN render introduced newlines (a nested
  construct that wrapped multi-line), the next OP/separator
  MUST break to a new line. Same anti-stranding principle as
  0.4.3's Bug 1 fix for method chains, applied generally to
  binary expressions (greedy + pair-aligned + paren-aligned),
  ternary expressions (condition → `?`, `?` → `:`), and
  argument lists (between adjacent args). Prevents the
  operator from visually merging with the wrapped operand's
  tail at the same column.

- **Ternary `paren_align_col` inheritance** (item 9). The
  `emit_paren_t2` / `emit_paren_t3` ternary candidates no
  longer clear `paren_align_col` while emitting the
  consequence / alternative branches. Inner binary chains
  inside ternary branches see the outer ternary's
  paren-aligned context and align their operator
  continuations under the same column the ternary's `?` / `:`
  use. New fixture:
  `ternary_wrap/07_paren_aligned_inherits_to_inner_binary`.

- **Spec C6 paren-align extended to single-arg binary call
  parens** (item 10). `_emit_argument_list` sets
  `paren_align_col` to the column immediately after a
  call/constructor `(` when the single arg is itself a
  `binary_expression`. The inner binary's cascade then sees
  the call's `(` as a governing paren and emits operator
  continuations paren-aligned under that column — covering
  the canonical `super("..." + foo() + "...")` /
  `throw new Exception("..." + arg)` patterns. Scope is
  deliberately narrow (binary args only): lambda, method-
  chain, and object-creation single args don't fire item 10
  because their interaction with `try_priorities` speculative
  emits breaks idempotency. A complementary universal rule
  rejects the binary paren-aligned candidate when any operand
  emits a continuation line shallower than the chain's
  `align_col` — prevents the visual-escape where an inner
  arg-list wrap pulls left past the chain's anchor. New
  fixtures: `arg_list_wrap/02_single_arg_binary_paren_aligned`
  (positive) and
  `arg_list_wrap/03_single_arg_binary_inner_wrap_falls_to_indent`
  (rejection).

### Added

- **Comprehensive wrap-engine overflow advisories** (item 11).
  The `FormatterWarning` advisory channel — previously fired
  only for source-preserve overflows — now also fires when
  the binary, ternary, method-chain, or argument-list wrap
  cascade commits a layout (spec C1 emit + warn) whose
  on-disk widths exceed `_MAX_LINE`. New shared helper
  `_fire_wrap_overflow_advisory` called at each cascade's
  terminal commit point. Per-line on-disk width is computed
  (not the uniform `max_width + tail_reserve`) so the
  advisory matches what checkstyle's LineLength actually
  sees. Speculative emits that rolled back via
  `snapshot()` / `restore()` don't fire — their warnings
  appended would be truncated. Dedupe by source range: when
  a wrap engine that contains another wrap engine which
  already fired (e.g. argument list containing a binary that
  exhausted its own cascade), the outer engine suppresses
  its own advisory — the inner one is more specific
  (smaller source span) and more actionable.

### Verification

- 644 formatter tests pass (was 626 at 0.4.3); +18 fixtures
  and unit tests across `binary_wrap`, `arg_list_wrap`,
  `ternary_wrap`, `method_chain_wrap`, and `condition_wrap`.
- `senzing-commons-java/src/main/java/` consumer trial:
  34 files reformat, `mvn -Pcheckstyle validate` BUILD
  SUCCESS, idempotent on 2nd pass, 0 LineLength violations
  after 18 manual literal splits (the no-fallback policy's
  expected adoption burden — each long literal in the
  reformatted output that couldn't fit was split at a
  word-boundary midpoint, with a couple of cases benefitting
  from extracting a long expression into a local variable so
  the label/value pair could fit on one line).
- Formatter test suite: 2151 consumer JUnit tests pass after
  reformat — no semantic regressions from the layout
  changes.

## [0.4.3] - 2026-06-18

Four formatter bugs caught by a code-review pass over the
0.4.2 reformat in `senzing-commons-java`. One is a regression
introduced by 0.4.2 itself (Bug 1); the other three are
pre-existing bugs that 0.4.2's wrap-engine fixes made more
visible (Bug 2), more frequently encountered (Bug 3), or more
visually conspicuous in the reformatted output (Bug 4). All
four are covered by new regression fixtures and the existing
fixture set continues to pass.

### Fixed

- **Method-chain P1 over-rejects when an inner construct is
  legitimately multi-line** (`_emit_method_chain_wrapped`,
  Bug 1, **regression from 0.4.2**). The Bug 1 fix in 0.4.2
  added per-segment newline detection so chain P1 would
  reject when an inner argument-list wrap broke the chain
  mid-call. That gate was too coarse: it also rejected when
  the segment's args were multi-row because the source was
  authored that way (the arg-list emitter takes the
  source-preservation path) or because the args contain a
  lambda whose body block is intrinsically multi-line. In
  both cases the chain still ends cleanly at the closing
  `)` and subsequent segments attach without breaking
  integrity. Fix: discriminate via `_node_spans_multiple_rows`
  on the segment's `arguments` node (and on any nested
  `lambda_expression` body block); newlines from those
  sources don't mark the chain as broken. Newlines from
  the actual wrap engine still do — the original Bug 1 case
  (long single-source-row chain that wrap-engine breaks via
  arg-list P4) continues to fall through to chain P2 as
  before.

- **Multi-line `if` condition does not trigger Allman brace
  placement** (`_emit_if_statement`, Bug 2, **pre-existing**).
  When the wrap engine breaks an `if`'s condition across
  multiple rendered lines (whether or not the source was
  already multi-row), the opening `{` should go Allman per
  the spec's "Brace Placement / Multi-Line Conditions" rule.
  `_emit_while_statement` had this behavior since 0.4.0;
  `_emit_if_statement` did not. The bug was masked in 0.4.1
  and earlier because the wrap engine produced fewer
  multi-line conditions; 0.4.2's precedence-aware spine
  walk increased the surface area where `&&` / `||`
  continuations land on their own lines, exposing the
  missing Allman switch. Fix: snapshot before condition
  emit, switch to Allman if `emitter.line_count` advances
  during the emit. Note: the if-emitter does NOT also adopt
  `_emit_while_statement`'s source-preserve fast path (which
  emits a developer-authored multi-row condition verbatim
  via `write_raw_lines`) — the if-emitter continues to
  re-render through `_emit_node`, matching its 0.4.1 and
  earlier behavior. Reconciling the two is left as a future
  spec/implementation decision.

- **Paren-aligned operator continuation per spec C6**
  (`_emit_parenthesized_expression` + `_emit_binary_expression`,
  Bug 3, **pre-existing**). When an expression is wrapped in
  _grouping_ parens (developer-authored `(...)` to
  disambiguate precedence), the spec calls for operator
  continuations to align under the column immediately after
  the opening `(`, not the standard cumulative `+4` indent.
  Without this, nested grouping parens produce a "staircase"
  shape where each level adds another `+4` of indent. Fix:
  add a `_paren_align_col` field to `Emitter` that
  `_emit_parenthesized_expression` sets to the column right
  after `(` for grouping parens only (control-flow required
  parens — `if (cond)`, `while (cond)`, `for (...)`,
  `catch (...)`, etc. — are explicitly excluded via the
  `_PAREN_NOT_GROUPING_PARENT_TYPES` set, since their
  continuations follow the existing `+4`-indent rule).
  `_emit_binary_expression` adds a new wrap candidate
  (`emit_paren_aligned`) tried BEFORE the standard P2: if
  paren-alignment fits, commit; otherwise fall through to
  P2 (`+4` single-line continuation) and P3 (`+4` one per
  line). `_emit_ternary_expression` gets the same treatment
  with TWO paren-aligned candidates tried before the
  standard T2/T3: `emit_paren_t2` (break before `?` only,
  with `? consequence : alternative` continuation aligned
  under the outer `(`) followed by `emit_paren_t3` (break
  before both `?` and `:`). Without the paren-T2 candidate,
  a ternary nested in grouping parens whose value branches
  fit together on a continuation line at the paren-aligned
  column was falling through to the standard `+4`-indent T2
  — losing the alignment spec C6 was supposed to produce.

- **Argument list preserves gratuitous multi-row source
  layout when single-line would fit**
  (`_arg_list_takes_source_preserve_path`, Bug 4,
  **pre-existing**). When the source arg list spans multiple
  rows AND its first source line fits at the current
  emission column, `_emit_argument_list` took the
  source-preserve path (`write_raw_lines`) and echoed the
  multi-row layout back verbatim. That logic is right when
  the author's break-points carry meaning (long log messages,
  semantically-grouped args), but produced gratuitous
  `Modifier.isStatic(modifiers)`-style wraps when a prior
  format pass had split a single-arg call across two lines:
  the source's first line is just `(`, trivially fits any
  column, so source-preserve fires even though
  `Modifier.isStatic(modifiers)` (27 chars) would comfortably
  collapse to single-line at the new column.
  Fix: before the `first_line_fits` gate, estimate whether
  the full args would fit single-line at the current column.
  The estimator (`_arg_list_single_line_estimate`) walks the
  arg-list AST, marks `string_literal` / `character_literal`
  / `line_comment` / `block_comment` regions as verbatim,
  collapses whitespace and normalizes comma-spacing
  (`,b` → `, b`) outside those regions, and returns the
  result. The AST walk is what prevents the foot-gun where
  a comma without a following space inside a string literal
  (`foo("name=A,value=B")`) is mistakenly comma-normalized
  and over-estimates the width by 1 per such comma — the
  string-literal contents have to be preserved exactly as
  the emitter would emit them. If the estimate fits at the
  current column, decline source-preservation so the wrap
  engine's P1 candidate produces the canonical single-line
  form.
  Skipped when any arg itself spans multiple rows (a text
  block, a lambda body, a nested wrapping call) — single-
  line is impossible in that case, so source-preservation
  remains the right path. Reordered the function so the
  unconditional preservation triggers (comments, CSOFF)
  fire first and the width-based opt-out applies only to
  the bare width-driven preservation path.

### Changed

- **`_PAREN_NOT_GROUPING_PARENT_TYPES` membership cleanup**
  (`format_java.py`). Removed `catch_formal_parameter` — a
  dead entry that could never match: the node represents the
  `TYPE NAME` inside catch parens and never owns a
  `parenthesized_expression` child (catch's required parens
  are owned by `catch_clause`, which remains in the set).
  The set is now exactly the tree-sitter-java node types
  whose grammar specifies a required-parens
  `parenthesized_expression` child. Note for future
  maintainers: tree-sitter-java does NOT have a separate
  `switch_statement` node — both `switch (x) { case ... }`
  and the JEP-361 `int y = switch (x) { ... }` parse as
  `switch_expression`. The set's `switch_expression` entry
  therefore covers both forms (verified via
  `Language.id_for_node_kind("switch_statement", True)`
  returning `None`).

- **Paren-alignment yields to source-preservation on
  inversion** (`_emit_parenthesized_expression`). Spec C6
  paren-aligned operator continuation (introduced as Bug 3
  in this release) and the arg-list source-preserve path
  could conflict when nested: an outer `(EXPR)` whose
  `EXPR` contains a deeply-nested arg list that
  source-preserves with continuation lines at a column LESS
  than the outer's paren-align column would render visually
  inverted — the outer operator chain (paren-aligned at
  `emitter.column`) appearing MORE indented than the inner
  source-preserved bytes. Fix: before setting
  `paren_align_col`, walk the inner expression tree for
  `argument_list` nodes that `_arg_list_takes_source_preserve_path`
  confirms WILL source-preserve at the proposed column. If
  any such arg list has a continuation line below the
  proposed column, decline paren-alignment for this level
  and fall back to the cumulative `+4` continuation (the
  pre-Bug-3 behavior). Result: paren-alignment fires
  wherever it's safe; source-preservation wins where it
  would otherwise be visually clobbered. The AST-based
  detection (rather than a pure source-text scan) is what
  avoids over-triggering on continuation columns that
  belong to arg lists Bug 4 will collapse — those don't
  actually source-preserve, so their source columns don't
  matter to the inversion check.

### Added

- **Formatter advisory channel** (`FormatterWarning` dataclass +
  `Emitter.warnings` list + `format_source(source, warnings_out=...)`
  parameter). The formatter now collects non-blocking advisories
  during emission and exposes them via an optional `warnings_out`
  list. The CLIs (`format_file.py` and `format_java.py --format`)
  print each advisory to stderr in `file:line:column: WARNING: ...`
  format consistent with editor / `grep` output.
  - Currently emits one advisory shape: "source-preserved arg
    list has continuation at column N below the surrounding
    indent (M); consider splitting the contained literal or
    expression into smaller chunks so the wrap engine can
    re-indent consistently." Fires when `_emit_argument_list`
    takes the source-preserve path AND the source has a
    continuation line landing at a column less than
    `emitter.indent_level * 4`. The classic trigger is a long
    `throw new IOException("…long error message…" + variable)`
    where the developer manually placed the string at a low
    column to fit 80 chars; the string literal can't be
    automatically split (Java syntax doesn't allow a literal
    to span lines, and converting to a text block changes
    semantics), so the developer is the only party who can
    resolve the visual quirk by splitting the literal into
    smaller concatenated chunks.
  - Advisories are filtered to be unique by `(line, column)`
    so speculative wrap-engine re-emission doesn't produce
    duplicates.
  - `warnings_out=None` (the default) silently discards the
    advisory list, preserving the original `format_source`
    API for callers that don't care.

### Tests

Thirteen new golden fixtures, each runs through the harness's
automatic idempotency check, plus 22 new unit tests (18 for the
pure helpers `_estimate_normalize` and
`_arg_list_single_line_estimate`, plus 4 for the new
`FormatterWarning` advisory channel):

- `method_chain_wrap/09_chain_collapses_when_call_fits_single_line`
  — locks the combined Bug 1 + Bug 4 behavior: input
  `cls.getResource(\n    cls.getSimpleName() + ".class").toString()`
  has source-preserved multi-row args inside the chain, the
  whole chain fits single-line at 80 chars, and the
  formatter collapses to a single line. The chain
  discriminator's `_arg_list_takes_source_preserve_path`
  agreement with the arg-list emitter is what makes the
  collapse safe — both predict "single-line" together so
  the chain doesn't get stranded mid-decision.
- `method_chain_wrap/10_chain_with_multiline_lambda_body_inline`
  — chain-P1 over a segment whose args contain a multi-row
  lambda body (`forEach(flag -> { ... })`). Locks the
  intrinsically-multi-line variant of the discriminator
  (`any_multiline_arg=True` path) — chain stays inline,
  doesn't get pulled to dot-aligned P2.
- `method_chain_wrap/11_chain_with_wrap_engine_rewrapped_args`
  — locks the bug-1-shape regression-guard for the case the
  initial Bug 1 fix attempt missed: when the source is
  multi-row but its first line doesn't fit at the chain's
  emission column, the arg-list emitter falls through to the
  wrap engine (P4), which produces multi-line output that
  strands subsequent chain segments. The discriminator must
  reject in that case. Added in follow-up after the first
  code-review pass flagged the gap.
- `method_chain_wrap/12_arg_list_collapses_when_single_line_fits`
  — locks Bug 4 fix in a non-chain context: a single-arg
  call `Modifier.isStatic(\n    modifiers)` that fits
  single-line at the current emission column collapses
  rather than echoing the source's multi-row layout.
  The same fixture also covers a multi-line `if` condition
  whose inner `Modifier.isStatic(modifiers)` calls each
  collapse while the outer `&&`-chained condition still
  wraps (proving the gate is per-arg-list, not per-
  expression).
- `method_chain_wrap/13_arg_list_collapses_with_string_literal_comma`
  — locks the AST-aware width estimator
  (`_arg_list_single_line_estimate`): a call whose args
  include string literals with commas that have no following space
  (`log("err=A,err=B", ..., "second,string", ...)`) lands
  exactly at column 80. The naïve regex-only estimator
  would over-estimate by 1 per such comma and incorrectly
  retain source-preservation; the AST walk skips
  string-literal contents and the gate correctly declines
  preservation so the call collapses single-line.
- `method_chain_wrap/14_long_chain_falls_to_dot_aligned_over_mid_arg_break`
  — locks the chain-P1 segment cap at 2: a 4-segment chain
  whose middle segment has source-preserved multi-row args
  (`Builder.builder().setReader(r).setFormat(\n  fmt).get()`)
  now wraps at the dots (chain P2, dot-aligned, one segment
  per line with collapsed args), NOT chain P1 with the
  trailing `.get()` piled on the continuation line of the
  closing `)`. Matches the design preference "break on
  method chaining (greedily) before breaking on parameter
  names for a method in the chain".
- `allman_braces/20_multiline_if_condition_uses_allman_brace`
  — locks Bug 2 fix: a single-source-row condition that the
  wrap engine breaks now triggers Allman brace.
- `allman_braces/21_multiline_if_condition_nested_uses_allman`
  — same shape for an `else if` chain with both branches'
  conditions wrapping.
- `condition_wrap/08_paren_aligned_operator_continuation`
  — locks Bug 3 fix with nested grouping parens
  (`(a || (b && (!c)))`). Both `||` and `&&` continuations
  paren-align under their respective `(`.
- `condition_wrap/09_paren_align_yields_to_source_preserve_inversion`
  — locks the paren-align-yields-to-source-preserve behavior:
  a deeply-nested boolean assignment containing a chained
  `Boolean.FALSE.equals(...)` call whose outer `(` lands at
  column 32 has a source-preserved arg list whose continuation
  lines sit at columns 28 and 34. The AST-walk inversion check
  detects the col-28 continuation < proposed 32 and declines
  paren-alignment for the outer grouping; `||` and `&&` fall
  back to the standard `+4` cumulative continuation so the
  inner source-preserved bytes nest correctly inside the outer
  operator chain rather than being visually outdented.
  Input == expected is intentional here — like
  fixture 01 above, the regression lock is on
  "formatter does NOT change this layout", not on a
  reformat-shape transformation.
- `ternary_wrap/05_paren_aligned_ternary`
  — locks the spec C6 paren-alignment generalization to
  ternaries: a `return (cond ? ... : ...)` whose value
  branches are too long for single-line aligns `?` and `:`
  under the column immediately after the outer `(`, not the
  standard `+4` continuation indent.
- `ternary_wrap/06_paren_aligned_ternary_t2`
  — locks the paren-aligned T2 candidate (break before `?`
  only, with `? consequence : alternative` continuation
  aligned under the outer `(`). Used when T1 and the
  standard +4 T2/T3 overflow but a paren-aligned T2 fits;
  without this candidate the engine would fall to standard
  `cont_indent` T2 and lose the paren alignment.
- `explicit_constructor_invocation/01_this_args_reserve_trailing_semicolon`
  — locks the tail_reserve fix surfaced by Bug 4. Input has
  source-preserved multi-row args whose single-line estimate
  would render the call at exactly column 80; with the
  trailing-`;` reserve in place, the wrap engine's P1
  candidate correctly rejects (would push to 81) and the
  output falls to paren-aligned one-per-line. Locks the
  parallel-with-`throw`/`return`/`expression_statement`
  convention. Input == expected is intentional here — the
  fixture is a regression lock for "formatter does NOT
  collapse this multi-row call when the `;` would push the
  line to 81", not a reformat-shape test.

### Verification

- 632 standards-repo tests pass (was 597; +13 new fixtures,
  +18 helper unit tests, +4 advisory-channel unit tests).
  One existing fixture
  (`condition_wrap/06_binary_precedence_keeps_atomic`) also
  had its `expected.java` updated to reflect the Bug 2
  Allman-brace correction — its multi-line condition now
  triggers the same Allman placement covered by the new
  `allman_braces/20_multiline_if_condition_uses_allman_brace`
  fixture.
- `senzing-commons-java`: formatter produces a one-time
  format diff (28 files modified — chain inline-recovery
  from Bug 1 fix + Allman brace from Bug 2 fix + paren-align
  from Bug 3 fix + arg-list single-line collapse from Bug 4
  fix); the second pass is idempotent and
  `mvn -Pcheckstyle validate` remains BUILD SUCCESS.

## [0.4.2] - 2026-06-17

Five formatter bugs surfaced by adopting 0.4.1 in
`sz-sdk-java-auto`, plus a SessionStart-hook robustness fix.
Adopters with consumers that already passed `mvn -Pcheckstyle
validate` under 0.4.1 should expect a one-time format diff
under 0.4.2 (the new wrap shapes correct previously-malformed
output for the affected patterns); the second formatter run
is idempotent at the new fixed point.

### Fixed

- **Method chains with arguments now chain-wrap instead of
  argument-list-wrapping** (`_emit_method_chain_wrapped`).
  When a fluent chain like
  `obj.alpha().beta(arg).gamma(arg).build()` overflowed, the
  formatter would try chain-P1 (single line), discover that
  one segment's argument list internally wrapped to keep
  widths under 80, and commit the result — leaving `.` and
  `)` mid-line and stranding args. Fix: chain-P1 tracks per-
  segment newlines and rejects when any segment's emit
  introduced one; the engine then falls through to chain-P2
  (dot-aligned per segment). The same pattern with no-arg
  chains was unaffected and continues to wrap correctly.
- **Binary-expression wrap now respects operator precedence**
  (`_emit_binary_expression`). Previously the left-spine walk
  descended through every `binary_expression` left child
  regardless of operator, so a chain like
  `a == null || b || c` was flattened to a single 4-element
  chain and broken before the leftmost `==` (stranding
  `== null`). Fix: the walk only descends through children
  whose operator shares the root's **precedence group**, so
  higher-precedence sub-expressions (`a == b` under `||`,
  `c * d` under `+`, etc.) stay atomic and the wrap engine
  breaks only at the lowest-precedence operator boundaries.
  A new module-level `_BINARY_OP_PRECEDENCE` table encodes
  the Java operator precedence used for the comparison.
- **Multi-operator expressions with inner parenthesized
  sub-expressions now break at the top-level operator**
  rather than inside the inner parens. Same root cause as
  the chain-args fix: the binary P1 attempt accepted nested
  newlines from a parenthesized sub-expression that wrapped
  internally to fit. Fix: binary P1 now rejects when nested
  emits introduce newlines.
- **Generic class headers with a long first type parameter
  now wrap by breaking after `<`** (`_emit_class_header_wrapped`).
  The previous shape always kept the first type parameter on
  the class declaration line; when that first parameter was
  the long one the line couldn't be brought under 80 chars
  by the formatter — the adopter was forced to a manual
  `// CSOFF` / `// CSON` pair, which the spec explicitly
  forbids as a general escape hatch. Fix: a new P3 shape —
  break right after `<`, each type parameter on its own
  continuation line — engages when the P2 shape (first
  parameter on the declaration line) would overflow.
- **Trailing `// side comments` now stay attached to the
  statement they follow** (`_emit_indented_member_list` and
  `_emit_block`). Per spec C6 ("End-of-line side comments"),
  a `line_comment` that originally sat on the same source
  row as the preceding statement / member is emitted on the
  same emitted line with two spaces of separation. The
  previous behavior put the comment on its own line above
  the next statement, visually re-attaching it to the wrong
  code.
- **SessionStart hook now verifies `origin` points at
  `java-coding-standards` before comparing tags**
  (`adoption/claude-md-templates/claude-hooks-snippet.json`).
  In CI / detached-submodule contexts the hook's
  `cd "${CLAUDE_PROJECT_DIR}/.java-coding-standards"` could
  resolve git operations against the parent repository (the
  submodule `.git` resolving to the parent's gitdir), so
  `git ls-remote --tags origin` returned the parent's tags
  and the hook nudged with the wrong release identifier.
  Fix: an explicit `git remote get-url origin` substring
  check; exits silently when the URL doesn't reference
  `java-coding-standards`. Adopters with existing
  `.claude/settings.json` files carrying the 0.2.5–0.4.1
  hook should re-run `/init-java` — the playbook's
  migration-detection now recognizes the older shape and
  offers to replace it.

### Tests

New golden fixtures (each runs through the harness's
automatic idempotency check):

- `method_chain_wrap/08_chain_with_args_dot_aligned` — locks
  the chain-wrap-over-arg-wrap precedence with a
  builder-style chain whose intermediate calls carry args.
- `condition_wrap/06_binary_precedence_keeps_atomic` — locks
  `a == null || b.isZero() || c.isDestroyed()` wrapping at
  `||` only, with `== null` kept atomic.
- `condition_wrap/07_mixed_precedence_inner_parens_atomic` —
  locks `a * b + (c / d)` breaking at the top-level `+` with
  the inner parenthesized sub-expression staying together.
- `class_header_wrap/06_type_params_break_after_open_angle` —
  locks the new break-after-`<` shape for generic class
  headers whose first type parameter would otherwise force a
  CSOFF.
- `line_comment_reflow/08_trailing_inline_comment_stays_attached`
  — locks `// side comment` attachment across multiple
  statements in a method body.
- `line_comment_reflow/09_trailing_block_comment_stays_attached`
  — locks `/* side comment */` attachment for the
  single-row block-comment variant of the same C6 rule
  (added in follow-up to the initial commit while
  extracting `_attach_trailing_side_comments` to handle
  both comment types consistently).

Fixtures use synthetic class names (`Demo`, `Outer`,
`MyConfigurableEnvironment`, `BaseEnvironment`,
`Initializer`) rather than copying identifiers from any
single consumer project.

### Verification

- 597 standards-repo tests pass (was 591, +6 new fixtures).
- `senzing-commons-java`: formatter produces a one-time
  format diff (26 files modified — chain wraps and
  precedence-aware operator breaks engaging where 0.4.1's
  malformed output had previously committed); the second
  pass is idempotent and `mvn -Pcheckstyle validate`
  remains BUILD SUCCESS.
- `sz-sdk-java`: same shape — 21 files reformat once,
  idempotent on the second pass.

## [0.4.1] - 2026-06-16

Two wrap-engine bug fixes surfaced by adopting 0.4.0 into
`sz-sdk-java` — both produced 81-char overshoots that the
formatter declined to wrap. Each was an off-by-one
`tail_reserve` miss; the fix in each case is a one-line
threshold adjustment plus (for one of them) propagating the
reserve into a nested wrap engine.

### Fixed

- **try-with-resources `) {` reserve missing**
  (`_emit_try_with_resources_statement`): for the
  single-resource form, the parent did not bump
  `tail_reserve` before dispatching to `_emit_resource`. The
  resource emitter's inline-fit check already reserved 1 char
  for the closing `)`, but the additional ` {` (2 chars) that
  the parent appends for the same-line body brace was not
  budgeted. A borderline-fit resource that ended at column 78
  would pass the resource's inline check, then land at 81
  chars on disk after the parent wrote `) {`. Fix: bump
  `tail_reserve` by 2 around the single-resource dispatch.
  Multi-resource form already uses Allman braces (body on its
  own line) so no extra reserve is needed there.

- **Abstract / interface / native method `;` reserve missing**
  (`_emit_method_declaration` + `_emit_formal_parameters`):
  the signature overflow check compared rendered width
  against `_MAX_LINE` (80) without accounting for the
  trailing `;` that gets appended for body-less methods. A
  signature emitting to exactly 80 chars would pass the
  check, then become 81 chars on disk after `;`. Fix: lower
  the fit threshold by 1 when `body is None`, and propagate
  the `tail_reserve` bump into the param-wrap path so the
  inner P1/P2 fit checks also see the reserve. As part of
  this, `_emit_formal_parameters` was generalized to honor
  `tail_reserve` in both its P1 and P2 fit-check comparisons
  — previously they compared against bare `_MAX_LINE` and
  ignored any caller-set reserve.

### Documentation

- Adoption playbook (`adoption/adopt-standards-prompt.md`):
  added a "first-time formatter dependency install" note in
  Step 2 — adopters need
  `python3 -m pip install --break-system-packages --user -r
.java-coding-standards/tooling/scripts/requirements.txt`
  on Homebrew Python (PEP 668), or the equivalent for their
  platform, before the PostToolUse hook and VSCode
  format-on-save will work. The playbook's Step 13
  verification already invokes `python3 format_file.py` and
  expected the deps to be available; without the install
  step the verification fails on a fresh machine. Addresses
  issue #27 (short-term fix only — the longer-term PEP 723
  inline-deps shebang path remains open for a future
  release).
- `docs/faqs/building/java-formatting-standards.md`: matching
  one-paragraph note on the same install step so the FAQ
  search surface covers the question.

### Tests

- New golden fixtures:
  - `method_decl_wrap/04_abstract_method_semicolon_reserve`
    locks the `;` reserve for abstract / native / interface
    methods. Input is the actual sz-sdk-java repro shape
    (`public native int searchByAttributes(String jsonData,
StringBuffer response);` at 81 chars); expected output
    is the paren-aligned P2 wrap.
  - `allman_braces/19_try_with_resources_brace_reserve`
    locks the ` {` reserve for single-resource
    try-with-resources. Input is the actual sz-sdk-java
    repro shape; expected output uses the spec B8
    break-at-`=` form.

### Verification

- 591 standards-repo tests pass (was 589, +2 new golden
  fixtures — each runs through the harness's automatic
  idempotency check too).
- `senzing-commons-java`: 106 files processed, 0 modified
  (clean on both passes — 0.4.0 baseline still steady-state).
- `sz-sdk-java`: the two original 81-char overshoots now
  wrap cleanly; formatter is idempotent at the new fixed
  point.

## [0.4.0] - 2026-06-12

The wrap-priority engine cutover. The formatter now drives every
wrappable construct through a single `try_priorities` cascade
that threads a `tail_reserve` budget through nested contexts —
each enclosing construct (`if`, `while`, `for`,
`expression_statement`, `parenthesized_expression`,
`method_invocation` receiver, `return`/`throw` statements)
reserves chars for the trailing tokens it knows about, so an
inner wrap candidate's effective line budget reflects the FULL
surrounding line, not just the local emission.

This eliminates the long tail of "wrap engine fits locally but
the trailing `) {` / `;` / `).method()` pushes the line past
80" failures that the 0.3.0 wrap cascade left behind. The
consumer adoption gate against `senzing-commons-java` drops
from 51 LineLength violations to 0; sz-sdk-java verifies
117/117 files clean and idempotent.

Highlights:

- **`WrapContext` + `try_priorities`** abstractions in
  `format_java.py`. Replaces the ad-hoc `start_col` arguments
  and snapshot/restore dances scattered through individual
  emitters. Documented in
  `docs/java-coding-standards.md` § "Wrap Priority Engine".
- **`tail_reserve`** push/restore mechanism on the emitter.
  Composes additively: `if (binary) {` reserves `2 + 1 = 3`
  chars (`) {` from the `if`, `)` from the paren-expression)
  so the binary expr's effective max is 77.
- **Method-chain wrap** (P1 single / P2 vertical-aligned
  dots / P3 single-indent fallback) in
  `_emit_method_invocation`. Method-invocation's simple emit
  also propagates `tail_reserve` to its receiver so chains
  inside parenthesized casts wrap correctly.
- **Ternary wrap** (T1 single / T2 break-before-`?` / T3
  break-before-both) in `_emit_ternary_expression`.
- **Binary-expression wrap** with full AST recursion (no
  more raw-source-rest fallback). P1 / P2 break-leftmost /
  P3 break-every-op via `try_priorities`.
- **Condition wrap** for `if`/`while`/`for` — tail_reserve
  bumped for the trailing `) {` / `) STMT` so nested binary
  expressions wrap when needed; for-statement adds an Allman
  brace fallback when `for (...) {` would overflow.
- **Line comment reflow** (spec § "Line Comment Reflow") —
  `//` comments that overflow are greedy-reflowed into
  multiple `// `-prefixed lines at the same indent.
  Directive exemptions (`CSOFF`, `CSON`, `CHECKSTYLE`,
  `SUPPRESS`, `@`-tags) and URL-bearing lines are preserved
  verbatim.
- **Conditional source-preserve** in arg lists — when an
  arg list spans multiple rows in source, preserve the
  developer-authored layout IF the first line still fits at
  the new emission column. When the surrounding indent has
  shifted (e.g. JDT's 2-space → AST's 4-space) and the
  source's first line would overflow, fall through to the
  wrap engine. Comments inside the arg list always force
  source-preserve (the wrap engine can't represent
  comment-between-args). The spec's "Formatted Log and
  Diagnostic Messages" `// CSOFF` / `// CSON` markers also
  force source-preserve via `_is_inside_csoff_region`.
- **Text blocks in indented contexts** (spec B4 full
  enforcement) — triple-quoted text blocks now emit at any
  indent level. The closing `"""` lands at +4 from the
  introducing statement; content lines shift by the same
  delta so the rendered string is byte-for-byte unchanged.
- **Class-header wrap** — when type parameters wrap to
  multiple lines AND the trailing `extends` / `implements`
  is also long, the clauses move to their own continuation
  line(s) instead of overhanging the closing `>` line.
- **Annotation type declarations** (`@interface ...`) and
  comma-separated `for_statement` init/update expressions
  (`for (i = 0, j = 0; ...; i++, j++)`) now emit instead of
  refusing — surfaced by sz-sdk-java adoption.
- **`_PARSER` thread safety** — replaced the module-level
  singleton with a `threading.local` lazy wrapper. Formatter
  is now safe to use from `pytest-xdist`, parallel batch
  formatters, and in-process services.
- **Test infrastructure** — added `tests/test_fixtures.py`
  to auto-discover and verify every fixture pair under
  `tests/fixtures/CATEGORY/CASE/` (the input + expected
  pair) as a live golden test (the existing 70 fixture
  pairs were previously dead data).
  Every golden case ALSO asserts idempotency (format(actual)
  == actual). 28 new fixture cases covering all new wrap
  behaviors. Added unit tests for `WrapContext`,
  `try_priorities`, and `Emitter.tail_reserve`. Total
  passing tests: 578 (up from 463 at 0.3.0).

Review-driven fixes (in this same release cycle):

- **`_emit_resource`** restructured to match spec B8
  preference order — break-at-`=` is now the first fallback
  when the inline form overflows, BEFORE letting the value's
  inner wrap engine fire. The previous behavior could keep
  `try (X r = new Foo(...))` inline (with the value wrapping
  internally) when the spec calls for the break-at-`=` form
  with `X r` on the first line and `= new Foo(...)` on the
  continuation line, with the value emitted single-line.
- **CSOFF scope set** expanded with `switch_block` and
  `switch_block_statement_group`. A `// CSOFF` directive
  inside one colon-form switch case no longer bleeds into
  subsequent cases.
- **Source-text-width shortcuts replaced with speculative
  emission** in `_emit_throws`, `_emit_if_statement`'s
  Tier 1 short-circuit check, and `_emit_variable_declarator`
  steps 1–2. Wrap decisions are now uniformly driven by
  rendered widths, not source-text widths — robust against
  unusual input whitespace and consistent with the rest of
  the wrap engine.
- **`_emit_field_access`** propagates `tail_reserve` to its
  receiver emit. Nested method-chain wrap inside a
  field-access head (e.g. `chain.thing().result.method()`)
  now correctly accounts for the trailing `.field`.
- **`_emit_variable_declarator`** consumes
  `emitter.tail_reserve` in its width calculations, matching
  the rest of the wrap engine's tail-reserve composition.
- **For-statement paren-aligned header wrap** — when the
  for-header is over budget but contains no binary expression
  to wrap (the previous condition-wrap engine relied on
  `&&`/`||`), init/condition/update each move to their own
  line at the column after `for (`, mirroring the
  multi-resource try-with-resources shape.

## [0.3.0] - 2026-06-11

The architectural cutover from the JDT + six-script pipeline
to a pure-Python AST-based formatter built on
`tree-sitter-java`. Same end-user `format_file.py` CLI; same
spec-compliant output; no JDK required at runtime; no
subprocess pipeline. See
`docs/faqs/building/java-formatting-standards.md` ("Upgrading
from 0.2.x") for adopter migration notes.

Highlights:

- **Comprehensive spec** (`docs/java-coding-standards.md`)
  filled in the 25 audit gaps surfaced in planning —
  modern syntax (records, sealed/permits, switch
  expressions, pattern matching, text blocks, lambdas,
  method references), spacing rules, import organization,
  blank-line rules, annotation placement, and several
  existing-rule clarifications.
- **AST formatter** at `tooling/scripts/format_java.py`
  built incrementally over Phases 2a–5g. Calibration gate
  closed at 83/83 fixture MATCH.
- **JDT pipeline removed**: 6 `fix_*.py` override scripts,
  the `tooling/jdt-formatter/` Maven module, the
  `tooling/ide/java-formatter.xml` Eclipse profile, the
  JDT JAR release workflow.
- **Pre-flight** against three real-world Java corpora
  (senzing-commons-java, sz-sdk-java, senzing-api-server —
  ~838 files total). All 838 traverse the formatter end-
  to-end without refusals on the targeted node types.
- **Robustness gates** — fuzz harness verifies round-trip
  AST equivalence + idempotency + error-recovery against
  the consumer corpus. Surfaced and fixed 5 additional
  bugs (C-style array dimensions, multi-line value
  overflow check, for/while header layout decision,
  `<li>` indent classification).
- **Performance gate** — 100-file warm format completes in
  ~150ms (median ~0.9ms / file), 65× under the 10s budget.

Full per-phase notes in the `### Added` section below,
reverse-chronological from Phase 8d.

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
  has just its own multi-tier wrapping rules and lands in a
  later phase.
- Phase 8c Robustness gates — fuzz harness + error-recovery.
  New `tooling/scripts/tests/test_fuzz_corpus.py` exercises
  the formatter against a real-world Java corpus and
  verifies three properties for every file:
  1. **Round-trip AST equivalence** — formatter output
     re-parses to the same named-node-type sequence as
     the input (modulo formatter-allowed normalizations
     like `enum_body_declarations` and `block` brace
     wrapping). Catches emitter bugs that would silently
     change Java semantics.
  2. **Idempotency** — formatting twice produces the same
     output: `format(format(src)) == format(src)`.
  3. **Refusal cleanliness** — declined constructs raise
     a typed exception with a diagnostic; never a
     traceback into formatter internals.
     Plus a six-case parametrized
     `test_broken_input_raises_value_error` for the
     error-recovery property: malformed
     inputs (unterminated class body, malformed condition,
     missing RHS, unbalanced parens, non-Java text) raise
     `ValueError` cleanly; the empty input is a valid Java
     program and formats to `b""`.
     Default corpus: `senzing-commons-java/src/` (~106 files).
     Set `SENZING_JAVA_FUZZ_CORPUS` to an absolute path to
     fuzz against a different / larger corpus.

  The fuzz harness surfaced **five real formatter bugs**
  that landed alongside the harness in this phase:
  - `_emit_variable_declarator` silently dropped C-style
    array dimensions on the variable name
    (`Class<?> params[] = ...` → `Class<?> params = ...`,
    losing the array type). The grammar exposes those as
    a `dimensions` named child of `variable_declarator`;
    the emitter now dispatches it between the name and
    the `=`.
  - `_emit_variable_declarator` had a
    `value_is_multiline: return` shortcut that skipped the
    inline-overflow check. When the multi-line source
    value collapsed to
    a long single line on first emission, the first pass
    kept the over-80 line; the second pass (now seeing a
    single-line value) correctly broke at `=`, causing
    non-idempotency. Removed the shortcut; the overflow
    check now runs regardless of `value_is_multiline`.
  - `_emit_for_statement` chose the brace placement
    based on source-row span, not on the formatter's
    eventual rendered layout. When wrapping inside the
    init / condition / update produced a multi-row
    header from single-row source, the first pass emitted
    same-line brace (wrong) and the second pass switched
    to Allman (correct), causing non-idempotency. Now
    snapshots emitter state before the header and
    switches to Allman when `emitter.line_count` grew
    during emission.
  - `_emit_while_statement` had the same flaw for the
    single-row-source path; applied the same
    `line_count`-grew check.
  - `_javadoc_is_prose_line` only recognized list-item
    markers when `<li>` appeared at position 0 of the
    content. The (common!) leading-indent variant
    `*   <li>...` (extra spaces between `*` and `<li>`
    for visual nesting under `<ol>` / `<ul>`) was
    misclassified as prose; the following non-`<li>`
    line got reflowed into the `<li>` paragraph. Fixed
    by stripping leading whitespace before all the
    structural-marker checks (`@`, `<li>`, block tags,
    etc.).

  One known non-idempotent file is `xfail`-marked in the
  test:
  `senzing-api-server/.../api/services/BulkDataSupport.java`
  hits a method-chain wrap interaction the wrap-priority
  engine doesn't yet handle cleanly. Documented in
  `_KNOWN_NON_IDEMPOTENT` with a description; the day the
  underlying limitation gets fixed the entry can be
  deleted.

  Verification across three corpora:

  - **Default** (senzing-commons-java/src, 106 files):
    453 tests pass.
  - **sz-sdk-java/src** (284 files): 226 pass + 14
    skipped (refusals).
  - **senzing-api-server/src** (448 files): 613 pass + 6
    skipped + 1 xfail (the documented method-chain case).

  Calibration recon: 83/83 MATCH preserved.

  pytest suite: 453 total — 235 baseline (format_java +
  format_file) plus 218 fuzz cases against the default
  corpus.

  Out of scope (Phase 8d+):

  - Performance gate: 100-file warm format < 10s.
  - Method-chain wrap awareness (the BulkDataSupport.java
    fix).
  - Version bump + tag 0.3.0.

- Phase 8b FAQ refresh for 0.3.0 architecture:
  - `docs/faqs/building/java-formatting-standards.md`
    rewritten — replaced the JDT + six-script "Formatter
    pipeline" architecture section with a description of
    the in-process tree-sitter formatter (Emitter /
    dispatch / wrap-priority engine). Replaced the "Running
    the pipeline" section with the new CLI usage (single
    `format_file.py` entry point plus
    `format_java.py --format FILE` for inspection).
    Removed the per-script behavior
    summary list. Added an "Upgrading from 0.2.x" section
    explaining the architectural shift, the one-time
    reformat expected, and the legacy artifacts to delete.
  - `docs/faqs/building/javadoc-reflow-conventions.md`
    updated — replaced the small reference to the old
    `fix_javadoc_*` scripts with a pointer to
    `format_java.py`'s javadoc emitter, which respects the same
    "no orphan words" / "no invented filler" rules by
    design. Updated the "When in doubt" pointer to
    `format_file.py`.
    No code, test, or non-FAQ doc changes. The FAQ MCP
    server picks up the new content on next restart per the
    standard re-index flow.
- Phase 8a Docstring updates + adoption-template refresh:
  - `tooling/scripts/format_java.py` module docstring
    rewritten — the old narrative documented incremental
    rollout phases ("Status (Phase 2z): tree-sitter-java
    is loaded..." and a long list of constructs added by
    phase). Replaced with a concise architecture section
    (Emitter / dispatch / wrap-priority engine), a
    coverage section (every fixture + every consumer
    file traverses; deliberate out-of-scope:
    `module_declaration`), and a CLI section listing the
    new `--format FILE` flags (`--write`, `--check`).
  - `adoption/claude-md-templates/vscode-settings-snippet.json`
    rewritten — removed the
    `java.format.settings.url` entry pointing at the
    deleted `tooling/ide/java-formatter.xml`, simplified
    the orchestrator commentary to describe the in-
    process tree-sitter formatter.
  - `adoption/claude-md-templates/full-section-template.md`
    "Bulk formatting scripts" section rewritten — replaced
    the five-script enumeration with a description of
    `format_file.py` as the single end-user entry point,
    showing how to run it against a file or directory tree.
  - `adoption/adopt-standards-prompt.md` updated — removed
    `.vscode/java-formatter.xml` from the "existing
    standards artifacts" probe list; added a 0.3.0 cleanup
    section listing legacy artifacts to delete when
    upgrading (`.claude/scripts/fix_*.py`, the JDT XML
    profile, the JDT JAR cache, task/hook references). The
    "first formatter run" guidance now describes what to
    expect when upgrading from the 0.2.x pipeline (one-
    time sizeable reformat) vs running 0.3.0+ at the same
    pin (zero modifications).
  - `adoption/verification-checklist.md` updated — the
    bulk-format verification section now shows the
    single-line `Formatter:` output the new orchestrator
    produces, and the "JDT formatter should not run"
    wording in the VSCode section was replaced with a
    cleaner explanation of the redhat.java +
    emeraldwalk.runonsave split.
    No formatter code changes, no test changes. Calibration
    still 83/83; pytest suite still 235.
- Phase 7 JDT pipeline removal — the atomic switch:
  - `tooling/scripts/format_file.py` rewritten as a thin
    orchestrator that resolves target paths via
    `_cli.iter_target_files` and invokes `format_java.format_source`
    in-process per file. Same CLI surface as before
    (positional paths, `--src-dirs`, `--exclude`,
    `--exclude-from`). Mtime is restored on byte-identical
    runs to keep IDE / build-cache hygiene quiet on
    idempotent saves.
  - The six legacy override scripts and their tests deleted:
    `fix_allman_braces.py`, `fix_javadoc_reflow.py`,
    `fix_javadoc_inline_tags.py`, `fix_javadoc_tags.py`,
    `fix_need_braces.py`, `fix_throws_alignment.py`. Their
    behavior is subsumed by `format_java.py`'s emitter
    walk; `format_file.py` no longer subprocess-invokes
    anything.
  - The Eclipse JDT formatter Maven module deleted:
    `tooling/jdt-formatter/` (pom.xml, the JdtFormatter.java
    shim, .gitignore). The XML profile
    `tooling/ide/java-formatter.xml` was deleted with it;
    the `tooling/ide/` directory is now empty and was
    pruned. Consumers no
    longer need a JDK on `PATH` to run `format_file.py`.
  - `.github/workflows/release.yaml` deleted — its only
    purpose was building and publishing the JDT JAR on
    `v*` tag push; the workflow has no remaining function.
    Future tag-driven release automation can be added back
    later if needed (e.g. CHANGELOG-based release notes).
  - `.github/workflows/pytest.yaml` simplified: removed
    the `setup-java@v5` step and the JDT JAR build step.
    CI now only needs Python + the formatter's runtime
    deps from `tooling/scripts/requirements.txt`.
  - `.github/dependabot.yml`: removed the
    `tooling/jdt-formatter` maven-ecosystem entry. The
    repository's only remaining ecosystems are github-
    actions and pip (under `tooling/scripts/` +
    `tooling/scripts/tests/`).
  - Test cleanup: deleted `test_format_file_jdt_pipeline.py`,
    `test_jar_resolution.py`, `test_helpers.py` (a unit
    test for `fix_allman_braces` helpers), and
    `test_idempotency.py` (which iterated each fix\_\*.py
    script over fixtures). Rewrote `test_format_file.py`
    as a smaller, sharper suite focused on the new
    orchestrator's contract (10 tests covering unchanged /
    changed / refused / parse-error / multi-file
    aggregation / mtime-preservation / CLI passthrough).
  - Calibration-recon: 83/83 MATCH preserved.
  - pytest suite: 235 total (225 format_java + 10
    format_file).

  Out of scope for this commit (Phase 8 follow-up):

  - Adoption-template updates under `adoption/` — the
    `/init-java` flow still references the JDT JAR /
    profile / script-pipeline; needs a rewrite to describe
    the new single-file architecture.
  - FAQ refresh under `docs/faqs/building/` — both
    `java-formatting-standards.md` and
    `javadoc-reflow-conventions.md` still document the old
    pipeline.
  - Module / class-level docstrings in `format_java.py`
    and `format_file.py` still describe the migration as
    pending; bump them to "complete" wording.

- Phase 6c switch_expression + record_declaration emitters:
  the last two REFUSED node types from the senzing-commons-
  java pre-flight are now handled, dropping REFUSED to 0/106.
  Switch support (spec B2):
  - `_emit_switch_expression` covers both the statement
    form and the expression form (same node type in
    tree-sitter-java). The `switch (cond)` header keeps
    the cond on its source line; the body opens Allman
    because cases flow on multiple lines.
  - `_emit_switch_block` emits the `{ CASES }` block with
    cases indented `+4` from the block's left anchor
    per spec B2's revised case-indent rule. Source-
    preservation of blank lines between cases.
  - `_emit_switch_rule` handles the arrow form
    (`case LABEL -> body[;]`) with single space around
    `->` per spec B2. Multi-row sources fall through to
    verbatim emission.
  - `_emit_switch_block_statement_group` handles the
    colon form (`case LABEL: stmts...`). One or more
    `switch_label` children stack as fall-through labels
    at the case indent; statements indent `+4` from the
    case label. Each statement emits via dispatch so
    authoritative re-indentation propagates correctly.
  - `_emit_switch_label` emits `case VAL[, VAL...]` or
    `default` (handles both single-value and multi-value
    cases per spec B2's multi-label rule).
  - `_emit_yield_statement` emits `yield VALUE;` for
    Java 14+ switch-expression block-body yields.
    Record support (Java 16+):
  - `_emit_record_declaration` emits
    `[modifiers] record NAME(components) [implements ...]
{ body }` with Allman brace placement (records are
    type declarations like classes).
  - `_emit_compact_constructor_declaration` emits a
    record's compact constructor (`[modifiers] NAME { body
}`) with Allman braces per spec B9.
    Unit-test cleanup: the `test_unknown_node_type_raises`
    test used `switch_expression` as the "intentionally
    unregistered" example; replaced with `module_declaration`
    (which IS intentionally out-of-scope per the plan's
    "module-info.java" exclusion). Calibration-recon: MATCH
    stays 83/83 (no regressions). Pre-flight against the
    senzing-commons-java consumer codebase:
    MATCH 12 / CHANGED 94 / REFUSED 0 / ERROR 0 — every one
    of the 106 consumer files now traverses the formatter
    end-to-end. CHANGED aggregate diff grew (avg +21 / -26
    per file) because the newly-unblocked switch files have
    large reformatting diffs from the spec's stricter case-
    indent rule (case at +4 from switch column, vs the older
    Java convention of case at switch column that consumer
    code currently uses).
- Phase 6b Pre-flight bug fixes — spot-check survey of CHANGED
  files surfaced three real bugs:
  - **Varargs parameter silently dropped**:
    `_emit_formal_parameters` filtered to `formal_parameter`
    children only, so `spread_parameter` (the grammar's
    node type for
    `Type... name` varargs) was excluded — methods like
    `logError(Object... lines)` became `logError()`. Added
    `_emit_spread_parameter` per spec B12 (no space before
    `...`, single space after) and updated the parameter
    filter.
  - **Blank line inserted between leading javadoc and class**:
    `_emit_program`'s blank-line rule emitted a blank between
    any two consecutive top-level children, including a
    `block_comment` (javadoc) and the class it documents. Per
    spec A1 ("Class-level javadoc placement"), the javadoc
    attaches to the type with NO blank between. Fix: when
    `prev` is a `block_comment` / `line_comment`, follow
    source — emit a blank only if the source had one.
  - **IndexError on `@param NAME` with empty description**:
    `_emit_javadoc_block`'s tag reflow accessed
    `desc_lines[0]` without checking for empty
    `desc_lines`. Some
    consumer files have bare `@param NAME` with no
    description (or the description on a continuation line
    that the collector didn't pick up). Fix: short-circuit
    with `emitter.write(star_prefix + tag_prefix.rstrip())`
    when no description was collected.
    Calibration-recon: MATCH stays 83/83 (no regressions). Pre-
    flight against the senzing-commons-java consumer codebase:
    MATCH 0 → 12, CHANGED 90 → 79, ERROR 1 → 0. The 15 REFUSED
    files (14 × `switch_expression`, 1 × `record_declaration`)
    await their respective emitters.
- Phase 6a Pre-flight infrastructure (Step A + Step B groundwork):
  Add the end-user formatter entry point and a batch of
  emitters needed for real consumer code:
  - `format_java.py` CLI gains `--format FILE [--write |
--check]` for single-file formatting. The `--write`
    form rewrites the file in place; `--check` exits 0 if
    compliant / 1 if formatting would change the file / 2
    on parse or refused-construct errors. NotImplementedError
    and ValueError from format_source surface as clean
    diagnostics on stderr.
  - New emitters for `package_declaration`,
    `import_declaration` (including static and wildcard
    `.*` via the named `asterisk` child),
    `scoped_identifier`, `class_literal`,
    `array_initializer`, `element_value_array_initializer`,
    `array_creation_expression`, `array_access`,
    `dimensions`, `dimensions_expr`,
    `synchronized_statement`,
    `explicit_constructor_invocation` (`this(...)` /
    `super(...)`), `extends_interfaces` (on interface
    declarations), and `method_reference` (`Class::method`).
  - `_emit_enum_declaration` now accepts `super_interfaces`
    (enum implementing interfaces);
    `_emit_interface_declaration` accepts
    `extends_interfaces` (interface extending parent
    interfaces); `_emit_formal_parameter`
    accepts modifiers (keyword `final` + parameter
    annotations like `@NonNull`) inline — explicit inline
    emission since `_emit_modifiers` puts annotations on
    their own line (suitable for declarations, not for
    parameters).
  - `_emit_program` orchestrates blank-line separators
    between top-level declarations (one blank after
    `package_declaration`; no blank between consecutive
    imports; one blank between last import and the
    following type declaration; one blank between
    consecutive type declarations).
  - `_emit_class_body_members`,
    `_emit_interface_body_members`,
    `_emit_block`, and method/constructor body
    emitters now preserve source-authored blank lines
    between consecutive members / statements (per spec A2
    blank-line rules; source-preservation captures spec
    A2 implicitly because real consumer code already
    follows the rules). Detection uses
    `next.start_point[0] - prev.end_point[0] > 1`.
  - `_emit_enum_body_members` collects `block_comment` /
    `line_comment` siblings of `enum_constant` nodes as
    "preceding javadoc" groups and emits them above each
    constant — the grammar surfaces these as enum-body
    siblings, not enum_constant children.
  - `_emit_variable_declarator` rebalances its wrap
    decision: it now prefers a clean break-at-`=` form
    over inline-with-value-wrap when break-at-`=` gives a
    single-line value. Order: (1) inline single-line if
    fits; (2) break-at-`=` if single-line value fits at
    the continuation column; (3) inline with value-wrap.
  - `_emit_binary_expression` rest-text emission now uses
    `write_raw_lines` when the source span contains
    newlines (the previous `emitter.write(text)` rejected
    embedded newlines and crashed on consumer code with
    already-wrapped binary expressions).
    Calibration-recon impact: MATCH stays 83/83 (no
    regressions). Pre-flight against the senzing-commons-java
    consumer codebase (~106 Java files under `src/`) now
    shows REFUSED 100% → 14% (only `switch_expression` and
    `record_declaration` remain unhandled in the corpus);
    CHANGED 0% → 85%; ERROR 1 file (an `IndexError` to
    diagnose).
- Phase 5g Wave-3 method-call P4 + binary-expression wrap
  — closes the calibration gate at MATCH 83/83.
  Two interlocking wrap-priority additions for the final
  DIFFER fixture
  (`orchestrator/08_string_concat_spec_layout`):
  - `_emit_argument_list` now emits the spec's P4 form
    (next-line single-indent) when a SINGLE-arg call's
    P1 single-line form overflows 80 chars. Layout:
    `methodName(\n<single-indent>arg)`. The arg is
    emitted at `(indent_level + 1) * 4` (single-indent
    past the call's statement start). The closing `)`
    stays on the arg's last line. P4 fires only for
    single-arg overflow; multi-arg overflow continues to
    use P2 (paren-aligned, comma-packed).
  - `_emit_binary_expression` now uses speculate-
    measure-backtrack. The emitter speculates the
    single-line shape; on overflow it backtracks and
    re-emits with a break BEFORE the leftmost binary
    operator in the chain. The leftmost operand lands on
    its own line; the operator plus the remainder of the
    chain wraps to a continuation at `+4` indent (per
    spec C3 cumulative continuation rule). Implementation
    walks the left-associative grammar tree to find the
    leftmost binary_expression — for `a + b + c + d`
    parsed as `((a + b) + c) + d`, the visually-leftmost
    `+` is the one owned by the deepest left-descendant
    binary_expression. After the leftmost operand and
    operator, the remainder of the expression emits from
    the source text (verbatim) because the source's
    whitespace around remaining operators is already
    spec-compliant for the current corpus.
    Calibration-recon impact: the last DIFFER fixture
    graduated to MATCH. **MATCH 82 → 83 (out of 83). DIFFER
    1 → 0. PARTIAL still 0. MISSING still 0.** The
    calibration gate (verification step 0 in the original
    plan) is now closed: every one of the 83 existing
    fixtures passes byte-for-byte against the spec-compliant
    formatter.
- Phase 5f Wave-3 class headers — `superclass` plus
  `super_interfaces` plus type-parameter wrap on overflow:
  `_emit_class_declaration` no longer refuses `superclass`
  / `super_interfaces` clauses. Two new emitters cover
  the single-line forms — `_emit_superclass` emits
  `extends TYPE`, `_emit_super_interfaces` emits
  `implements TYPE, ...` via the `type_list` child.
  The class-declaration emitter speculates a single-line
  header (modifiers + `class NAME<T1, T2>` + extends +
  implements); if the resulting line exceeds 80 chars, it
  backtracks via `Emitter.snapshot()` / `restore()` and
  re-emits using a new `_emit_class_header_wrapped`
  helper. The wrap shape: first type-parameter on the
  class line after `<`; subsequent type-parameters each on
  their own continuation line at `start_col + 4` (single-
  indent past the class declaration's start column); `>`
  ends the last type-parameter line; ` extends X` and
  ` implements Y, Z` flow on that same line (which fits
  for the fixture's case). The body's opening `{` is
  always Allman for the class declaration; the wrap
  doesn't change brace placement (already Allman). C1
  emit-and-warn applies if even the wrapped form
  overflows. The `permits` clause continues to refuse
  pending a follow-up. Calibration-recon impact: the
  previously-PARTIAL
  `orchestrator/10_long_generic_class_decl_wraps` fixture
  graduated straight to MATCH. MATCH 81 → 82. DIFFER
  unchanged at 1. PARTIAL 1 → 0.
- Phase 5e Wave-3 argument-list source-preservation:
  `_emit_argument_list` now preserves a source-authored
  multi-row argument list verbatim (via
  `write_raw_lines(_node_source_text(node))`) before
  attempting any wrap-priority decision. This handles cases
  like a method call inside a try-with-resources resource
  value whose source already wraps `(\n    "arg" ...)`
  across multiple rows — the formatter respects the
  developer's authored layout instead of collapsing and
  re-wrapping at a different shape. Calibration-recon
  impact: `allman_braces/08_try_with_resources_nested`
  graduated to MATCH. MATCH 80 → 81. DIFFER 2 → 1.
  PARTIAL unchanged at 1.
- Phase 5d Wave-3 variable-declarator wrap at `=`:
  `_emit_variable_declarator` now uses a try-emit-and-
  measure pattern to decide between inline (`NAME = VALUE`)
  and broken (`NAME\n    = VALUE`) forms. The break-at-`=`
  form is the spec's continuation rule for long
  assignments: break BEFORE the `=` operator (per "Line
  Continuation / break before binary operators"); place
  the `=` at the start of the continuation line indented
  `+4` from the statement's indent (single-indent past the
  statement start). New `Emitter.snapshot()` and
  `Emitter.restore()` capture/restore the lines buffer +
  current line + indent; new
  `Emitter.last_lines_max_width(since)` reports the max
  width across all lines
  finalized after a snapshot, so the wrap-priority engine
  can detect overflow. The variable-declarator emitter
  speculates the inline form, measures, and backtracks to
  the break form when any rendered line (accounting for
  the trailing `;` the caller will write) exceeds 80
  chars. Calibration-recon impact: MATCH 78 → 80.
  DIFFER 4 → 2. PARTIAL unchanged at 1. Both
  `orchestrator/09_long_assignment_wraps_at_eq` and
  `/11_long_generic_var_decl_wraps_at_eq` graduated to
  MATCH.
- Phase 5c Wave-3 method-call args wrap (P1 → P2 paren-
  aligned): `_emit_argument_list` now measures the would-be
  P1 single-line width and falls through to P2 (two-line,
  paren-aligned, comma-packed) when P1 would exceed 80
  chars. The P2 emission greedily packs args onto the call
  line until the next arg would overflow, then breaks to a
  continuation line at the column right after `(` and
  continues placing args there. Per spec "Method Call
  Arguments / Placement (in priority order by line length)".
  Two fixture `expected.java` files were also regenerated
  as part of this commit because their pre-spec output used
  the legacy JDT-style single-indent continuation (which
  the spec explicitly calls out as the wrong-shape anti-
  pattern in "Method Call Arguments / Anti-pattern"):
  `orchestrator/01_user_failure_cases` and
  `orchestrator/03_long_line_wrapping`. The third method-
  call fixture (`orchestrator/08_string_concat_spec_layout`)
  still DIFFER — it needs P4 form (next-line single-indent)
  plus binary-expression `+`-wrap on the long-string first
  arg; that combination lands in a later phase. P3 (paren-
  aligned, one arg per line) and P4 (next-line single-
  indent) are not exercised by the current corpus apart
  from fixture 08 and remain TODO. Calibration-recon
  impact: MATCH 76 → 78. DIFFER 6 → 4. PARTIAL unchanged
  at 1.
- Phase 5b Wave-3 multi-line-header Allman + Tier-1 width
  fallback: three brace-placement decisions now hinge on
  source span / measured width:
  - `_emit_while_statement` switches to Allman brace when
    the `condition` (`parenthesized_expression`) spans
    multiple source rows. Per spec
    "Brace Placement / Exception: Multi-Line Conditions".
    The developer-authored condition layout is preserved
    verbatim from source.
  - `_emit_for_statement` switches to Allman brace when
    the for-header (init / condition / update bundle)
    spans multiple source rows. Detection compares the
    body's start row to the for-keyword's start row; when
    they differ, the header is emitted verbatim from
    source bytes (paren-aligned continuation lines from
    source, semicolon separators preserved).
  - `_emit_formal_parameters` now preserves source-
    authored multi-line parameter lists (when the params
    node spans multiple rows, emit verbatim via
    `write_raw_lines`). Method bodies are already Allman,
    so this combines naturally to produce the spec's
    multi-line-params-with-Allman shape.
  - `_emit_if_statement` Tier-1 short-circuit collapse
    now gates on a measured width check: if the would-be
    Tier-1 line (leading indent + `if ` + condition
    source + ` ` + short-circuit statement source) exceeds
    80 chars, fall back to Tier 2 (braced). Also inhibits
    Tier 1 when the condition spans multiple rows (no
    Tier 1 form makes sense for a multi-row condition).
    New shared helper `_node_spans_multiple_rows(node)` —
    used by all four call sites. Calibration-recon impact:
    six previously-DIFFER fixtures graduated to MATCH —
    `allman_braces/04_method_wrapped_params`,
    `allman_braces/05_while_multiline_condition`,
    `allman_braces/06_for_wrapped_header`,
    `allman_braces/10_case5_cleanup_buggy_split`,
    `need_braces/09_long_short_circuit_uses_braces`, and
    `need_braces/13_braced_short_circuit_too_long_kept`.
    MATCH 70 → 76. DIFFER 12 → 6. PARTIAL unchanged at 1.
- Phase 5a Wave-3 throws-clause wrap-priority (start of the
  wrap-priority engine): `_emit_throws` now measures the
  would-be single-line P1 width (caller's leading-indent
  column + `throws ` + sum of type source widths +
  comma-space separators) and chooses between P1 (single
  line) and P2 (one type per line, column-aligned with the
  first type after `throws `). When P1 overflows 80 chars,
  the emitter falls through to P2 — each type on its own
  line at `cont_col = start_col + len("throws ")`; each
  line but the last carries a trailing `,`. The P3/P4
  fallbacks (next-line double-indented if even P2 overflows
  the column-aligned line; CSOFF/CSON warning emission) are
  not exercised by the current corpus and remain TODO
  pending fixtures. Calibration-recon impact: all five
  throws-overflow fixtures graduated to MATCH —
  `throws_alignment/04_multi_exception_wraps_column_aligned`,
  `throws_alignment/05_compact_packed_input_re_aligns`,
  `throws_alignment/07_already_correct_idempotent`,
  `throws_alignment/12_constructor_throws_wraps_column_aligned`,
  and
  `orchestrator/13_throws_clause_multi_exception_wraps_column_aligned`.
  MATCH 65 → 70. DIFFER 17 → 12. PARTIAL unchanged at 1.
- Phase 4b Wave-2 javadoc reflow port: `_emit_comment` now
  dispatches block comments whose text begins with `/**`
  to the new `_emit_javadoc_block` emitter, which ports the
  text-level transforms from the legacy three-script
  pipeline (`fix_javadoc_reflow.py`,
  `fix_javadoc_inline_tags.py`, `fix_javadoc_tags.py`) onto
  tree-sitter-identified comment ranges. Behaviors:
  - Plain prose paragraphs (consecutive `* TEXT` lines not
    starting with `@` / `<li>` / block HTML / `{@snippet`)
    are reflowed to fill lines near 80 chars under the
    orphan-or-overlong gate: reflow fires when ANY line
    exceeds 80 chars OR when a paragraph has an awkward
    orphan continuation (next line's first word could fit
    on the previous line). Balanced paragraphs whose lines
    fit and have no orphan are emitted verbatim — the
    formatter doesn't churn developer-authored breaks just
    because lines happen to be short.
  - `{@link}` / `<code>` / similar inline-tag lines act as
    paragraph BOUNDARIES (per the legacy
    `fix_javadoc_reflow.py` rule). They emit as singletons
    while adjacent prose sub-paragraphs are reflowed
    independently. If ANY line in the surrounding
    paragraph overflows 80 chars, the whole paragraph
    reflows together (the legacy
    `fix_javadoc_inline_tags.py` fallback).
  - `@param NAME desc` / `@return desc` / `@throws Type desc`
    descriptions are reflowed under the same orphan-or-
    overlong gate. Continuation lines align with the
    description's start column (one space past `NAME` /
    `Type`, or one space past `@return`).
  - `<pre> ... </pre>` interior content is preserved
    verbatim — never reflowed (the spec carves out code
    examples).
  - `{@snippet ...}` directives and their continuation
    `file="..."` lines emit verbatim (checkstyle's
    `@snippet` ignorePattern grants them an 80-char
    exemption).
  - Comment delimiters (`/**`, `*/`), blank `*` separator
    lines, and standalone block HTML openers / closers
    (`<p>`, `<ul>`, etc.) emit verbatim.
    Output re-indents to the formatter's authoritative
    `emitter.indent_level` regardless of the source's leading
    indent. Calibration-recon impact: ten previously-DIFFER
    javadoc fixtures graduated to MATCH
    (`javadoc_inline_tags/01_link_tag_paragraph` and `/02`;
    `javadoc_reflow/01_orphan_continuation_reflowed`, `/02`,
    and `/05`; `javadoc_tags/01_param_orphan`, `/02`, `/03`,
    `/05`, `/06`, `/07`). The eleventh fixture,
    `javadoc_reflow/06_at_param_skipped`, had its
    `expected.java`
    regenerated as part of this commit — the fixture's
    pre-spec expected output reflected the intermediate state
    after the legacy `fix_javadoc_reflow.py` ran alone
    (which intentionally SKIPS `@param` tags), not the
    unified pipeline's final output (where the subsequent
    `fix_javadoc_tags.py` collapses a fitting `@param`
    description to one line). MATCH 54 → 65. DIFFER 28 → 17.
    PARTIAL unchanged at 1.
- Phase 4a Wave-2-prep fixture cleanup: nine more javadoc-\*
  fixture `expected.java` files updated to expand their
  incidental inline-`{}` method / class / constructor bodies
  to the spec's Allman form. Same drift category as Phase 3b
  (the inline-body shape doesn't match what the spec
  requires); these fixtures were missed by the original
  Phase 3b survey because their primary DIFFER reason was
  the javadoc-content reflow, which masked the secondary
  body-shape drift in the diff summary. Updating them now
  removes one layer of noise from each fixture's diff so
  that when the Wave-2 javadoc-reflow port lands, the
  remaining diff is purely about the javadoc content
  itself. Fixtures updated:
  `javadoc_inline_tags/01_link_tag_paragraph`,
  `javadoc_inline_tags/02_code_tag_paragraph`,
  `javadoc_reflow/02_inline_tag_line_preserved_prose_reflows`,
  and `javadoc_tags/01_param_orphan`,
  `javadoc_tags/02_return_orphan`,
  `javadoc_tags/03_throws_orphan`,
  `javadoc_tags/05_multiple_tags`,
  `javadoc_tags/06_long_param_name_alignment`, and
  `javadoc_tags/07_single_line_param_overshoots_eighty`.
  No formatter
  changes in this commit; fixture-only. Calibration counts
  unchanged: MATCH 54, DIFFER 28, MISSING 0, PARTIAL 1.
- Phase 3b fixture-vs-spec drift cleanup (Wave 1 — fixtures):
  nine fixture `expected.java` files updated to match the
  current spec where they encoded pre-spec JDT-era output.
  Per the plan's calibration-gate guidance ("Resolve any
  drift by either tightening the spec rule or updating the
  fixture"), the spec is correct in each case and the
  fixtures move. The drifts:
  - `allman_braces/11_if_with_inline_comment` — fixture
    had one space between `{` and `//`; spec C6 requires
    exactly two. (Formatter behavior was already correct
    in Phase 3a; this commit retires the off-by-1-byte
    DIFFER.)
  - `allman_braces/14_static_initializer` — fixture had
    same-line `static {`; spec B10 requires Allman
    (`static` and `{` on separate lines).
  - `allman_braces/18_enum_constant_body` — fixture had
    same-line `ALPHA {`; spec B9 requires Allman body
    opening for enum-constant anonymous bodies.
  - `need_braces/22_braced_short_circuit_with_paired_else_kept`
    — fixture had `}\n        else {` (uncuddled else);
    spec C5 requires cuddled `} else {`.
  - `throws_alignment/13_annotation_with_comma_args` —
    fixture had `@MyAnno(a=1, b=2)` (no spaces around `=`
    in annotation arguments); spec A4 requires single
    space on each side of assignment-style operators in
    `element_value_pair` nodes.
  - `javadoc_inline_tags/03_already_reflowed_idempotent`,
    `javadoc_inline_tags/04_pre_block_preserved`,
    `javadoc_reflow/06_at_param_skipped`, and
    `javadoc_tags/04_already_compact_idempotent` — each
    had `public class Foo {}` (or
    `public int doThing(int input) { return 0; }`)
    single-line/inline-`{}` body shapes for the test's
    otherwise-incidental class/method body; the spec
    requires Allman expansion of all type and method
    bodies regardless of contents. The javadoc content
    in each fixture was already correct, so the brace-
    shape update alone unlocks them.
    Calibration-recon impact: all 9 updated fixtures graduated
    to MATCH. MATCH 45 → 54. DIFFER 37 → 28. PARTIAL unchanged
    at 1. After Wave 1, MATCH is 65% (54/83); the remaining
    DIFFER fixtures all hinge on the wrap-priority engine
    (Wave 3) or the javadoc reflow port (Wave 2).
- Phase 3a-2 nested type-declaration brace indentation fix:
  `_emit_class_declaration`, `_emit_interface_declaration`,
  and `_emit_enum_declaration` previously emitted the
  opening `{` and closing `}` of their type body without
  `write_indent()`, so nested declarations (inside an outer
  class body) had column-0 braces instead of indented
  braces matching the type-name column. The fix adds
  `emitter.write_indent()` before each brace emit. Also
  removed the trailing `emitter.newline()` from each
  declaration emitter — it was redundant with `finish()`'s
  EOF-newline guarantee for top-level types, and produced
  a stray blank line between an inner type's closing `}`
  and the outer's closing `}` when nested (the parent's
  `_emit_class_body_members` loop adds the line
  terminator). Defect was latent — no currently-MATCH
  fixture exercised nested type declarations, but the four
  `javadoc_*` fixtures that contained `public class Foo {}`
  inner-class bodies were emitting visibly broken output.
- Phase 3a real formatter bug fixes (three bugs surfaced by
  DIFFER-fixture diagnosis after Phase 2z):
  - Tier 1 short-circuit collapse no longer fires on an
    `if_statement` that is the `alternative` of a parent
    `if_statement` (i.e. an `else if` branch). Per spec
    "Short-Circuit Conditionals / `if`/`else` pairs always
    use braces" — once any branch in an if/else chain has
    an `else`, every branch is braced, INCLUDING
    intermediate `else if` branches whose body would
    otherwise be Tier-1-eligible. New helper
    `_is_else_branch_if(node)` performs the check; the
    Tier 1 condition in `_emit_if_statement` adds it as a
    third clause. (Tree-sitter Node objects don't support
    Python `is` identity since each accessor returns a
    fresh wrapper; comparison uses `==` which the binding
    implements as structural equality on the underlying
    node id.)
  - Tier 1 collapse from a source Tier 2 block is now
    inhibited when the developer authored a blank line
    between the opening `{` and the short-circuit
    statement. The blank line is a deliberate visual-
    separation cue that single-line form would erase. The
    `_short_circuit_body` helper now compares the brace's
    source row to the statement's row and returns None
    (refusing collapse) when there is at least one empty
    line between them.
  - `_emit_block` now preserves a developer-authored blank
    line between the opening `{` and the first statement
    AND emits inline side-comments on the brace line. A
    `line_comment` or `block_comment` child whose source
    row equals the opening `{`'s row is emitted on the
    same line as the brace, separated by exactly two
    spaces per spec C6 ("End-of-line side comments").
    Subsequent statements emit on their own lines as
    normal.
    Calibration-recon impact: two previously-DIFFER fixtures
    graduated to MATCH:
    `need_braces/18_braced_else_if_chain_kept` and
    `need_braces/19_braced_short_circuit_with_blank_line_kept`.
    MATCH 43 → 45. DIFFER 39 → 37. PARTIAL unchanged at 1.
    The third targeted fixture
    (`allman_braces/11_if_with_inline_comment`) remains DIFFER
    by exactly 1 byte — the fixture has one space between `{`
    and `//`, the spec C6 rule requires two, and the formatter
    now emits two. Fixture-vs-spec drift; the fixture itself
    needs updating in the Wave-1 fixture-cleanup commit.
- Phase 2z enum constants with anonymous bodies:
  `_emit_enum_constant` now dispatches the optional body
  rather than refusing it. Per spec B9 ("Enum Constant
  Bodies"), the body opens on its OWN line (Allman braces),
  NOT same-line like C8 anonymous-class expressions — even
  though the body is structurally a class body, here it's
  the continuation of a top-level enum constant declaration
  rather than an inline expression, and the spec's "Brace
  Placement / Allman Style" rule applies. Body content uses
  standard class-body member emission via
  `_emit_class_body_members`, so method declarations inside still take
  their normal Allman brace placement. The body opens at
  the constant's indent column (via `write_indent()`), body
  members indent one level deeper, and the closing `}`
  returns to the constant's column. The trailing `,` or `;`
  separator continues to be emitted by the parent
  `_emit_enum_body_members`, which attaches naturally to the
  constant's last token (closing `)` of arguments, closing
  `}` of body, or identifier). Combined form (constructor
  arguments AND body — `PLUS("plus", 1) { ... }`) supported.
  Calibration-recon impact: the previously-PARTIAL
  `allman_braces/18_enum_constant_body` fixture graduated
  out of PARTIAL but landed in DIFFER, not MATCH — the
  fixture's `expected.java` uses pre-spec SAME-LINE braces
  (`ALPHA {`) for enum-constant bodies, contradicting the
  current spec B9 rule. The fixture itself needs updating
  as a separate calibration-cleanup pass. PARTIAL 2 → 1,
  DIFFER 38 → 39.
- Phase 2y anonymous classes on object creation:
  `_emit_object_creation_expression` now dispatches the
  optional `class_body` named child rather than refusing it.
  Per spec C8 ("Anonymous Classes"), the opening `{` stays
  SAME-LINE with `new TYPE(ARGS)` (anonymous classes are
  expressions, not top-level declarations, so they don't take
  Allman braces). Body content uses the standard class-body
  member emission via `_emit_class_body_members`, so methods
  inside the anonymous body still take their normal Allman
  brace placement (the C8 same-line rule applies only to the
  anonymous-class opening brace itself, not to members
  nested inside). The closing `}` aligns with the
  surrounding statement's indent (the emitter's current
  indent level), followed by whatever syntactic terminator
  the surrounding expression requires — `;` for an
  assignment, `)` for end-of-call, `,` for next argument,
  etc. — emitted by the caller. Calibration-recon impact:
  the previously-PARTIAL `allman_braces/13_anonymous_class`
  fixture graduated to MATCH. MATCH 42 → 43.
- Phase 2x type parameters on declarations: three new emitters
  cover the single-line `<T>` / `<T, U>` / `<T extends Foo>` /
  `<T extends Foo & Bar>` / `<@Ann T extends Foo>` shapes per
  spec B11. `_emit_type_parameters` emits the `<...>` list
  with comma-space between parameters per spec A4
  ("Whitespace and Operator Spacing"); `_emit_type_parameter`
  handles a single parameter (optional annotation(s),
  identifier, optional `type_bound`) with single-space
  separators; `_emit_type_bound` handles `extends Type` and
  multi-bound `extends A & B & ...` with single space around
  `extends` and around `&` per spec B11 / A4. The four
  declaration emitters that previously refused
  `type_parameters` now dispatch through:
  `_emit_class_declaration` and `_emit_interface_declaration`
  emit `<...>` immediately after the type name with no
  intervening space; `_emit_method_declaration` and
  `_emit_constructor_declaration` emit `<...>` BEFORE the
  return type / constructor name, with a single space after
  the closing `>`. `_emit_enum_declaration` continues to
  refuse `type_parameters` defensively (Java forbids generic
  enum declarations). The B11 multi-line wraps (P2 paren-
  aligned with the first parameter, P3 next-line single-
  indented with each parameter on its own line, plus the
  bound-clause-overflow `&` alignment) land with the wrap-
  priority phase. Calibration-recon impact: the
  previously-PARTIAL
  `throws_alignment/11_generic_type_parameter_in_throws`
  fixture moved straight into MATCH. MATCH 42 → 43.
- Phase 2w try-with-resources: new
  `_emit_try_with_resources_statement` and `_emit_resource`
  emitters cover both shapes from spec B8. A single resource
  that fits on one line keeps the opening `{` same-line:
  `try (Resource r = expr) {`. Multi-resource is ALWAYS
  multi-line — each resource on its own line, subsequent
  resources paren-aligned with the first (the column right
  after `try (`), `;` between resources but not after the
  last, and the opening `{` on its own line (Allman) because
  the try condition spans multiple lines. `catch_clause` and
  `finally_clause` children cuddle with the body's closing
  `}` the same way they do for plain `try_statement`. The
  Java 9+ shorthand resource form (an effectively-final
  variable used directly without a `Type name = ` prefix)
  refuses cleanly with a specific diagnostic; support lands
  later. The break-on-`=` wrap for an individual resource
  that overflows its own line (single-resource P2+, or
  recursive promotion inside a multi-resource block) lands
  with the wrap-priority phase. Calibration-recon impact: the
  two remaining MISSING fixtures (both
  `try_with_resources_statement`) cleared. MATCH 40 → 42,
  MISSING 2 → 0. Every fixture in the existing surface now
  RUNs through the formatter — remaining differences are all
  DIFFER or PARTIAL (wrap-priority, javadoc reflow,
  side-comment attachment, refused constructs like generic
  type parameters, and fixture-vs-spec drift cleanups).
- Phase 2v lambda expressions (single-line form): new
  `_emit_lambda_expression` handles `PARAMS -> BODY` with
  single space on each side of `->` per spec B5. The
  parameters field can be a bare `identifier` (single
  inferred-type param: `s -> body`), an
  `inferred_parameters` node (multi inferred-type:
  `(x, y) -> body`), or a `formal_parameters` node
  (explicit-typed: `(int x) -> body`). The body can be
  any expression OR a `block`; block bodies dispatch
  through the existing `_emit_block` which uses
  same-line opening brace per the spec's same-line-brace
  bullet for lambda expressions. New companion emitter
  `_emit_inferred_parameters` handles the `(x, y)` shape
  with comma-space separator. Phase 2v emits the
  single-line form unconditionally; the universal `->`
  placement rule from spec B5 (breaking before `->`
  when the parameter list itself wraps) and the
  multi-line lambda body wrap rules land with the
  wrap-priority phase. Calibration-recon impact: the
  single `lambda_expression` fixture moved out of
  MISSING straight into MATCH. MATCH 39 → 40, MISSING
  3 → 2.
- Phase 2u wildcard + enum declarations:
  `_emit_wildcard` handles `?`, `? extends Foo`, and
  `? super Foo` with single space around the bound
  keyword per spec A4 ("Whitespace and Operator
  Spacing"). `_emit_enum_declaration` emits
  `[modifiers] enum NAME { body }` with Allman braces
  (declaration-level per the spec's "Brace Placement /
  Allman Style" section). `_emit_enum_body_members`
  splits the body into the enum-constants block and any
  non-constant members (typically a constructor and
  private fields wrapped in `enum_body_declarations`).
  Each constant emits on its own line per spec A2/B9
  with a trailing `,` separator; the last constant
  gets `;` (always emitted regardless of whether more
  members follow). One blank line separates the
  constants block from any following non-constant
  members per spec A2. `_emit_enum_constant` emits
  `[modifiers] NAME [(arguments)]` and refuses
  enum_constants with anonymous class bodies
  (`PLUS { ... }`) — that combined form lands with the
  anonymous-classes phase. Calibration-recon impact:
  MISSING dropped from 5 to 3 (the 1 wildcard and 1
  enum fixtures unblocked); they landed in DIFFER
  rather than MATCH due to fixture-vs-spec drifts
  (enum fixture pre-dates spec B9's Allman rule for
  constant bodies; tracked as calibration-phase
  followup). PARTIAL bumped by 1
  (`enum_constant with anonymous body` for the same
  fixture).
- Phase 2t type-use annotations: new `_emit_annotated_type`
  handler for the `annotated_type` node type, which the
  grammar uses to wrap `@Annotation TYPE` inline forms in
  contexts like throws clauses, generic type arguments, and
  return types. Per spec A3 ("Type-use annotations"):
  annotation sits inline immediately before the type with a
  single space between them, no own-line emission.
  Calibration-recon impact: both `annotated_type` fixtures
  unblocked from MISSING; MATCH 38 → 39, MISSING 7 → 5.
- Phase 2s interface declarations + abstract methods:
  `_emit_interface_declaration` emits
  `[modifiers] interface NAME { body }` with Allman
  braces (matching the spec's "Brace Placement / Allman
  Style" bullet for interface definitions).
  `_emit_interface_body_members` mirrors the existing
  class-body member emission. `constant_declaration`
  registered to reuse `_emit_field_declaration` since the
  grammar shapes are identical: optional modifiers, type,
  one or more variable declarators, trailing semicolon.
  `_emit_method_declaration` extended to handle the
  abstract-method case (no `body` field): emits the
  signature plus an optional throws clause followed by a
  trailing semicolon, with the indented throws-line
  carrying the `;`, no Allman braces. Refuses
  `type_parameters`, `extends_interfaces`, and `permits`
  clauses on the interface header — those land with the
  "Class Headers" wrap-priority phase. Calibration-recon
  impact: all 4 `interface_declaration` fixtures moved
  straight into MATCH; the formerly-deferred
  abstract-method case is now supported. MATCH count
  bumped 34 → 38 of 83 fixtures.
- Phase 2r constructor declarations + static initializers:
  `_emit_constructor_declaration` handles the
  `[modifiers] NAME(params) [throws] { body }` shape with
  Allman braces per the spec's "Brace Placement / Allman
  Style" section (which lists constructor definitions
  alongside method definitions). Constructor body
  (`constructor_body`) is emitted inline by the same
  loop pattern method_declaration uses — no separate
  `constructor_body` entry in the dispatch table.
  `_emit_static_initializer` emits `static\n{\n    body\n}`
  with Allman braces per spec B10 ("Static and Instance
  Initializer Blocks": declaration-level, not control
  flow, so Allman). Refuses constructors with type
  parameters (`<T> A()`) until the generic-types phase.
  Calibration-recon impact: 3 fixtures moved out of
  MISSING (2 constructor + 1 static_initializer); all 3
  landed in DIFFER rather than MATCH because of small
  formatting drifts in the fixtures or the body content
  itself. Notable finding for the calibration phase: the
  `allman_braces/14_static_initializer` fixture's
  `expected.java` shows `static {` (same-line brace)
  rather than the spec-mandated Allman shape — the fixture
  pre-dates the Phase 1 spec edits and needs updating to
  match B10. Captured as a calibration-phase followup.
- Phase 2q short-circuit Tier 1 collapse + brace synthesis
  in `if_statement`: per the spec's "Short-Circuit
  Conditionals" section, `_emit_if_statement` now collapses
  `if (x) [{] return; [}]` (any combination of input forms)
  to single-line braceless Tier 1 (`if (x) return;`) when
  the consequence is exactly one short-circuit statement
  (`return`, `continue`, `break`, `throw`) AND there is no
  `else` clause. Per the spec's "`if`/`else` pairs always
  use braces" rule, the presence of any `else` inhibits
  Tier 1. Non-block bare-statement bodies that are NOT
  short-circuit (e.g. `if (x) y = 1;`) are wrapped in
  braces via the new `_emit_branch_as_block` helper. The
  helper is also used for bare-statement `else` branches
  to ensure both arms of an if/else are braced. New
  module-level constant `_SHORT_CIRCUIT_STATEMENT_TYPES`
  enumerates the four qualifying statement types. New
  helper `_short_circuit_body(node)` returns the inner
  short-circuit statement for either Tier-1-input or
  Tier-2-input shapes (block-with-one-short-circuit). The
  Tier-1 width check ("would the single-line form exceed
  80 characters? → fall back to Tier 2") is NOT yet
  implemented; lands with the wrap-priority phase.
  Calibration-recon impact: PARTIAL dropped from 14 to 3
  (11 short-circuit fixtures unblocked); MATCH bumped
  from 21 to 34 of 83 fixtures.
- Phase 2p throws clauses on method declarations: new
  `_emit_throws` handler registered for the `throws` node;
  `_emit_method_declaration` updated to detect the optional
  throws child during its named-children scan and emit it
  between the signature line and the opening brace. Per
  the "Method and Constructor Declarations / Throws Clause"
  spec section: throws on its own line, single-indented
  (4 spaces from the method declaration). Single-line form
  only — the priority-2 "one per line, types left-aligned"
  multi-exception form lands with the wrap-priority phase.
  Calibration-recon impact: 11 previously-PARTIAL fixtures
  unlocked (`method_declaration with throws clause` was the
  single most common refusal); MATCH bumped from 16 to 21
  of 83 fixtures. The newly-emitting throws fixtures split
  between MATCH (5) and DIFFER (6, mostly due to the
  multi-exception wrapping rule).
- Phase 2o line + block comment emission: new
  `_emit_comment` handler registered for both
  `line_comment` and `block_comment` node types. Comments
  emit verbatim — single-line through `Emitter.write` and
  multi-line block comments (typical javadoc) through
  `Emitter.write_raw_lines`. When the source has the
  comment at the right column for the current
  `indent_level`, this produces correctly-indented output;
  misindented comments emit with the developer's original
  indent. Javadoc reflow (orphan-word reflow, `@tag`
  continuation alignment, inline-tag handling) per the
  "Javadoc Comments" spec section and side-comment
  attachment (end-of-line `// explanation`) are both
  deferred to subsequent phases. Phase-driven recon (Phase
  2o gate run) bumped MATCH from 12 to 16 of 83 existing
  fixtures and dropped MISSING from 31 to 12 — comments
  were the single biggest emitter gap in the fixture
  surface.
- Phase 2n annotations on declarations: refactored
  `_emit_modifiers` to handle both annotations and keyword
  modifiers per spec A3. Annotations emit on their own
  lines directly above the declaration (no blank between
  annotations or between the last annotation and the
  declaration); keyword modifiers continue to emit inline
  space-separated as before. New caller contract: the
  emitter writes its own trailing space (for keyword
  modifiers) or its own trailing newline + write_indent
  (for annotation-only modifiers), so the three callers
  (`_emit_class_declaration`, `_emit_field_declaration`,
  `_emit_method_declaration`) no longer write an
  intermediate `write(" ")` after the modifiers dispatch.
  New emitters: `_emit_marker_annotation` for `@Foo`,
  `_emit_annotation` for `@Foo(args)`,
  `_emit_annotation_argument_list` for the annotation
  argument list (comma-space-separated, single-line only
  — multi-line wrapping per spec A3's
  "Annotations with arguments" subsection lands with the
  wrap-priority phase), and `_emit_element_value_pair`
  for named-arg form `key = value`. After Phase 2n the
  formatter handles realistic annotation-bearing
  declarations like
  `@Override public String name() { return n; }` and
  `@Schedule(hour = "12") class A {}`.
- Phase 2m ternary, object creation, and generic types:
  `_emit_ternary_expression` emits Tier 1 (single-line)
  `COND ? CONSEQUENCE : ALTERNATIVE` with single space on
  each side of `?` and `:` per the "Whitespace and Operator
  Spacing" spec section. The multi-tier wrapping (Tiers 2,
  3, 4 per "Line Continuation / Ternary Operator") lands
  with the wrap-priority phase.
  `_emit_object_creation_expression` emits
  `new TYPE(ARGS)` with single space after `new`, no
  space before the argument list. Refuses anonymous class
  bodies (`new Type() { ... }`, Phase 2c8 scope) and
  explicit type-argument constructors
  (`new <T>Foo(...)`, later phase). `_emit_generic_type`
  emits `TYPE<TYPE_ARGS>` with no spaces;
  `_emit_type_arguments` emits `<TYPE, TYPE, ...>` or the
  diamond
  `<>` with comma-space separators per the spec.
  `scoped_type_identifier` (`Outer.Inner`) registered as
  `_emit_verbatim`. After Phase 2m the formatter handles
  realistic field declarations like
  `Map<String, Integer> m = new HashMap<>();` and
  `String s = x > 0 ? "pos" : "neg";`.
- Phase 2l throw / break / continue / labeled:
  `_emit_throw_statement` emits `throw EXPR;` with single
  space between keyword and expression.
  `_emit_break_statement` and `_emit_continue_statement`
  emit either bare `break;` / `continue;` or the labeled
  `break LABEL;` / `continue LABEL;` form with single
  space between keyword and label per the spec's
  "Labels and Labeled break/continue" section (C7).
  `_emit_labeled_statement` emits `LABEL:` on its own line
  and the labeled statement on the next line at the same
  indent per the same spec section.
- Phase 2k try/catch/finally with multi-catch:
  `_emit_try_statement` emits `try BODY` followed by zero-
  or-more cuddled catch clauses and an optional cuddled
  finally clause, per the "Closing Brace Rules" spec
  section's bullets for `catch` and `finally`.
  `_emit_catch_clause` emits `catch (PARAM) BODY` with the
  same-line-brace form. `_emit_catch_formal_parameter`
  emits `TYPE NAME` and refuses modifiers / annotations
  (those land with the annotation phase).
  `_emit_catch_type` handles multi-catch via space-space
  around `|` per the "Multi-catch" spec section's
  binary-operator-like spacing rule; single-line form only
  (the priority 2 / 3 two-line / one-per-line wrapping
  forms land with the wrap-priority phase).
  `_emit_finally_clause` emits `finally BODY`. After
  Phase 2k the formatter handles realistic try blocks:
  `try { x(); } catch (IOException | SQLException e) { handle(e); } finally { cleanup(); }`.
  Try-with-resources is a separate
  `try_with_resources_statement` node type in the grammar
  and refuses cleanly via the dispatcher; it lands with
  the resource-management phase.
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
  with primitive type, enhanced-for with named type, and
  refusals for multi-init and multi-update comma-separated
  forms, and (Phase 2k) try/catch/finally tests covering
  try-catch, try-finally, multi-catch-with-finally (all
  clauses cuddled), `|`-separator spacing in multi-catch,
  and the try-with-resources refusal, and (Phase 2l)
  throw/break/continue/labeled tests covering bare throw,
  unlabeled break, unlabeled continue, labeled break with
  the label on its own line, and labeled continue, and
  (Phase 2m) ternary + object-creation tests covering simple
  ternary, ternary with compound condition, object creation
  with no args / with args / with diamond generic / with
  comma-separated type args / with scoped type, plus the
  anonymous-class-body refusal, and (Phase 2n) annotation
  tests covering marker annotation on class, annotation
  with string arg, annotation with element_value_pair
  (named arg form), annotation + keyword modifiers,
  multiple annotations on class, annotation on method,
  multiple annotations on method, annotation on field, and
  annotation-only-no-keyword form, and (Phase 2o) comment
  tests covering single-line block comment above a field /
  above a method, line comment inside a method body, and
  multi-line block comment with interior indent preserved,
  (Phase 2p) throws-clause tests covering single
  exception, multi-exception single-line, and modifiers +
  throws + body combinations, and (Phase 2q) short-circuit
  Tier 1 tests covering braceless-non-short-circuit
  wrapping, braceless-short-circuit-stays-Tier-1,
  braced-short-circuit-collapses-to-Tier-1, and
  if/else-inhibits-Tier-1, and (Phase 2r) constructor +
  static-initializer tests covering no-args constructor,
  args + body, throws, Allman static initializer with
  one statement, and static initializer with multiple
  statements, and (Phase 2s) interface tests covering
  empty interface, interface with abstract method,
  interface with constant + method, interface with
  default method, and interface with abstract method +
  throws clause, and (Phase 2t) type-use annotation tests
  covering single annotated_type in throws and multi
  annotated_types in throws, and (Phase 2u) wildcard +
  enum tests covering unbounded wildcard, extends-bound
  wildcard, super-bound wildcard, simple enum constants,
  enum constants with arguments, and enum with
  constructor + field after constants, and (Phase 2v)
  lambda tests covering zero args, single inferred-type
  param, multi inferred-type params, explicit-typed
  param, and lambda with block body (185 tests total).

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
