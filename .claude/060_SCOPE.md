# 0.6.0 release scope (planning — draft)

_Draft 2026-07-07. Seeded after 0.5.3 shipped and PR #228
merged in `senzing-commons-java` (0.5.3 adoption). Work items
collected from three sources — the 0.5.2 investigation
(`052_SCOPE.md` findings A–E), 0.5.0 leftovers
(`051_SCOPE.md` "Deferred to 0.6+"), and gaps surfaced during
the 0.5.3 consumer adoption pass._

## Why this is a minor bump (0.5.x → 0.6.0)

The centerpiece is **architectural**: rework the source-
preserve path in `_emit_argument_list` so it can decide
whether the developer-authored shape or a fresh wrap-engine
emit is better. Today it always chooses "developer wins"
(modulo the 0.5.2 F shift-up-overflow guard). That's not a
bug fix — it changes formatter output on a class of inputs
and needs a real design + spec touch-up.

## Legend

Examples below are shown as **CURRENT / DESIRED** pairs.
"CURRENT" is exactly what 0.5.3 produces on real code in the
consumer trees (verifiable via `mvn -Pcheckstyle validate` or
`format_file.py`). "DESIRED" is what 0.6.0 should produce.

---

## P0 — Source-preserve speculatively-verify-then-commit (findings A/B/D)

**Origin:** `.claude/052_SCOPE.md` findings A, B, D.

**Problem statement.** `_emit_argument_list`'s source-preserve
path preserves developer-authored multi-row shapes verbatim
(modulo shift-UP re-anchor). This is fine when the author's
shape is at-or-better-than-canonical. It's wrong when the
source shape is stale (pre-0.5 format), or when a fresh
wrap-engine emit would fit under 80 chars while the preserved
shape overflows.

### Example A — stale continuation column preserved

Real site: `src/main/java/com/senzing/cmdline/MissingDependenciesException.java:33-37`.

CURRENT (0.5.3 — preserves col 28 continuation from pre-0.5
format; inner call's args at col 28 look "floating" —
neither block-aligned nor paren-aligned under the inner `(`
at col 55):
```java
    {
        super(source, option, specifier, buildErrorMessage(source,
                            option,
                            option.getDependencies(),
                            specifier,
                            specifiedOptions));
    }
```

DESIRED (0.6 — the naïve "paren-align inner under
`buildErrorMessage(`" shape at col 59 would OVERFLOW because
`option.getDependencies()` is 25 chars wide (col 59 + 25 =
col 84). The wrap engine must speculatively detect that,
back up, and break the outer `super()` args more
aggressively so the inner call has room. One valid landing
— outer P4 (one arg per line) so the inner arg list starts
at col 14, then inner P4 at col 32):
```java
    {
        super(source,
              option,
              specifier,
              buildErrorMessage(source,
                                option,
                                option.getDependencies(),
                                specifier,
                                specifiedOptions));
    }
```

Equally valid (outer P2-greedy packs `source, option,
specifier` on line 1, break before the multi-row
`buildErrorMessage`, inner P4 at col 32):
```java
    {
        super(source, option, specifier,
              buildErrorMessage(source,
                                option,
                                option.getDependencies(),
                                specifier,
                                specifiedOptions));
    }
```

Which one the wrap engine picks is one of the P0 open
questions — see "Better shape oracle" below. Both fit under
80 chars on every line, and both are strictly better than
the CURRENT stale-col-28 shape.

### Example B — continuation operator visually attached to closed inner group

**Problem statement.** When a boolean chain contains a
parenthesized sub-group and that sub-group closes on the
first line, the operator (`&&`, `||`) that joins the
sub-group to the NEXT operand of the OUTER expression must
align to the outer paren's continuation column — NOT to any
column deeper than the closed inner group's opening paren.
Deeper alignment reads to a human as "this operator belongs
to the closed inner group," which is semantically wrong.

Sketch:

```java
// BAD — cond3 visually appears to be a continuation of the
// (cond1 && cond2) inner group, but it's actually the
// second operand of the outer if-test.
if ((cond1 && cond2)
        && cond3)

// GOOD — cond3 clearly at the outer if(-paren-align
// column, showing it's an outer-expression operand.
if ((cond1 && cond2)
    && cond3)
```

