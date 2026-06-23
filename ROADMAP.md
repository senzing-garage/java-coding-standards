# Roadmap

Forward-looking work items for `java-coding-standards`. Items
here are PLANNED but not yet committed — distinct from
`CHANGELOG.md`'s `[Unreleased]` section, which is reserved for
committed-but-unreleased changes per the Keep a Changelog
convention.

## 0.5.0 — wrap-engine extensions and source-preserve refactor

**Status:** scoped during a planning session after 0.4.3
shipped. Five items targeted for 0.5.0; coordinated batch
because the underlying questions overlap (wrap-engine
candidate set, spec C6 scope, source-preserve column policy).

### Items in 0.5.0

<!-- prettier-ignore -->
| # | Item | Risk | Spec change? |
|---|---|---|---|
| 1 | Control-flow paren-alignment (extend spec C6) | Low | Yes |
| 2a | Label/value-aware binary `+` chain wrap | Low | Yes |
| 2b | Same-method greedy method-chain wrap | Medium | Yes |
| 3 | Greedy-P2 binary expression wrap | Low | Minor (new candidate) |
| 4 | Context-aware source-preservation | High | Yes |

### Phasing

**Phase 1 — Item 4 spike (throwaway).** Empirical
comparison of the two candidate implementation paths for
item 4 (column-remapping vs partial semantic emission).
Run each on `senzing-commons-java`, measure reformat
surface and LineLength regressions. Don't commit — the
result picks the option for Phase 5.

**Phase 2 — Item 1 (control-flow paren-align).** Lowest
risk, additive. Trial-run on consumer to gauge visual
density before tagging.

**Phase 3 — Items 2a + 3.** Same wrap engine
(`_emit_binary_expression`), shared cascade positioning.
Implement together.

**Phase 4 — Item 2b spike + implementation.** Greedy
method-chain has medium reformat surface. Spike on a
throwaway branch first to gauge impact (same pattern as
Phase 1); commit if the diff looks acceptable.

**Phase 5 — Item 4 actual implementation.** Uses the
spike-winner option from Phase 1. Last because dependence
on items 2a/2b/3 is now clear and the IOException
long-literal back-off needs careful fixture coverage.

**Phase 6 — Bulk adoption + tag.** Reformat
`senzing-commons-java` (and ideally `sz-sdk-java` as a
second adopter), verify `mvn -Pcheckstyle validate` BUILD
SUCCESS, idempotency holds. Tag 0.5.0.

### Why phase 1 (item 4 spike) comes first

Item 4's option 2 (partial semantic emission) would cause
`_emit_binary_expression`, `_emit_method_chain_wrapped`,
and `_emit_block` to fire on inputs they don't see in
0.4.3 (inside source-preserved arg lists). Items 2a, 2b,
and 3 would behave differently in those new contexts. If
we land 2a/2b/3 first under today's assumptions and then
land option 2, the interaction surprises are hard to
unwind. If option 1 (column-remapping) wins the spike,
this concern evaporates and items can land in any order.

### Why phase 4 has a spike too

