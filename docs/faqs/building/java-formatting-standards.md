# Java Formatting Standards

## Overview

All non-generated Java source files must conform to the formatting rules defined in `.java-coding-standards/docs/java-coding-standards.md`. Consult it before writing or reformatting Java code.

## When generating new code

**Apply these standards from the start.** Do not write Java code in a free-form way and then reformat — generate it already compliant:

- Pick brace placement based on the construct (Allman for type/method/constructor definitions; same-line for control flow and lambdas).
- Wrap long lines at `+`, `&&`, `||`, `?`, `:`, `.` with the operator starting the continuation line.
- Use the parameter placement priority (single line → paren-aligned → next-line double-indented).
- Reflow javadoc to fill near 80 chars; never leave 1-3 orphan words on a continuation.
- Single-line `if` is **only** for short-circuit control flow: body must be `return`/`continue`/`break`/`throw`, the `if` must be standalone (no `else`), and the whole thing must fit on one line. `if (x == null) return null;` is fine.
- Assignments and method calls always get braces, even when they fit. `if (env != null) env.destroy();` and `if (moduleName == null) moduleName = "...";` are wrong — brace them.
- For `if`/`else` pairs, always brace both branches regardless of body type or fit.
- Put `throws` on its own line, single-indented from the method.

After generation, run `mvn -Pcheckstyle validate` to confirm compliance. The bulk formatter described below is an aid for legacy code or batch updates — it is not a substitute for writing compliant code on the first pass.

## Key Rules

- **80-character line limit** — enforced by checkstyle via `-Pcheckstyle`
- **Allman braces** for class, interface, enum, record, method, and constructor definitions
- **Same-line braces** for control flow: if/else, for, while, do, try/catch/finally, switch, synchronized, lambdas, array initializers
- **Allman braces** for static / instance initializer blocks (spec B10)
- **Continuation indentation**: +4 per wrap level (cumulating to 8 spaces of displacement for the typical double-wrap; see the full standards doc for the per-level rule)
- **Operators on continuation lines**: break BEFORE `+`, `&&`, `||`, `?`, `:`, `.`
- **CSOFF/CSON**: only for deliberately aligned multi-line output (aligned labels, SQL DDL, column-formatted diagnostics) — NOT a general escape hatch
- **Javadoc**: reflow prose and @tag descriptions to fill lines near 80 chars; don't leave orphaned short words
- **Switch case labels**: indented +4 from the block's left anchor (the column where the closing `}` aligns)
- **Single-line `if`** is reserved for short-circuit control flow only — body must be `return`/`continue`/`break`/`throw`, no `else`, and the whole thing must fit on one line. Assignments and method calls always use braces, even when they fit. `if`/`else` pairs always brace both branches.

## Checkstyle Configuration

The standards repo ships two checkstyle config files; consumer projects reference them via the submodule path in `pom.xml`'s `maven-checkstyle-plugin` configuration:

- `senzing-checkstyle.xml` — enforces LineLength (80), RightCurly, NeedBraces, UnusedImports, Indentation, OperatorWrap, FileTabCharacter, CSOFF/CSON suppression.
- `senzing-checkstyle-suppressions.xml` — globally suppresses checks that are not yet enforced (Indentation, NoWhitespaceAfter, FinalParameters, HiddenField, ParameterNumber, MagicNumber, AvoidNestedBlocks, MethodLength, FileLength, AvoidStarImport, RegexpSingleline).

Project-specific suppressions (e.g. for auto-generated files) layer in via a project-local `checkstyle-suppressions-local.xml` next to the project's `pom.xml` — passed to checkstyle alongside the shared base via the multi-value `<suppressionsLocation>` syntax.

## Formatter architecture (0.4.0+)

`tooling/scripts/format_file.py` is the single end-user entry point. It's a thin wrapper that invokes the canonical formatter at `format_java.py` **in-process** — no JVM, no subprocess pipeline. Same input → same output regardless of caller (VS Code save, Claude Code edit hook, CLI, CI pre-commit).