The `condition_wrap/09` fixture (shown below in "The bug
repro that P0 must FIX") has a **mixed** shape — the `||`
on line 2 and the `&&` on line 3 correctly paren-align to
their enclosing parens, which is what we want. But the
string literal on line 4 is stranded at col 28, which
paren-aligns to NOTHING (see the fix in that section). P0
must preserve the correct `||`/`&&` positions while
correcting the literal's column to paren-align under
`equals(`.

**When 0.5.3 gets it wrong.** The failure mode surfaces when
`_emit_argument_list`'s source-preserve path inherits a
stale continuation column from a pre-0.5 format. If the
developer originally authored `cond3` at a deeper column
(e.g. because a prior formatter emitted it that way), source-
preserve preserves the deeper indent even though a fresh
wrap-engine emit would place `cond3` at the correct
paren-align position.

**No confirmed repro in `senzing-commons-java` today.** The
0.5.3 adoption pass reformatted all consumer test/main
sources; if any lingered from a pre-0.5 format they would
already be fixed. The concern is preventing regression when
new adopters bring pre-0.5 code AND when the source-preserve
rework moves ahead — P0 must produce the GOOD shape by
construction, not by relying on the source having the right
shape already.

**Fixture to add for P0.** A synthetic input with `cond3`
at a stale deeper column, plus expected output at the
correct paren-align — locks the "reshape stale continuation"
behavior explicitly.

### Example D — source-preserved shape actively wider than fresh

Real site: `src/test/java/com/senzing/util/JsonUtilitiesExtraTest.java:267-269`.

CURRENT (0.5.3 — variable_declarator P2 wrap-at-`=` picked,
but the source-preserved lambda body overflows to 89 chars):
```java
        JsonObject obj
            = buildObject(
                job -> add(job, "k", new BigInteger("123456789012345678901234567890")));
```

DESIRED (0.6 — either fresh P1 or P4 shape that fits ≤ 80,
determined by speculative comparison):
```java
        JsonObject obj = buildObject(
            job -> add(job,
                       "k",
                       new BigInteger("123456789012345678901234567890")));
```

### The bug repro that P0 must FIX (formerly labeled "canary")

`condition_wrap/09` fixture — 0.5.3's source-preserve
preserves the developer's arbitrary col 28 for the literal,
which doesn't paren-align to ANY enclosing paren. The
correct enclosing paren for that literal is `equals(` at
col 35 (paren-align position = col 36).

CURRENT (0.5.3 — literal at col 28, doesn't paren-align to
any enclosing paren — this is a bug):
```java
        somewhatLongFlagName = (somewhatLongFlagName
            || (result.containsKey("key")
                && (!Boolean.FALSE.equals(
                            "a quite long string literal that the developer placed at a low column"))));
```

DESIRED (0.6 — literal at col 24, one `+4` step past the
enclosing `(!Boolean.FALSE.equals(...))` grouping paren at
col 20. The `emit_p4_single_arg` P4 fallback in
`_emit_argument_list` engages a paren-deference rule when the
arg is a literal AND an enclosing `parenthesized_expression`
set `paren_expr_col`: continue at `paren_expr_col + 3`
(= "col of enclosing `(` + 4"). Still overflows because the
literal itself is 68 chars, but the placement is now
semantically meaningful — the literal reads as "content of
that grouping paren." Fixing the overflow requires the
developer to split the literal by hand):
```java
        somewhatLongFlagName = (somewhatLongFlagName
            || (result.containsKey("key")
                && (!Boolean.FALSE.equals(
                       "a quite long string literal that the developer placed at a low column"))));
```

Resolution of Q1c drove this update — see "Open questions
— RESOLVED" section below. `condition_wrap/09`'s
`expected.java` was UPDATED as part of P0 to lock the col 24
shape.

**Two-candidate cascade selects the shape.** `emit_p4_single_arg`
splits into two `try_priorities` candidates:

1. **Block+4** (tried first) — canonical single-indent
   continuation past the call's statement start. Wins when
   the arg fits at the shallow col.
2. **Paren-defer** (tried last, spec C1 emit-and-warn
   fallback) — `paren_expr_col + 3` when a
   `parenthesized_expression` is active, otherwise mirrors
   block+4. Commits when NO earlier candidate fit, so it
   catches the cases where every column overflows.

Behavior by arg category under this cascade:

- **Long literals that can't be split** (canary): both cols
  overflow → paren-defer wins → literal at "col of
  enclosing `(` + 4", semantically aligned under its group.
- **Long identifiers that overflow everywhere** (Case 5 in
  the 2026-07-08 walkthrough): same — paren-defer wins for
  the same reason. Checkstyle reports the overflow and the
  developer renames the identifier.
- **Args that fit at block+4** (short identifiers / short
  method-call names / anything comfortably under 80): block+4
  wins as the first fitting candidate. This preserves
  pre-0.6 behavior for cases like `.asList(timers)` nested
  inside a binary chain (`arg_list_wrap/03`), avoiding a
  cascade that would push the outer binary from P2 to P3.

The 0.5.x source-preserve shift-up rule remains: a subsequent
format pass that sees a block+4-emitted arg inside an
enclosing group will normalize to paren-align on the way
back through the source-preserve gate. That's a legitimate
convergence step — the paren-aligned shape then stays stable
on the third pass and onward.

**Approach.** Speculatively emit both candidates (source-
preserved AND fresh wrap-engine cascade), compare per-line
widths, commit the better shape. Requires:
- Speculative-emit harness (extend `Emitter.snapshot`/`restore`).
- "Better-shape" oracle. Working definition:
  1. Fewer lines that overflow 80.
  2. Tiebreaker: fewer total lines.
  3. Second tiebreaker: shallower continuation columns.
- Idempotency proof: pass-1 output must be a fixed point.

**Risk.** High. The 0.5.2 P0 attempt broke
`SzInstallLocationsTest` idempotency. This is the hard piece.

---

## P1 — `assignment_expression` wrap

**Origin:** surfaced during 0.5.3 consumer adoption.

**Problem statement.** `Type var = value` (variable_declarator)
has wrap logic. Bare `var = value` (assignment_expression)
does not. Deep-indent reassignments overflow silently — no
wrap AND no advisory (advisories fire only when the wrap
engine actively tried the construct).

### Example 1 — array-initializer RHS

Real site: `src/test/java/com/senzing/cmdline/CommandLineUtilitiesTest.java` (6 sites like this).

CURRENT (0.5.3 — 81 chars at 12-space indent, silent overflow):
```java
            args = new String[] { "--port", "9080", "--interface", "localhost" };
```

SHIPPED (0.6 — array literal wraps internally per
the "Array initializers" section of the standards
doc; `new Type[]` skips the break-before-`=` tier
per that section, so this specific case cascades
straight to the array's internal greedy pack at
Priority 3):

```java
            args = new String[] {
                "--port", "9080", "--interface", "localhost"
            };
```

### Example 2 — method-call RHS with long args

Hypothetical but common:

CURRENT (0.5.3 — silent overflow):
```java
            connection = pool.acquireConnection(timeoutMillis, retryPolicy, threadName);
```

DESIRED (0.6 — paren-align under `(`):
```java
            connection = pool.acquireConnection(timeoutMillis,
                                                retryPolicy,
                                                threadName);
```

### Example 3 — field assignment via `this.`

CURRENT (0.5.3 — silent overflow):
```java
        this.installLocation = SzInstallLocations.findLocation(defaultInstallPath);
```

DESIRED (0.6 — paren-align continues to work):
```java
        this.installLocation
            = SzInstallLocations.findLocation(defaultInstallPath);
```

**Approach.** Extend `variable_declarator`'s wrap logic to
`assignment_expression`, sharing the same P1/P2/P3 cascade
helpers. The syntactic difference is only the leading `Type`
— the RHS wrap decision is identical.

**Risk.** Low-medium. Small new call site into stable helpers.

---

## P2 — Method-chain wrap cascade (chain-head anti-stranding)

**Origin:** `.claude/051_SCOPE.md` "Deferred to 0.6+", plus
Barry's 2026-07-07 elaboration adding a full priority
cascade rather than a single fallback rule.

**Problem statement.** When a method chain follows a
receiver expression (constructor, factory call, method
invocation), the chain segments must land at a
predictable, readable continuation column. 0.5.3 handles
the trivial cases (chain fits on line 1) and some pathological
ones (chain stranded on receiver's last-arg-line, which is
what the earlier "chain-head anti-stranding" phrasing
described). What's missing is the full priority cascade
for when the chain does NOT fit on one line.

**Rule cascade.** Try priorities in order, commit the first
one that fits under 80 chars on every line. Two cascades
because the receiver shape drives the priorities available:

### Factory / method-call receiver cascade

Applies when the receiver has the shape
`Receiver.factoryMethod(args)` — i.e. there is a dot before
the receiver's args. Includes both `SomeClass.newBuilder(a,
b)` (static factory) and `someInstance.getService()`
(method on an object).

#### P0F — Full expression fits on one line

Trivial base case. If everything fits, no wrap.

```java
        this.foo = SomeFactory.newBuilder(a, b).chain1(p1).chain2().build();