Item 2b touches every `.method().method()` chain with the
same method name in adopter code. That's potentially
hundreds of files. A throwaway preview before committing
the implementation lets us see the diff quality and adjust
the gating heuristic (currently "all segments call the
same method name") if it over- or under-triggers.

### Spec text

Each implementation PR carries its own spec-text update to
`docs/java-coding-standards.md` (no separate spec-first
PR). The user is the primary adopter during 0.5.0
development; pre-circulating spec for external review
isn't necessary.

### Cascade ordering reference

The combined `_emit_binary_expression` cascade after
0.5.0:

1. P1 (single line)
2. **2a** `emit_pair_aligned` (label/value pattern matches;
   uses `paren_align_col` if set, else +4 indent)
3. `emit_paren_aligned` (0.4.3, only when grouping paren in
   scope and 2a didn't apply)
4. P2 (break-at-leftmost-only, rest on one continuation line)
5. **3** `emit_greedy` (pack as many operands per line as fit)
6. P3 (every operand on its own line)

The `_emit_method_chain_wrapped` cascade after 0.5.0:

1. P1 (single line)
2. **2b** `emit_p2_greedy` (only when all segments call the
   same method name; pack as many segments per line as fit)
3. P2 (dot-aligned, one segment per line)
4. P3 (continuation-indent, one segment per line)

---

## Original 0.5.0 backlog notes (preserved for reference)

The items below are the original coordinated **gaps /
ambiguous-cases list** captured at the end of 0.4.3
review. The scoping decisions above (item 2 splitting
into 2a/2b, retention of item 3, etc.) refine these into
the final 0.5.0 plan.

### Label/value-aware string concatenation wrap candidate

New `emit_p2_pair_aligned` candidate in
`_emit_binary_expression`. Spec extension: when a binary `+`
chain alternates between `string_literal` operands and
non-string operands AND each label literal begins with a
delimiter character (` `, `,`, `;`, `]`, `)`, `}`, `|`, `:`),
break before each label so each line carries one label/value
pair aligned at the chain's continuation column. Generic
example (the classic `toString()` builder pattern):

```java
// current 0.4.3 output (P3 — break before every `+`):
return ("{ option=[ "
        + this.getOption()
        + " ], processedValue=[ "
        + this.getProcessedValue()
        + " ], source=[ "
        + this.getSource()
        + " ] }");

// proposed 0.4.4 output (pair-aligned):
return ("{ option=[ " + this.getOption()
        + " ], processedValue=[ " + this.getProcessedValue()
        + " ], source=[ " + this.getSource()
        + " ] }");
```

Detection is purely structural (operand types from AST) plus
a lexical delimiter-prefix check on the string literals.
Falls back to break-at-every-operator (P3) when the
alternation breaks (two consecutive strings or two
consecutive values) or when any pair would overflow 80 chars.
Won't fire on arithmetic chains like `a + b + c + d` because
the operand types don't alternate.

Requires: spec section in `docs/java-coding-standards.md`
("Label/value-aware string concatenation"), wrap candidate
implementation, ≥2 fixtures (engagement case +
alternation-broken fall-back), consumer re-verification.

### Greedy-P2 wrap candidate for binary expressions

Also in `_emit_binary_expression`. Generic fallback for
binary chains that don't match the label/value pattern but
where P3's one-per-operator break is wider than necessary.
Tries to fit as many operands as possible on each
continuation line before breaking. Complements the
label/value-aware candidate above by handling the
non-alternating cases. Lower priority — only worth
implementing if real cases surface in consumer adoption that
P3 handles poorly.

### Context-aware source-preservation for multi-row arg bodies

`_emit_argument_list` source-preserve path. Currently the
source-preserve path emits an arg list's bytes verbatim via
`write_raw_lines` — including the bodies of any contained
multi-row constructs (lambda blocks, multi-row chain
expressions, multi-row binary concatenations). The
continuation columns in those bodies are whatever the source
originally chose, often inherited from an earlier surrounding
context that has since shifted to a different indent. Two
visible flavors of the same underlying issue:

**(a) Lambda body inherited from prior context.** Example:

```java
// current 0.4.3 output — body at the source's original col:
                collection.entrySet().forEach(entry -> {
          String key = entry.getKey();
          if (key != null) {
            key = key.trim().toUpperCase();
          }
          …
        });

// proposed — body re-indented per current indent_level:
                collection.entrySet().forEach(entry -> {
                    String key = entry.getKey();
                    if (key != null) {
                        key = key.trim().toUpperCase();
                    }
                    …
                });
```

**(b) Non-lambda multi-row arg inherited from prior context.**
E.g. a chain expression arg whose continuation column was set
by the original author. Generic example:

```java
// current 0.4.3 — continuation at source's original col 16:
            if (!canonicalTarget.toPath().startsWith(
                canonicalTargetDir.toPath()))
            {

// proposed — continuation at current_indent_col + 4 (col 20):
            if (!canonicalTarget.toPath().startsWith(
                    canonicalTargetDir.toPath()))
            {
```

The 0.4.3 `FormatterWarning` advisory channel surfaces flavor
(a) (lambda body below indent), so developers see the issue
in CI logs. Flavor (b) is silent today — the continuation
column happens to be ≥ `indent_level * 4`, so the advisory
doesn't fire — but the visual quirk is the same family.

The fix path covers both flavors: refactor the
source-preserve emit to either (1) shift continuation columns
by a computed delta relative to the new emission context
(column-remapping source-preserve), or (2) switch to semantic
emission for multi-row inner constructs while keeping the
outer parens verbatim (partial-preserve). Option (1)
preserves the developer's intra-arg break choices but
rewrites the absolute column; option (2) lets `_emit_block` /
chain / binary engines re-emit cleanly but may pick different
break points than the original. Pick by trial — see how the
consumer reformat reads under each — before committing to one
path.

Constraints: must not regress the `IOException("…long
literal…" + var)` case where a long string literal at a low
column is THE thing that fits in 80 chars. Re-indenting
upward there would push the literal past 80 (verified
empirically during 0.4.3 — the naïve "decline source-preserve
when continuation < indent" caused ~10 LineLength failures
across 5 consumer files). String literals cannot be
auto-split, so the fix must back off in that case (likely via
a width check: only re-indent when the re-indented layout
actually fits 80).

Requires: source-preserve path refactor, fixture coverage for
lambda body / non-lambda multi-row arg / long-literal
fall-back, and consumer re-verification across adopters.

### Extend spec C6 paren-alignment to control-flow required parens

`_emit_parenthesized_expression` + `_PAREN_NOT_GROUPING_PARENT_TYPES`.
0.4.3's paren-alignment applies only to grouping parens
(developer-authored `(...)` around an expression for
emphasis); the control-flow required parens — `if (cond)`,
`while (cond)`, `for (...)`, `catch (...)`, `synchronized
(...)`, `switch (...)` — use the standard cumulative `+4`
continuation indent for their binary-operator wraps. Generic
example:

```java
// current 0.4.3 (cumulative +4 continuation):
} else if (owner.fileParts.size()
    > this.currentFileIndex)
{
    …
}

// proposed (paren-aligned under `(`):
} else if (owner.fileParts.size()
           > this.currentFileIndex)
{
    …
}
```

The visual case for extending: the continuation operator
lines up directly under the column the condition opens at,
making the wrap point unambiguous at a glance. The case
against: deeper indents per level (more horizontal space
consumed in nested control flow), and it breaks a convention
many adopters already rely on.

Fallback behavior: when paren-alignment would overflow on the
second line (long condition relative to deep indent), the
wrap engine should fall back to the standard `+4` cumulative
continuation. The existing `try_priorities` cascade handles
this naturally — paren-aligned candidate emits speculatively,
engine checks width, accepts or rolls back and tries the +4
candidate.

Tagged as a candidate for **0.4.4 or 0.5.0** depending on how
invasive the consumer-side reformat ends up being. Worth a
trial run on `senzing-commons-java` + a second adopter to
gauge the visual impact before committing to a
semantic-version bump.