`format_java.py` is a pure-Python AST-based formatter built on `tree-sitter-java`. For each file it:

1. **Parses** the source bytes to a tree-sitter CST.
2. **Walks** the CST top-down, dispatching each node type to its registered emitter function via the `_NODE_EMITTERS` table.
3. **Emits** spec-compliant text via an output buffer (`Emitter`) that tracks column / indent level and strips trailing whitespace per spec A5.
4. **Wraps** when the natural single-line form would overflow 80 chars — the wrap-priority engine threads through every wrappable construct (see below).

### Wrap-priority engine (0.4.0)

Every wrappable construct emits through a single `try_priorities` cascade. A construct declares an ordered list of **candidate shapes** (single-line, paren-aligned, next-line single-indent, etc.); the engine commits the first candidate whose rendered output fits within the line budget. Candidates that overflow are rolled back via `Emitter.snapshot()` / `restore()` so partial output never leaks. When every candidate overflows, the last one is left committed and the spec C1 "emit + warn" rule applies.

The line budget is `_MAX_LINE` (80) minus a **`tail_reserve`** that accounts for trailing tokens the candidate can't see — the `;` after an expression statement, **the `;` after an explicit-constructor invocation (`this(...)` / `super(...)`)**, **the `;` after a `throw` / `return` statement**, the `)` closing an enclosing parenthesized expression, the `) {` after an `if` / `while` / `for` condition, the trailing `.method(args)` after a chain's receiver, the trailing `.field` after a method-chain receiver, and so on. Each enclosing construct pushes `tail_reserve` before emitting its inner expression and restores it afterwards. The composition is additive: an `if (binary) {` reserves `2 + 1 = 3` chars, so the binary expression's wrap engine treats the effective max as 77.

**Gotcha for future maintainers**: in tree-sitter-java, `explicit_constructor_invocation`, `throw_statement`, `return_statement`, and `expression_statement` are sibling grammar nodes — they all own a trailing `;` but each is a separate AST type. A change to "how the single-line estimator reserves for a trailing `;`" must touch every one of these; missing any of them is a latent off-by-one where a single-line candidate at exactly column 80 looks acceptable but renders at column 81 once the `;` is appended. The fixture `tooling/scripts/tests/fixtures/explicit_constructor_invocation/01_this_args_reserve_trailing_semicolon/` locks the explicit-constructor case; analogous fixtures exist for `throw` / `return` / `expression_statement`.

The constructs handled by the wrap engine include:

- Method declaration signatures (spec B11 type-parameter wrap; non-generic signature paren-align fallback).
- Method-call arguments (P1 single-line / P2 two-line paren-aligned comma-packed / P3 paren-aligned one-per-line / P4 next-line single-indent).
- Method-chain wrap (P1 single / P2 vertical-aligned dots / P3 continuation-indent fallback).
- Ternary wrap (T1 single / T2 break-before-`?` / T3 break-before-both).
- Binary-expression wrap (P1 / P2 break-before-leftmost-op / P3 break-before-every-op).
- Class-header `extends` / `implements` wrap (B1) — combined-continuation form when type parameters allow, separate-line form when they don't.
- Variable-declarator break-at-`=`.
- Try-with-resources resource break-at-`=` (spec B8 preference order).
- `if` / `while` / `for` condition wrap (binary-operator break inside the condition; for-header paren-aligned split at `;` separators when no binary operator is available).
- Throws-clause column-aligned wrap.
- Line-comment reflow (greedy fill at the indent column; directive exemptions for `CSOFF` / `CSON` / `CHECKSTYLE` / `SUPPRESS` / `@`-prefixed tags; URL exemption).
- Conditional source-preserve for argument lists — when the developer authored a multi-line layout (logged messages broken at readable boundaries, for example), the layout is preserved when its first line still fits at the new emission column. CSOFF/CSON regions force source-preserve unconditionally.
- Text blocks at any indent level — closing `"""` lands at +4 from the introducing statement; content lines shift by the same delta so the rendered string is byte-for-byte unchanged.

