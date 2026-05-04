# Changelog

All notable changes to this project will be documented in this file.

The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
[markdownlint](https://dlaa.me/markdownlint/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
