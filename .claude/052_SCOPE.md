# 0.5.2 release scope (planning)

Bug-fix release addressing formatter-output alignment defects
surfaced during the 0.5.1 adoption pass in `senzing-commons-
java` (PR #228 CI review on consumer commit `91ba830` /
`2d0a260`). All are formatter-emitter shape problems, not
spec changes. 0.5.2 continues the 0.5.x architecture; no
spec edits are anticipated.

The source of these findings is PR #228's automated Claude
code-review comments. The consumer-side responses to that
review batched the bugs as "formatter output alignment
issues, standards-repo concern for 0.5.2" — this doc is the
durable capture.

All file paths in this doc are relative to
`/Users/barry/dev/senzing/senzing-commons-java/` for the
repros; the fixes land in `format_java.py` in this repo.

---

## A. `super(arg, arg, innerCall(arg,` continuation alignment

**Symptom:** When a `super(...)` (or any multi-arg call)
has an INNER multi-arg call as one of its arguments and
that inner call wraps multi-row, the inner call's
continuation arguments don't paren-align under the inner
`(` — they sit at a column dictated by an outer
relationship.

**Repro** — `src/main/java/com/senzing/cmdline/MissingDependenciesException.java:33-37`:

```java
        super(source, option, specifier, buildErrorMessage(source,
                            option,
                            option.getDependencies(),
                            specifier,
                            specifiedOptions));
```

The first arg of `buildErrorMessage` is `source` at column
58 (after the `(`). Per spec C6, the continuation arguments
should paren-align under column 58. Instead they land at
column 28 — neither paren-aligned to `buildErrorMessage(`
NOR at a sensible block-indent-derived position.

**Expected (paren-aligned under `buildErrorMessage(`):**

```java
        super(source, option, specifier, buildErrorMessage(source,
                                                           option,
                                                           option.getDependencies(),
                                                           specifier,
                                                           specifiedOptions));
```

But that would push the continuation arguments past column
80 in this case. The 0.5.1 wrap engine's fallback to
`block + 4 = 12` for the continuation column would be:

```java
        super(source, option, specifier, buildErrorMessage(
            source,
            option,
            option.getDependencies(),
            specifier,
            specifiedOptions));
```

The current 0.5.1 output (column 28) sits between these
two reference shapes and doesn't satisfy either.

**Likely root cause:** the multi-arg-call source-preserve
path in `_emit_argument_list` is preserving the
developer's original continuation column verbatim
(probably from a pre-0.4.x format pass that authored the
shape) without re-anchoring. When the outer call's emit
column shifts (e.g. because `super(` puts the inner
`buildErrorMessage(` at a different column than the source
had it), the inner continuation column stays glued to its
old absolute value.

**Fix candidate:** when source-preserving an inner arg
list whose first source-row column differs from the
emitter's current column, re-anchor the continuation
column to `inner_paren_col + 4` or `inner_paren_col`
(whichever the spec C6 single-arg-binary-call extension
generalizes to multi-arg).

**Test fixture to add:** `arg_list_wrap/08_outer_call_inner_multi_arg_call_continuation`
with two-level nested multi-arg calls; expected shape is
paren-aligned at the inner `(` if it fits, else
`emit_p4_multi_arg` (newline + block+4 indent) shape.

---

## B. `("dist".equals(installDir.getCanonicalFile().getName()))` continuation

**Symptom:** A single-arg method call whose only argument
is itself a multi-segment method-chain wraps with the chain
continuation at an unexpected column.

**Repro** — `src/main/java/com/senzing/util/SzInstallLocations.java:484-485`:

```java
            result.devBuild = ("dist".equals(
                                   installDir.getCanonicalFile().getName()));
```

The inner method call `equals(...)` has its only argument
on a continuation line at column 36. The arg is the full
chain `installDir.getCanonicalFile().getName()`. The
spec C6 single-arg-call extension would paren-align under
the column after `equals(` (column 31), not column 36.

Alternative interpretation: the inner argument is itself
a method-chain, and per spec the chain should wrap at the
chain's dot-aligned column, not at the call paren's
column. In this case the chain is on a single line and
doesn't need to wrap at all — the wrap is forced by the
call's overflow.

**Expected (paren-aligned under `equals(`):**

```java
            result.devBuild = ("dist".equals(
                               installDir.getCanonicalFile().getName()));
```

Or alternatively, accepting that the inner chain doesn't
fit, switch to `emit_p4_single_arg`:

```java
            result.devBuild = ("dist".equals(
                installDir.getCanonicalFile().getName()));
```

(block + 4 indent for the arg).

**Likely root cause:** the source-preserve path inherits
a stale continuation column from the developer-authored
source, similar to A. The wrap engine's
`_emit_argument_list` single-arg P4 path is supposed to
re-anchor at `block + 4`, but the source-preserve gate
fires first and locks in the stale column.

**Fix candidate:** unify with A — re-anchor source-
preserved continuation columns to a deterministic
spec-defined target when they don't match the canonical
position.

**Test fixture to add:** `arg_list_wrap/09_single_arg_method_chain_wrap`
with a single-arg call whose arg is a multi-segment
chain that overflows when packed inline.