Unknown node types raise `NotImplementedError` with a clear "not yet supported" diagnostic; the dispatcher never silently passes source text through. The deliberate out-of-scope construct for 0.4.0 is `module_declaration` (no consumer project uses Java modules yet).

The grammar version (`tree-sitter-java==0.23.5`) and the Python binding (`tree-sitter==0.25.2`) are pinned in `tooling/scripts/requirements.txt`. Bumps go through a calibration re-run against the fixture pairs under `tooling/scripts/tests/fixtures/`.

`_PARSER` is wrapped in `threading.local`, so the formatter is safe to use from parallel pytest runs, batch formatters, and in-process services.

## VSCode integration

- `.vscode/settings.json` — `[java].editor.formatOnSave: false` (we do NOT use redhat.java's built-in format-on-save). `emeraldwalk.runonsave` instead invokes `format_file.py` on Java save.
- Why not let redhat.java do format-on-save? The redhat.java extension doesn't implement the Senzing spec — running it on save would produce output the canonical formatter then has to rewrite. One invocation via `emeraldwalk.runonsave` is cleaner.

## Running the formatter

### First-time dependency install

The formatter imports `tree-sitter` and `tree-sitter-java` — these
must be installed against the `python3` that the Claude Code
`PostToolUse` hook and VSCode `emeraldwalk.runonsave` invoke (the
system `python3`, not any project virtualenv). One-time per machine:

```bash
# macOS Homebrew Python (PEP 668):
python3 -m pip install --break-system-packages --user \
  -r .java-coding-standards/tooling/scripts/requirements.txt

# Linux / any non-PEP-668 python3:
pip install -r .java-coding-standards/tooling/scripts/requirements.txt
```

Symptoms of missing deps: `ModuleNotFoundError: No module named 'tree_sitter_java'` from the hook on every Java edit; VSCode format-on-save silently does nothing. Re-run the install after any submodule bump that touches `requirements.txt`.

### Invocations

End-to-end:

```bash
# Bulk pass over the project's source roots (defaults: src/main/java,
# src/test/java, src/demo/java when present).
python3 .java-coding-standards/tooling/scripts/format_file.py

# Format a specific directory tree.
python3 .java-coding-standards/tooling/scripts/format_file.py src/main/java

# Format a single file in place.
python3 .java-coding-standards/tooling/scripts/format_file.py path/to/File.java
```

Output: one summary line — `Formatter: N files processed, M modified.` Exit code 0 on success (regardless of how many files were modified), 1 on parse errors, 2 on missing-file or import-error conditions.

For inspecting a single file's formatted output without rewriting it:

```bash
# Print the formatted output to stdout.
python3 .java-coding-standards/tooling/scripts/format_java.py --format path/to/File.java

# Exit 1 if the file would be reformatted, 0 if compliant.
python3 .java-coding-standards/tooling/scripts/format_java.py --format path/to/File.java --check
```

## Upgrading from 0.4.x

The 0.4.2 release adds three generalizable patterns to the wrap engine, and 0.4.3 generalizes them further. Consumers don't need to know about them to use the formatter, but anyone maintaining `format_java.py` should:

- **Binary-expression precedence-aware left-spine walk** — `_emit_binary_expression` flattens a multi-operator chain by descending the left spine, but only through children whose operator shares the root's precedence group. A new module-level `_BINARY_OP_PRECEDENCE` table encodes Java operator precedence (JLS § 15). Without the precedence guard, `a == null || b || c` would flatten into a 4-element chain and break at the leftmost `==`, stranding `== null` on a continuation line instead of breaking at the lowest-precedence operator (`||`).

- **P1 newline-rejection gate** — for any wrap-priority site whose P1 candidate claims "all on one line", a width-only fit check is insufficient. A nested emit (an inner parenthesized binary that wraps, an arg list that wraps to P4, a chain whose head is itself another chain) can satisfy the width check by producing multi-line output that happens to fit ≤80 per line — leaving the outer construct's structure broken (operators stranded mid-line). The fix is to track `emitter.line_count` before and after the P1 emit and reject if any newlines were introduced. Used in `_emit_binary_expression` (rejects any newline) and `_emit_method_chain_wrapped` (rejects per-segment, because the head is allowed to wrap legitimately as another chain).

- **`_attach_trailing_side_comments` shared helper** — spec C6 "End-of-line side comments" attaches a `line_comment` (or single-row `block_comment`) to the preceding statement's emitted line with two spaces of separation, instead of detaching it onto its own line. The helper centralizes the same-row attachment rule for `_emit_indented_member_list` (method / constructor / static-initializer bodies, switch-block cases) and `_emit_block` (control-flow blocks). Multi-row block comments are intentionally not attached (the attachment loop's blank-line tracking assumes the comment ends on its own start row).

