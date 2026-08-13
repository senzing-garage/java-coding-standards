# 0.6.2 scope — the four shapes 0.6.1 leaves wrong

Decisions from the 0.6.1 consumer-trial census (504 files across
`senzing-commons-java`, `sz-sdk-java`, `sz-sdk-java-grpc`,
`data-mart-replicator`). Counts are measured against 0.6.1 output at
commit `9c0025c` unless noted.

Verification baseline for all four: 728/728 pytest on the pinned
tree-sitter 0.26.0, and the 504-file trial gates — over-80 1598 →
1590, non-idempotent 25 → 11, shape C 73 → 24, switch-Allman 98 → 0,
zero AST changes.

---

## 1. Deep orphan — 21 sites, 13 files

An argument list whose opener sits mid-line at a deep column emits
its contents at `current line's leading spaces + 4`, which lands
LEFT of the `(` they belong to. Drift 5–49 columns.

```java
        SzInterestingEntity entity = new SzInterestingEntity(100L,
                                                             1,
                                                             Arrays.asList(
                                                                 "FLAG"),
                                                             Arrays.asList(
            createSampleRecord("DS", "R")));          // <<< col 12
```

Note line 4 is the CORRECT handling of the same construct; line 6 is
the identical shape one argument later.

### Decision

Two shapes take priority over the current output, in this order:

- **(a) break before the `=`** — `entity`, then `= new SzInterest…`
  on the next line. This is the variable-declarator cascade's
  break-at-`=` tier; prefer it when the construct is an assignment
  or declaration RHS.
- **(b) break before the first argument** and indent every argument
  as if the first had not fit.

### Trigger rule

If ANY argument cannot be broken across lines without still
overflowing 80, then ALL arguments behave as if the very first one
did not fit — i.e. the whole list escalates to the
break-before-first-argument shape rather than paren-aligning and
orphaning a later argument.

Indent for that shape: `base + 4`, possibly `base + 8` — to be
settled against real output during implementation.

### Why this is the right shape

The current failure is that paren-alignment is chosen on the basis
of the EARLY arguments fitting, and a later argument that cannot fit
is then orphaned. Testing all arguments up front makes the decision
once, for the whole list.

---

## 2. Declarations over 80, never wrapped — 26 sites

All in `SzRecord.java`. Records carrying an `implements` clause get
the Allman brace correctly but never run the parameter cascade on
the header. Up to 92 chars. Unchanged from 0.6.0.

```java
    public record SzFullAddress(String fullAddress, String addressType) implements SzAddress
    {
```

### Decision

- **First measure: move `implements` to the next line.** That alone
  resolves most sites.
- **Record components**, when they must also break: paren-aligned,
  one per line — same treatment as method parameters.

Confirm whether the standards document already states a rule for
record component wrapping; if not, add one alongside the fix.

---

## 3. Enhanced-`for` headers over 80 — 25 sites

Exempt from the wrap cascade. Basic `for` wraps correctly, so this
is a missing node-type case rather than a policy gap.

```java
        for (Map<String, Map<String, SzFlagMetaData>> parent : parentMaps) {
            for (Map.Entry<String, Map<String, SzFlagMetaData>> entry : parent.entrySet()) {
```

### Decision

Break on the `:`, pushing the colon to the next line. When the
header breaks, the opening brace goes **Allman** — consistent with
the existing "Multi-line Conditions" exception that already governs
`if`/`while`/`switch`.

---

## 4. Comment orphans — far smaller than first reported

**Corrected count: 41 candidates, not 1036.** The broad count of any
1–3 word continuation is 1036, but 995 of those have no room on the
previous line and are therefore unavoidable.

### Decision

An orphan matters **only if its words could have fit on the previous
line without overflowing 80**. That is the only case the reflow
engine can actually improve.

### Implementation caution

Even within the 41, the detector cannot distinguish a wrapped
paragraph from two adjacent independent comments, and merging the
latter would be wrong:

```java
                // we must have an acquired connection
                // create a handler          <- separate statements

        // CR followed by something other than LF.
        // cspell:disable                    <- a directive, never merge
```

Any fix needs a notion of paragraph continuation (and must leave
directive comments such as `cspell:` alone). Genuine cases look
like:

```java
                // their maximum lifespan (we handle maximum leases on
                // release)
```

Related: task #299, javadoc HTML `<li>` hanging-indent flattening —
same reflow engine, so one fix likely addresses both.

---

## Explicitly NOT defects — do not "fix"

| Count | Shape | Why it stays |
| ----- | ----- | ------------ |
| 1339 | over-80 containing a string literal | Unsplittable without rewriting the literal; the C1 advisory fires. Source had 2820. |
| 200 | other over-80 | Largely `// @highlight` javadoc snippet markers; unchanged from 0.6.0. |
| 92 | deep paren-align (≥ col 56) | Legitimate P3 — deep only because the call starts deep. |
| 24 | shape C | The deliberate 0.5.0 item-2b same-method density tier (`sb.append(a).append(b)`). |

Three of the four defect classes above (2, 3, 4) are pre-existing and
untouched by 0.6.1. Only the deep orphan is one 0.6.1 moved, and it
moved the right way: 37 → 21.