```

#### P1F — Align on the "deep dot" (first chain's `.`)

Everything through the first chain method's `(args)` fits
on line 1. Subsequent chain methods break to align at the
first chain's `.` column.

```java
        this.foo = SomeFactory.newBuilder(arg1, arg2).chainMethod1(param1, param2)
                                                     .chainMethod2(param4)
                                                     .chainMethod3()
                                                     .build();
```

#### P2F — Align on the factory method's `.`

Everything through the receiver's `(args)` fits on line 1
but `.firstChain(args)` doesn't. Break before the first
chain method; all chain methods (including the first) align
on the factory method's `.` column.

```java
        this.foo = SomeLargerFactoryClassName.newBuilder(longerArg1, longerArg2, longerArg3)
                                             .chainMethod1(param1, param2)
                                             .chainMethod2(param3)
                                             .chainMethod3()
                                             .build();
```

#### P3F — If parenthesized, indent from the outer `(`

Whole expression is wrapped in an outer `(...)`. All chain
methods align at outer-paren-position + 4 (see Q-CHAIN-1 —
this is the "col 15 vs col 16" question).

```java
        this.foo = (SomeLargerFactoryClassName.newBuilder(longerArg1, longeArg2, longerArg3)
                        .someLongerMethodNameWithMoreParams(param1, param2, param3, param4)
                        .chainMethod2(param5)
                        .chainMethod3()
                        .build());
```

#### P4F — Not parenthesized, block+4

Falls back to a single indent past the enclosing block.
All chain methods at `block + 4`.

```java
        this.foo = SomeLargerFactoryClassName.newBuilder(longerArg1, longerArg2, longerArg3)
            .someLongerMethodNameWithMoreParams(param1, param2, param3, param4)
            .chainMethod2(param5)
            .chainMethod3()
            .build();
```

### Constructor cascade

Applies when the receiver has the shape `new SomeClass(args)`
— no dot before the receiver's args, so P2F's factory-dot
tier is not applicable. Cascade has one fewer tier.

#### P0C — Full expression fits on one line

```java
        this.foo = new BarBazService(a).chain1().chain2().build();
```

#### P1C — Align on the "deep dot" (first chain's `.`)

Same rule as P1F.

```java
        this.foo = new BarBazService(arg0).chainMethod1(arg1, arg2)
                                          .chainMethod2(param1, param2, param3, param4)
                                          .chainMethod3(param5);
```

Also applies when the constructor is grouped in an outer
`(...)` — the receiver+first-chain shape is unchanged:

```java
        this.foo = (new BarBazService(arg0)).chainMethod1(arg1, arg2)
                                            .chainmethod2(param1, param2, param3, param4)
                                            .chainMethod3(param5);
```

#### P2C — If parenthesized, indent from the outer `(`

Constructor args wrap paren-aligned to the constructor's
own `(`; chain methods align at outer-paren-position + 4.

```java
        this.foo = (new BarBazService(longerArg1, longerArg2, longerArg3, longerArg4)
                       .chainMethod1(arg1, arg2)
                       .chainMethod2(param1, param2, param3, param4)
                       .chainMethod3(param5));
```

Also when the constructor args themselves wrap multi-line
paren-aligned:

```java
        this.foo = (new LongerClassNameWithArgs(evenLongerArgOrExpression,
                                                anotherLongArgOrExpression)
                       .chainMethod1(arg1, arg2)
                       .chainMethod2(param1, param2, param3, param4)
                       .chainMethod3(param5));
```

Note two different alignment columns coexist here:
constructor args at the constructor's paren-align, chain
methods at the outer paren-align + 4.

#### P3C — Not parenthesized, block+4

Falls back to block indent.

```java
        this.foo = new BarBazService(longerArg1, longerArg2, longerArg3, longerArg4)
            .chainMethod1(arg1, arg2)
            .chainMethod2(param1, param2, param3, param4)
            .chainMethod3(param5);
```

Also when the constructor args wrap paren-aligned:

```java
        this.foo = new LongerClassNameWithArgs(evenLongerArgOrExpression,
                                               anotherLongArgOrExpression)
            .chainMethod1(arg1, arg2)
            .chainMethod2(param1, param2, param3, param4)
            .chainMethod3(param5);
```

### Sub-open questions on P2 — RESOLVED 2026-07-07

All five resolved by Barry through worked examples in the
0.6.0 scoping conversation. Recorded here with the resolution
and consequences.

**Q-CHAIN-1 — Off-by-one in "indent from paren" (P3F / P2C).**
The originally sketched examples showed chain-tail `.` at
`paren_char_col + 4` (col 15 for `(` at col 11), which is
one less than `paren_align_col + 4` (col 16).

**ANSWER (Q-CHAIN-1):** Option B — `paren_align_col + 4`.
Consistent with the enum/class-header wrap convention used
in 0.5.3. Barry confirmed the col-15 sketches were typos
and intended col 16. All P3F/P2C examples in this doc have
been adjusted accordingly.

**Q-CHAIN-2 — Single chain method fallthrough.**
```java
        this.foo = new BarBazService(a, b).thenChain();
```
If this overflows, P1C doesn't apply (no *subsequent*
chains to align to `.thenChain`'s dot).

**ANSWER (Q-CHAIN-2):** No special-case rule needed. The
cascade runs with N=1 chain and falls through to the normal
P2C (parenthesized) or P3C (block+4) tier depending on
whether the whole expression is grouped in outer parens.
Single chain isn't special.

**Q-CHAIN-3 — Nested receivers, where does the "receiver" end?**
The `someContainer.getService().someMethod(a, b).chain1().chain2();`
ambiguity has multiple possible parses.

**ANSWER (Q-CHAIN-3):** Use a **naming-convention heuristic**
to disambiguate. Detection based on the leftmost identifier's
character case:

- **PascalCase** (starts with uppercase, has at least one
  lowercase char) — e.g. `SomeClass.method(...)...` — treat
  as static factory. The leftmost identifier is the class
  name; the first method-invocation is the "factory
  method"; F cascade applies.
- **camelCase** (starts with lowercase) — e.g.
  `someInstance.method()...` — treat as instance chain. The
  leftmost identifier IS the receiver; every `.method(...)`
  after is a chain segment. Effectively "Option C" from the
  earlier examples.
- **SCREAMING_SNAKE_CASE** (all uppercase + underscores/
  digits, typically `static final` constants) — e.g.
  `SOME_CONSTANT.method()` — treat as **instance chain**,
  same as camelCase. Not a class despite the uppercase.
- **`new SomeClass(...)`** — constructor pattern; C cascade
  applies (already covered).

Consequence: `someContainer.getService().someMethod(a, b).chain1().chain2()`
under the heuristic is instance chain — receiver =
`someContainer`, all `.method(...)` calls are chain
segments. Chain-align col = first chain's `.` col
(under `.getService`), giving the "uniform indent" shape
where every segment lives on its own line.

**Q-CHAIN-4 — Chain method whose OWN args wrap.**
```java
        this.foo = someService.chain1(a, b)
                              .chainMethod(veryLongArg1, veryLongArg2, veryLongArg3, veryLongArg4)
                              .chain3();
```
When a chain method's own args need to wrap at the deep
chain-align col, do they paren-align to their own `(`
(keeping the deep chain-align col), or do we back off the
outer chain-wrap to a shallower tier?

**ANSWER (Q-CHAIN-4):** Option B — **back off the outer
chain-wrap to a shallower tier.** When any chain method's
args would overflow at the current chain-align col, retry
at a shallower tier (typically P2C/P3F paren-indent or
block+4). Reasoning: predictable, avoids the confusion of
mixing chain-wrap alignment with arg-list-wrap alignment
inside chain segments.

Consequence for implementation: chain-wrap must look-ahead
through all chain methods and check "would every chain
method's args fit at this chain-align col?" If any wouldn't,
downgrade the tier before committing. Heavier than a purely
local decision.

**Q-CHAIN-5 — Args-wrap + chain-wrap collision in P2C.**
The user's P2C multi-line-args sketch shows the
constructor's args paren-aligned to the constructor's own
`(` (deep col) AND chain methods paren-aligned to the outer
expression's `(` + 4 (shallow col) — two different
alignment columns coexist in the same expression.

**ANSWER (Q-CHAIN-5):** Option A — **dual columns are OK.**
Constructor args are part of the receiver scope; chain-tail
is a separate scope. They paren-align to their respective
enclosing parens independently. This is DIFFERENT from
Q-CHAIN-4's chain-method-args case (which shares the outer
chain scope, so overflow there does force a back-off) —
constructor args are syntactically separate from the chain
scope, so they don't share the back-off machinery.

**Approach.** Extend `_emit_method_chain_wrapped` with the
5-tier cascade above, plus the 4-tier constructor variant.
Detection of "factory pattern" vs "constructor pattern"
happens at the AST level — `method_invocation` receiver
with a dot triggers factory cascade; `object_creation_expression`
receiver triggers constructor cascade.

**Risk.** Medium-high. This is the biggest single P-item in
0.6 aside from P0. The tier detection and speculative
emission at each priority interact with the existing
try_priorities engine. Idempotency is not obvious —
priorities produce different columns, so second-pass input
must not shift decisions across tiers. Careful fixture
coverage per tier required.

---

## P3 — Cross-statement smoothing (finding E)

**Origin:** `.claude/052_SCOPE.md` finding E.

**Problem statement.** Structurally identical statements in
the same block get different wrap shapes because each is
emitted independently. Readability degrades — the reader
sees noise where identical patterns should look identical.

### Example — three sibling `result.add(arguments(...))` calls

Real site: `src/test/java/com/senzing/util/JsonUtilitiesTest.java:3057-3062`.

CURRENT (0.5.3 — three shapes for three structurally identical
calls):
```java
        result.add(arguments(123.456F, JsonValue.ValueType.NUMBER));
        result.add(
            arguments(
                new Object[] { 10L, 5.5, true, "three" }, JsonValue.ValueType.ARRAY));
        result.add(arguments(
                List.of(10L, 5.5, true, "three"), JsonValue.ValueType.ARRAY));
```

Three different wrap decisions:
1. Full single-line (fits).
2. `result.add(\n    arguments(\n        <expr>, <type>))` — source-preserved from pre-0.5 shape, doesn't wrap `<expr>` cleanly.
3. `result.add(arguments(\n    <expr>, <type>))` — different indent pattern than #2.

DESIRED (0.6 — smoothed to a consistent shape across all three):
```java
        result.add(arguments(123.456F, JsonValue.ValueType.NUMBER));
        result.add(arguments(new Object[] { 10L, 5.5, true, "three" },
                             JsonValue.ValueType.ARRAY));
        result.add(arguments(List.of(10L, 5.5, true, "three"),
                             JsonValue.ValueType.ARRAY));
```

(All paren-aligned under `arguments(`; the one that fits
single-line stays that way.)

**Approach.** Requires non-local context — formatter today
is strictly per-node. Would need a "recent siblings" scan
of the enclosing block that detects shape drift among
structurally-identical statements and picks a common shape.

**Risk.** High architectural cost. This is genuinely bigger
than P0's local speculative-emit change. Detecting "these
statements are structurally identical" requires AST
comparison and can false-positive on superficially-similar
but semantically-different calls.

**In-scope for 0.6.0** (Barry's call — "one more release to
get this right"). This is the biggest architectural addition
on the 0.6 list; ships last in the phasing so it has the
settled P0/P1/P2 base to build on and the widest verification
window.

**UPDATE 2026-07-09 — achieved by Phase 2/3.** The motivating
example above is now handled correctly WITHOUT non-local
cross-statement machinery. Phase 2/3's source-preserve
fall-through (declines the source-preserve gate when the
developer-authored shape would still overflow at target col)
combined with the emit_p4_single_arg two-candidate cascade
causes each of the three sibling `result.add(arguments(...))`
calls to independently pick the same canonical paren-aligned
shape — the local wrap engines converge naturally on the
same layout when they see structurally-similar inputs at
similar contexts. Locked by
`arg_list_wrap/11_sibling_calls_paren_align_naturally`. The
non-local architecture described in this section is deferred
unless / until a consumer trial surfaces a case that ISN'T
handled by the local convergence.

---

## P4 — SQL DDL one-clause-per-line detector

**Origin:** `.claude/051_SCOPE.md` "Deferred to 0.6+".

**Problem statement.** Hand-authored multi-line SQL DDL
strings (one clause per source line) get greedy-packed by
the 0.5.0+ binary cascade. Semantically identical output,
visually unreadable.

### Example — hand-authored `CREATE TABLE`

Author writes:
```java
        String sql = "CREATE TABLE foo ("
            + "  id INTEGER PRIMARY KEY,"
            + "  description TEXT,"
            + "  created_at TIMESTAMP"
            + ")";
```

CURRENT (0.5.3 — greedy-packed by binary cascade):
```java
        String sql = "CREATE TABLE foo (" + "  id INTEGER PRIMARY KEY,"
            + "  description TEXT," + "  created_at TIMESTAMP" + ")";
```

DESIRED (0.6 — preserve one-clause-per-line):
```java
        String sql = "CREATE TABLE foo ("
            + "  id INTEGER PRIMARY KEY,"
            + "  description TEXT,"
            + "  created_at TIMESTAMP"
            + ")";
```

### Current escape hatch — CSOFF/CSON markers

Today the only fix is to wrap the block in CSOFF:
```java
        // CSOFF
        String sql = "CREATE TABLE foo ("
            + "  id INTEGER PRIMARY KEY,"
            + "  description TEXT,"
            + "  created_at TIMESTAMP"
            + ")";
        // CSON
```

That's the escape hatch — invasive and easy to forget when
adding a new column.

**Approach.** Heuristic detector: string-concat chain where
each `+ literal` fragment starts with recognizable SQL
keywords (`CREATE`, `INSERT`, comma-prefix, whitespace-then-
keyword) suggests column-aligned DDL. Preserve source shape
when the detector fires.

**Risk.** Medium. Heuristics false-positive — a long prose
string authored one sentence per line might trigger.

**In-scope for 0.6.0** (Barry's call — "one more release to
get this right"). Ships alongside P0/P1/P2/P3. The
heuristic false-positive risk is real, so it needs
generous fixture coverage over prose vs. DDL vs. mixed
strings, and a documented opt-out (CSOFF still works as
the escape hatch for cases the detector gets wrong).

---

## P5 — Enum-header fill-ins (skip — not valid Java)

**Origin:** 0.5.3 shipped enum-header `implements` wrap; left
`type_parameters` and `permits` as `NotImplementedError`.

**Common source of confusion — what P5 is NOT.**

The `TestOption` enum in this repo declares:

```java
public enum TestOption implements CommandLineOption<TestOption, TestOption>
```

That looks generic at a glance because of the angle
brackets. But the angle brackets belong to the
**super-interface reference** `CommandLineOption<...>`, not
to the enum declaration itself. Java-syntactically:

- `enum TestOption` — declares an enum named `TestOption`
  with NO type parameters.
- `implements CommandLineOption<TestOption, TestOption>` —
  implements a specific *instantiation* of the generic
  interface `CommandLineOption<T, B>`, providing `TestOption`
  as both type arguments.

This is legal Java and is already handled correctly by
0.5.3's enum-header wrap — the type-args inside the
super-interface reference are emitted by
`_emit_class_header_wrapped`'s type-argument logic, not by
enum-header code.

**What P5 refers to (and why it's skipped).**

The `NotImplementedError` guards in `_emit_enum_declaration`
refuse two constructs that the tree-sitter grammar may
permit but that Java itself does not:

1. **Enum with type parameters** — e.g.
   `public enum Foo<T> { ... }`. Per JLS §8.9.1: "It is a
   compile-time error if an enum declaration has type
   parameters." Not legal Java.
2. **Enum with `permits`** — e.g.
   `public sealed enum Foo permits Bar, Baz`. Per JLS §8.9:
   an enum class is implicitly final at the class level, so
   it cannot be sealed. Not legal Java.

**Recommendation.** Skip. `NotImplementedError` is correct
behavior — if these ever appear in a real file they're
`javac` errors already, so no adopter can encounter them
during formatting. No spec change or code change needed for
0.6.0.

---

## Recommended 0.6.0 shape

**In-scope (all five, per Barry's "one more release to get
this right" directive):**
- **P0** — source-preserve speculatively-verify-then-commit
  (the flagship).
- **P1** — assignment_expression wrap.
- **P2** — chain-head anti-stranding.
- **P3** — cross-statement smoothing.
- **P4** — SQL DDL one-clause-per-line detector.

**Skipped (not applicable):**
- **P5** — enum `type_parameters`/`permits` (not valid Java).

**Scope note.** This is a substantial release. P0 and P3 are
each individually the biggest formatter changes since 0.5.0.
Shipping all five in one bump means the consumer-side trial
in Phase 6 has to catch regressions across all five surfaces
simultaneously. Budget accordingly — the bulk-trial phase
may surface issues that force us to loop back to earlier
phases.

## Phasing

Ordered by risk (low → high) so each earlier phase settles
before the next builds on it. If a phase surfaces a
regression, we can hold off subsequent phases without
throwing away the earlier work.

1. **Phase 1 — P1 warm-up.** `assignment_expression` wrap
   ships first; small change, exercises the P1/P2/P3
   helpers from a new call site, low risk. Confidence-
   builder and shakes out any regressions in the shared
   wrap infrastructure before we lean on it harder.
2. **Phase 2 — P0 spike.** Try speculative-emit design on
   throwaway branch. Measure idempotency on the fixture
   suite AND on both consumer trees. **Expected side
   effect:** `condition_wrap/09` MUST break (its
   expected.java is a bug repro under Q1c's answer) — the
   spike is only successful when that fixture's expected
   output shifts from the developer's col 28 to the
   paren-aligned col 36. If any OTHER fixture breaks,
   reset and redesign.
3. **Phase 3 — P0 implementation.** Real branch, real
   fixtures locking A/B/D-class fixes.
4. **Phase 4 — P2 chain-head.** Ships on the settled P0
   base. Small, mostly independent.
5. **Phase 5 — P4 SQL DDL detector.** Independent of P0/P1/
   P2 code paths (it's a source-preserve extension for a
   specific string-concat shape). Medium risk from
   heuristic false-positives; needs its own fixture family
   covering prose-that-looks-like-DDL, mixed-content
   strings, etc.
6. **Phase 6 — P3 cross-statement smoothing.** The biggest
   architectural addition. Requires a "recent-sibling"
   scan of enclosing blocks and shape-identity comparison
   across statements. Ships LAST because:
   - It builds on P0's speculative-emit machinery (both
     rely on "what would a fresh emit look like").
   - It has the widest blast radius (any block with 2+
     structurally-similar statements is a candidate for
     smoothing).
   - It needs the most verification time on the consumer
     trees.
7. **Phase 7 — Bulk consumer adoption trial.** Reformat
   `senzing-commons-java` + `sz-sdk-java` end-to-end; verify
   0 net new overflows AND that smoothing changes are
   improvements, not surprises. Manual visual review of a
   sample of files with high sibling-density (test data
   builders, argument-provider methods).
8. **Phase 8 — Tag 0.6.0, adopt consumer-side.**

## Non-goals for 0.6.0

- No spec text changes (the shape of the emitted code IS
  changing on A/B/D-class inputs, but the spec's
  brace/indent/paren rules don't shift).
- No formatter architecture rewrite beyond P0 speculative-
  emit. The AST walker, `try_priorities` cascade, and
  emitter model all stay.
- No new adopter-facing template changes. 0.6.0's public
  surface is the emitter behavior.

## Open questions — RESOLVED 2026-07-07

All resolved by Barry after reviewing worked examples. Each
answer is recorded below with the option chosen and the
consequences that follow.

### Q1 — P0's "better shape" oracle: how to compare candidates

When P0's speculative-emit finds that BOTH the source-
preserved shape AND a fresh wrap-engine shape fit under 80
chars, which do we pick? The oracle is the decision
procedure.

The obvious tiebreakers — "fewer overflow lines, then fewer
total lines" — settle most cases unambiguously. What
remains ambiguous is when both candidates have the same
overflow count AND the same line count. Three sub-cases
that need a rule:

#### Q1a — Same shape family, different continuation column

Two candidates that use the same "one arg per line" shape,
but at different continuation columns. Which continuation
column is preferred?

**Option A — Deeper (paren-align):**
```java
        result = foo.someMethod(veryLongArg1,
                                veryLongArg2,
                                veryLongArg3);
```
Continuation at col 32 (paren-align under `someMethod(`).

**Option B — Shallower (block+4):**
```java
        result = foo.someMethod(veryLongArg1,
            veryLongArg2,
            veryLongArg3);
```
Continuation at col 12 (block+4).

Both fit, both 3 lines. Option A visually groups the args
tightly under their owning call; Option B is more compact
horizontally and reads consistently with control-flow
continuation.

**Current wrap-engine default:** Option A (paren-align via
`emit_p4_multi_arg`). Only falls back to Option B when
paren-align overflows.

**Question for Barry:** if BOTH options fit, is paren-align
always preferred, or does column depth matter (i.e., prefer
Option B if it saves 20 columns)?

**ANSWER (Q1a):** Option A — paren-align. Deeper is
preferred when both fit. The visual grouping of args under
their owning call outweighs horizontal compactness.

#### Q1b — Different shape families with the same line count

Two candidates that use DIFFERENT shapes but produce the
same line count.

**Option A — P2-greedy (packed args, fewer break points):**
```java
        result = foo.doThing(arg1, arg2,
                             arg3, arg4);
```
2 lines. Greedy pack: as many args as fit on line 1, break,
finish on line 2.

**Option B — P4-multi-arg (one per line, then packed):**
```java
        result = foo.doThing(arg1,
                             arg2, arg3, arg4);
```
Also 2 lines but the "one arg per line" convention starts
first, then packs. (Unusual — this shape wouldn't be
produced by the current wrap engine, but source-preserve
might carry it from a pre-0.5 file.)

**Question for Barry:** if source-preserved gives us shape
B and fresh emit gives us shape A, both fitting and both 2
lines, which wins? My recommendation is A (canonical) — but
that means the oracle needs a "canonical shape" preference,
not just line/column counters.

**ANSWER (Q1b):** Option A — greedy (canonical wrap-engine
shape). Consequence: oracle must include a "canonical shape
wins ties" rule beyond the pure line/column counters.

#### Q1c — Source-preserved is developer-authored deep indent

The `condition_wrap/09` canary case: developer authored a
long literal at a deep column, deeper than fresh emit would
place it. Both overflow (long literals can't be split).

**Source-preserved (developer chose col 28):**
```java
        somewhatLongFlagName = (somewhatLongFlagName
            || (result.containsKey("key")
                && (!Boolean.FALSE.equals(
                            "a quite long string literal that the developer placed at a low column"))));
```

**Fresh emit (would put literal at col 20):**
```java
        somewhatLongFlagName = (somewhatLongFlagName
            || (result.containsKey("key")
                && (!Boolean.FALSE.equals(
                    "a quite long string literal that the developer placed at a low column"))));
```

Both overflow (the literal is 68 chars — neither col-28 nor
col-20 leaves room). The developer's col 28 is deliberate;
fresh emit's col 20 is mechanical.

**Question for Barry:** when both candidates overflow, does
the oracle:
- (a) Prefer the shallower one because it's "less bad"
  numerically (col 20 shape has smaller max width)?
- (b) Prefer the deeper one because it's what the developer
  chose (source-preserve wins ties)?

The canary is currently locked to interpretation (b) by
`condition_wrap/09`'s expected.java.

**ANSWER (Q1c):** Neither (a) nor (b) as I framed them.
Barry's principle: "if the literal doesn't fit anyway —
indented or not — why not indent it properly?" The formatter
should paren-align to the CORRECT enclosing paren regardless
of whether it fits.

For the canary example, the correct enclosing paren for the
string literal on the last line is `equals(` at col 35
(paren-align position = col 36 — its args should paren-align
under it). Not `(!` at col 19 (which is 3 nesting levels
out). Not the developer's arbitrary col 28.

The correct 0.6 shape for the canary:
```java
        somewhatLongFlagName = (somewhatLongFlagName
            || (result.containsKey("key")
                && (!Boolean.FALSE.equals(
                                    "a quite long string literal that the developer placed at a low column"))));
```
(Literal at col 36, paren-aligned under `equals(`. Overflows
by 24 chars — but the paren-alignment is semantically
correct, and the overflow is unfixable without splitting the
literal itself, which the developer must do by hand.)

**Consequences for P0:**
- Oracle rule: "fresh emit always wins over source-preserve
  when the fresh emit uses correct paren-alignment, even if
  both overflow."
- The current `condition_wrap/09` fixture is a **bug
  repro**, not a canary. Its `expected.java` locks the wrong
  behavior (developer's col 28) and must be UPDATED as part
  of P0 to lock the correct behavior (paren-align col 36).
- Any references elsewhere in this doc treating
  `condition_wrap/09` as a "must-keep-working" reference
  are now wrong — remove/update them.

Consequence rippled through the doc: the P0 section's
"canary" subsection is replaced with the updated shape;
Phase 2's "if it breaks `condition_wrap/09`, reset and
redesign" instruction is inverted — Phase 2 MUST break the
old fixture and update it to the correct expected shape.

---

### Q2 — P2 chain-tail continuation column

Where does the chain-tail land after the receiver's closing
paren?

**Option A — `paren_align_col + 4` (indented under receiver's `(`):**
```java
        this.foo = new BarBazService(veryLongArg1, veryLongArg2)
                                     .thenChainWithLongName();
```
Continuation at col 37 (below the `(` in `BarBazService(`).

**Option B — `block + 4` (spec item 8's convention):**
```java
        this.foo = new BarBazService(veryLongArg1, veryLongArg2)
            .thenChainWithLongName();
```
Continuation at col 12 (single indent past the enclosing
block).

**Option C — `receiver_expr_col + 4` (indented under the assignment RHS):**
```java
        this.foo = new BarBazService(veryLongArg1, veryLongArg2)
                       .thenChainWithLongName();
```
Continuation at col 23 (below `new` in `new BarBazService`).

**Tradeoffs:**

- **Option A (paren-align + 4):** the chain-tail visually
  attaches to its receiver's arg list. Downside: if the
  receiver's `(` is at a deep column (as here, col 33),
  the tail continuation is very deep too. For long chain
  method names this risks overflow.
- **Option B (block + 4):** the chain-tail lands at the
  same indent as any other statement continuation in this
  block. Visually consistent with control-flow wrap. This
  is what I used in the current DESIRED shapes throughout
  P2's examples. Downside: the chain-tail is not visually
  "grouped" with its receiver.
- **Option C (receiver-expr-col + 4):** the chain-tail
  aligns with a column that's related to but shallower
  than paren-align. Middle ground; downside: this is a
  novel indent column, doesn't match any existing spec
  rule.

**My recommendation:** Option B. Rationale: matches spec
item 8's convention, avoids deep-column overflow risk,
reads consistently with block-level continuation. But this
is genuinely a style call.

**Question for Barry:** which of A/B/C, and if B, are you
OK that the chain-tail doesn't visually group with its
receiver?

**ANSWER (Q2):** Option B — `block + 4`. Barry's rationale:
- **Rejecting Option A (paren-align):** makes the chain
  call look like a third parameter to the receiver.
  Visually misleads the reader.
- **Rejecting Option C (receiver-expr-col + 4):** implies
  an open paren before the `new` keyword that isn't
  there. Only makes semantic sense if the statement was
  `this.foo = (new BarBazService(…)` (paren-grouped RHS),
  which it isn't. Also raises overflow risk on longer
  chain calls.
- **Accepting Option B:** matches spec item 8's
  convention, no misleading visual grouping, safest
  overflow-wise. Trade-off accepted: chain-tail isn't
  visually grouped with its receiver, but that's outweighed
  by the other two options' active downsides.

---

### Q3 — Ship P3 (cross-statement smoothing) in 0.6.0 or defer to 0.7?

The original open question was whether the P3 cross-
statement inconsistency was painful enough on adopter code
to bring the item into 0.6, or whether it could wait for a
separate 0.7 release.

**ANSWER (Q3):** In-scope for 0.6.0. Resolved by Barry's
"one more release to get this right" directive earlier this
session. P3 is now Phase 6 in the release plan (ships last
because it has the widest blast radius and needs the most
verification-window time).

## Adopter action required (preview)

Consumers upgrading their submodule pin from 0.5.3 to 0.6.0
will see formatter output change on all five in-scope
surfaces:

- **P0** — multi-row arg lists whose source shape overflows
  or is worse than a fresh wrap-engine emit.
- **P1** — bare `var = value` assignments to array-init or
  method-call RHS values (previously silent overflows).
- **P2** — receiver + chained method calls where the full
  expression overflows but receiver+args alone fits.
- **P3** — blocks of structurally-similar sibling statements
  now converge to a consistent wrap shape.
- **P4** — hand-authored multi-line SQL DDL strings preserve
  their column-per-line shape instead of greedy-packing.

Each consumer adoption will need to re-reformat and either
accept the diff or hand-adjust the surprising cases. Same
pattern as the 0.5.0 adoption, but with wider surface —
expect a larger diff. Manual visual review recommended on
files with dense sibling patterns (test data builders,
JUnit `@MethodSource` provider methods, argument-of-arguments
patterns) since P3's smoothing will move code around.