### Additional patterns in 0.4.3

- **`_arg_list_takes_source_preserve_path` shared predicate** — the arg-list emitter and the method-chain P1 discriminator now consult the same column-sensitive check (`_node_spans_multiple_rows(args)` AND `first_line_fits(args_emit_column)` OR has-comment OR in-CSOFF). The chain discriminator can't just guess from source-row count alone, because the arg-list emitter falls through to the wrap engine when the source's first line doesn't fit at the new emission column — and that wrap-engine output strands subsequent chain segments. Sharing the predicate is what keeps the two sites in agreement. Generalization of the same "outer construct must predict what inner construct will actually do" principle the 0.4.2 P1 newline-rejection gate established.

- **Chain P1's legitimate-multi-line cap is at total-segments ≤ 2** — even when the source-preserve predicate fires for a segment's args, chain P1 only accepts when the chain has at most TWO segments total. The cap reflects the design preference "break on method chaining (greedily) before breaking on parameter names for a method in the chain": a 3+ segment chain whose middle segment has multi-line args (e.g. `Builder.builder().setReader(r).setFormat(\n  fmt).get()`) reads better as a dot-aligned wrap (chain P2) than as "chain-on-one-line with mid-args wrap" (which piles the trailing `.get()` onto the continuation line that starts with the closing `)`). The 2-segment threshold matches `cls.getResource(\n  arg).toString()` (Bug 1's original case) while rejecting longer chains. Replaces the prior trailing-segment cap of ≤1, which over-accepted at 4-segment chains.

- **Width-based opt-out in `_arg_list_takes_source_preserve_path`** — before the `first_line_fits` gate, the predicate now estimates whether the full args would render single-line at the current emission column. The estimator (`_arg_list_single_line_estimate`) walks the arg-list AST to identify `string_literal` / `character_literal` / `line_comment` / `block_comment` regions, preserves their text verbatim, and collapses whitespace + normalizes comma-spacing only outside those regions. If the estimate fits, source-preservation is declined so the wrap engine's P1 candidate produces the canonical single-line form. The AST walk is what prevents the foot-gun where a comma with no following space inside a string literal (`foo("name=A,value=B")`) is mistakenly comma-normalized — over-estimating the width by 1 per such comma and incorrectly retaining source-preservation. The opt-out is skipped when any arg itself spans multiple rows (text block, lambda body, nested multi-row expression) — single-line is unlikely to fit then, so source-preservation remains the safer path. Reordered the function so unconditional preservation triggers (comments, CSOFF) fire first; the width opt-out applies only when neither holds.

- **Spec C6 paren-aligned operator continuation** (binary + ternary, added in 0.4.3) — when an expression is wrapped in grouping parens, operator continuation aligns under the column immediately after the `(`. `_emit_parenthesized_expression` sets `emitter.paren_align_col` for grouping parens only — control-flow required parens (`if (cond)`, `while (cond)`, etc.) are excluded via `_PAREN_NOT_GROUPING_PARENT_TYPES`. `_emit_binary_expression` and `_emit_ternary_expression` each add a paren-aligned wrap candidate tried before standard P2/T2.

- **Paren-alignment yields to source-preservation on inversion** (`_emit_parenthesized_expression` + `_inner_would_invert_paren_align`) — paren-alignment is silently declined for a grouping paren when the inner expression contains an `argument_list` that would source-preserve at a column LESS than the proposed paren-align column. The detection walks the inner subtree, consults `_arg_list_takes_source_preserve_path` to confirm each candidate arg list will actually source-preserve (not collapse via Bug 4's width opt-out), and only then compares the arg list's continuation columns against the proposed paren-align column. When an inversion is detected, the level reverts to the cumulative `+4` continuation (pre-Bug-3 behavior) so the source-preserved inner content nests correctly inside the outer operator chain. The fix is column-conservative — uses the OUTER proposed column as a lower bound when calling the predicate, which gives a safe under-detection bias (false negatives reduce to the pre-0.4.3 status quo for those specific nested cases; false positives never occur).

- **Formatter advisory channel for un-fixable source-preserve quirks** (`FormatterWarning` + `Emitter.warnings` + `format_source(source, warnings_out=...)` parameter, 0.4.3+) — there's a category of layout quirk the formatter genuinely cannot fix on its own. The headline case: a long error message wrapped in `throw new IOException("…long literal…" + variable)` where the author manually placed the literal at a low column (e.g. col 14) to make it fit within 80 chars. Each subsequent reformat sees the multi-row arg list and source-preserves it verbatim, even when the surrounding context (`throw` keyword, enclosing `if` bodies) has shifted to a deeper indent. The result is a 80-char-compliant but visually inverted layout — the contained literal sits LESS indented than the statement that owns it. The only way to fix this is to split the literal into smaller concatenated chunks, which is a code change and out of scope for an AST-preserving formatter. The formatter now collects these as `FormatterWarning` records during emit and the CLIs print them to stderr in `path:line:col: WARNING: …` format so developers know which spots warrant manual cleanup. The advisory is informational only — `mvn -Pcheckstyle validate` still passes because the source-preserved layout fits 80; the warning is the formatter's way of saying "I made this work but the result is a little ugly because of how the original was authored."

## Upgrading from 0.3.x

The 0.4.0 release added the wrap-priority engine with `tail_reserve` propagation. The CLI surface is unchanged — same `format_file.py` invocation, same exit codes. The only adopter-visible effect is that the formatter now produces spec-compliant output for cases the 0.3.x cascade left as LineLength violations: long method chains, long ternaries, long conditions, line comments past 80, text blocks in indented contexts, and a few more (see CHANGELOG `[0.4.0]`).

- A first run on a consumer that's been on 0.3.x will typically produce a moderate reformat as the new wrap engine takes over from the 0.3.x source-preserve. Commit that as a "format compliance" follow-up; the second run is idempotent.
- Annotation type declarations (`@interface ...`) and multi-init / multi-update for-statements (`for (i = 0, j = 0; ...; i++, j++)`) now emit instead of refusing — relevant if your project uses either.

## Upgrading from 0.2.x

The 0.3.0 release replaced the previous JDT + six-script pipeline with the single in-process tree-sitter formatter. If your project is upgrading from 0.2.x:

- `format_file.py` keeps the same CLI surface (positional paths, `--src-dirs`, `--exclude`, `--exclude-from`), so VSCode tasks, Claude Code hooks, and pre-commit configs continue to work.
- A consumer's first post-upgrade run typically produces a sizeable one-time reformat because the new formatter is spec-compliant by construction. Commit that diff as a "format compliance" follow-up; a second run reports zero modifications (the idempotency gate).
- Consumers should delete legacy artifacts after upgrading: `.claude/scripts/fix_*.py`, `.vscode/java-formatter.xml`, and any cached `~/.cache/senzing-jdt-formatter/` JDT JAR. The standards repo no longer ships any of those.
- A JDK is no longer required to run the formatter. Only Python 3.10+ plus the runtime deps in `tooling/scripts/requirements.txt`.

## Full Reference

See `.java-coding-standards/docs/java-coding-standards.md` for the complete standards document, including method declaration priority rules, ternary operator tiers, short-circuit conditional formatting, and the per-construct spec sections.