---

## C. `assertEquals(arg1, "long literal " + var);` reformat pushed lines past 80

**Symptom:** The 0.5.1 P3 item-8 invariant for arg lists
introduced a "force break before next arg when prev arg
wrapped multi-row" rule. In some test-source patterns the
break lands the trailing args at a continuation column
that pushes the resulting line past 80 chars — a wrap
shape that's WORSE than the original.

**Repro** — `src/test/java/com/senzing/sql/ConnectionPoolTest.java:111-112`:

```java
                        throw new IllegalStateException(
                            "Thread connection does not match specified connection.");
```

Line 112 is 86 chars. The single-string arg of
`IllegalStateException(...)` lands at column 28
(block + 4) which puts the 57-char string content at
columns 28-84.

**Same pattern** at `:282-283`:

```java
                        throw new IllegalStateException(
                            "Failed to obtain connection in allotted time.  " + info);
```

Line 283 is 86 chars.

**Expected** — at minimum, a `FormatterWarning` advisory
should fire so the developer knows to split the literal.
Currently the formatter silently emits the overflow with
no warning, because the binary-cascade C1 emit+warn fires
only at the BINARY wrap site, not at the arg-list wrap
site that committed to the overflowing shape.

**Likely root cause:** the arg-list wrap engine commits
to `emit_p4_single_arg` (newline + block+4 indent +
single-arg-emit) without checking whether the emitted
single-arg line itself overflows. The 0.5.1 P4
overflow-advisory wiring in `_emit_argument_list` may
not be catching the post-emit overflow when the entire
emit is a single line (no wrap-engine cascade fired).

**Fix candidate:** in `_emit_argument_list`'s P4 single-
arg path, post-emit check whether the resulting line
overflows; if yes, fire `_fire_wrap_overflow_advisory`
with site label `"argument list"`. The 0.5.1
post-`try_priorities` advisory call should already do
this — investigate why it doesn't fire here.

**Test fixture to add:** `arg_list_wrap/10_p4_single_arg_overflow_advisory`
where the single-arg literal pushed to a new line at
block+4 still exceeds 80 chars. Expected: the formatter
emits the overflowing line AND fires an advisory.

---

## D. `JsonObject obj = buildObject(lambda)` reformat made the line WORSE

**Symptom:** A `JsonObject obj = buildObject(lambda)` pattern
where the lambda body is a method invocation with a long
literal got reformatted to a shape that's 89 chars wide,
worse than the original's 81 chars.

**Repro** — `src/test/java/com/senzing/util/JsonUtilitiesExtraTest.java:267-269`:

```java
        JsonObject obj
            = buildObject(
                job -> add(job, "k", new BigInteger("123456789012345678901234567890")));
```

Line 269 is 89 chars. The original (pre-0.5.0) was
presumably:

```java
        JsonObject obj = buildObject(
            job -> add(job, "k", new BigInteger("123456789012345678901234567890")));
```

That's 81 chars on line 2 (a 1-char overflow that was
arguably acceptable). The 0.5.0+ wrap engine's
break-at-`=` (the variable_declarator wrap priority 2)
fires when single-line doesn't fit, and produces the
3-line shape — but the resulting line 3 is 89 chars
(8 chars worse than the original 81).

**Likely root cause:** when `_emit_variable_declarator`'s
P2 break-at-`=` fires, it doesn't post-emit-check whether
the resulting value-line overflows. If it does, P2
should reject and the formatter should fall through to a
shape that overflows less (e.g. emit `buildObject(` then
break, then emit the lambda body at +8 indent rather
than the lambda starting at the deeper column).

**Fix candidate:** add post-emit width check to
variable_declarator P2; reject when value-line exceeds
80 chars AND the previous candidate's overflow was
strictly less.

**Test fixture to add:** `variable_declarator_wrap/01_p2_rejects_worse_than_p1`
with a long-RHS that overflows by 1 char in P1 but by
more in P2; expected: pick P1 (the lesser evil) and
fire the advisory.

---

## E. `result.add(arguments(...))` over-eager break

**Symptom:** Sequences of `result.add(arguments(...))`
statements where most lines fit on one line of source
get inconsistent treatment — some lines collapse to
single-line, others break to a `result.add(\n  arguments(...))` shape that's now multi-row.

**Repro** — `src/test/java/com/senzing/util/JsonUtilitiesTest.java:3050-3068`:

```java
        result.add(arguments(true, JsonValue.ValueType.TRUE));
        result.add(arguments(false, JsonValue.ValueType.FALSE));
        result.add(arguments("ABC", JsonValue.ValueType.STRING));
        result.add(arguments(((short) 123), JsonValue.ValueType.NUMBER));
        result.add(arguments(123, JsonValue.ValueType.NUMBER));
        result.add(arguments(123L, JsonValue.ValueType.NUMBER));
        result.add(arguments(123.456, JsonValue.ValueType.NUMBER));
        result.add(arguments(123.456F, JsonValue.ValueType.NUMBER));
        result.add(
            arguments(
                new Object[] { 10L, 5.5, true, "three" }, JsonValue.ValueType.ARRAY));
        result.add(arguments(
                List.of(10L, 5.5, true, "three"), JsonValue.ValueType.ARRAY));
        result.add(arguments(
                Set.of(10L, 5.5, true, "three"), JsonValue.ValueType.ARRAY));
        result.add(arguments(
                Map.of("foo", "bar", "phoo", true, "num", 25L),
                JsonValue.ValueType.OBJECT));
        result.add(arguments(Map.of(1, 10, 2, 20), JsonValue.ValueType.STRING));
```

The `new Object[] { ... }` case (line 3058-3060) gets a
3-line shape because `result.add(arguments(new Object[]
{ 10L, 5.5, true, "three" }, JsonValue.ValueType.ARRAY))`
overflows on one line. But the `List.of(...)` case
(line 3061-3062) goes to 2 lines because the chain wrap
catches at a different point. The visual inconsistency
across nearly-identical statements is jarring.

**Likely root cause:** the wrap-cascade decisions
between `_emit_method_chain_wrapped` (for the outer
`result.add(...)`) and `_emit_argument_list` (for the
inner `arguments(...)`) interact in subtly different
ways depending on what's INSIDE the inner `arguments`
call. When the inner arg is itself wrappable (a method
call, an array initializer), the wrap-engine triggers
break-at-receiver for `result.add(` differently than
when the inner arg is a single literal.

**Fix candidate:** this one's less clear-cut. The
"inconsistent treatment" issue may be inherent to the
greedy wrap cascade — small differences in arg
complexity cross the 80-char threshold at different
points. Possible improvements:

1. Bias toward the SHALLOWER wrap shape when both fit
   (e.g. prefer `result.add(arguments(...))` collapse
   over `result.add(\n  arguments(...))` break, when
   widths permit).
2. Add a "consecutive statements" smoothing rule that
   detects neighboring statements with very similar
   shape and tries to give them consistent wrap
   decisions. (High complexity; probably out of scope.)

**Test fixture to add:** `method_chain_wrap/18_method_chain_arg_list_consistency`
with a sequence of similar `result.add(arguments(...))`
statements; expected: consistent shape across
neighbors.

This finding may legitimately defer to 0.6+ — the
"consecutive statements" rule is a significant
architectural change.

---

## Priority order for 0.5.2

### P0 — A (super() inner-call continuation alignment)

Real correctness-of-output issue. Affects production
source files (`MissingDependenciesException.java`, and
similar inner-call patterns across senzing repos).
Source-preserve column re-anchoring is the conceptual
fix.

### P1 — C (P4 single-arg overflow advisory not firing)

Silent overflow is worse than loud overflow. Adding
the missing advisory call is mechanical. Adopter sees
the warning and splits the literal.

### P2 — B (single-arg method chain continuation)

Same conceptual fix as A (source-preserve re-anchoring).
Probably falls out of the A fix once that lands.

### P3 — D (variable_declarator P2 rejects-worse-than-P1)

Post-emit width check + candidate rejection. Localized
change; clear test surface.

### P4 — E (`result.add(arguments(...))` consistency)

Defer to 0.6+ unless an obvious narrow fix surfaces.
Multi-statement smoothing is architectural.

## Verification plan (lessons from 0.5.0 + 0.5.1)

Per the consumer trial checklist
(`docs/faqs/building/consumer-trial-checklist.md`),
every consumer trial includes:

1. `mvn -Pcheckstyle validate` — formatting gate.
2. `mvn test` — semantic regressions.
3. `mvn javadoc:javadoc` — snippet/comment preservation.
4. Token round-trip — counts of `@highlight`/`@end`
   markers + trailing whitespace must match pre/post.
5. Idempotency — second formatter pass = 0 modified.

For 0.5.2 specifically, also verify:

- **Per-file widest-line audit:** `awk 'length($0) > 80'`
  on `src/main/java/` must not show any new overflows
  vs 0.5.1 (modulo CSOFF regions). Pre-0.5.2 baseline
  in `senzing-commons-java`: 2 long lines, both inside
  CSOFF blocks in `SQLiteConnector.java`.
- **Visual-consistency spot check:** the `result.add(...)`
  consecutive-statements pattern in
  `JsonUtilitiesTest.java:3050-3068` should not regress
  further; if it improves, capture as a positive
  outcome of the fix.

## Open question — consumer adoption sequence

When 0.5.2 ships, the consumer's `caceres-bump-standards-
0.5.1` branch (PR #228) becomes obsolete. Options:

- **Hold #228 open** until 0.5.2 lands; rename the
  branch via the GitHub rename API and re-formatter-
  refresh, same workflow as 0.5.0 → 0.5.1.
- **Merge #228 now**, then open a new
  `caceres-bump-standards-0.5.2` branch when 0.5.2
  ships.

Recommend the latter — #228 has a real correctness fix
(`ConnectionPool.java:760`) that shouldn't sit blocked
waiting for 0.5.2. Merge #228 standalone; cut a fresh
PR for 0.5.2 adoption when ready.
