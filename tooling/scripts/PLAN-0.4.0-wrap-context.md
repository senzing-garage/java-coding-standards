# 0.4.0 WrapContext Design Plan

## Session-specific context

- **Branch:** `caceres-0.4.0-wrap-context` (pushed to origin)
- **Starting commit:** `062e066` — "0.4.0 WIP: interface + method header
  wrap, parameter P2/P3"
- **Consumer adoption baseline:**
  - Working tree: `.java` files reverted to HEAD (JDT-formatted, 2-space
    indent); non-Java changes (`.claude/*`, `pom.xml`, submodule pin)
    preserved.
  - Submodule pin in consumer is currently set to this branch
    (`062e066`).
  - First run of formatter from clean HEAD baseline:
    `mvn -Pcheckstyle validate` reports **51 LineLength errors**.
  - Down from **107** errors on first run of buggy 0.3.0, and **62**
    after the partial fix in `062e066`.
  - All **463 formatter unit tests** pass.
  - **Idempotency holds** across the full consumer codebase (second
    pass modifies 0 files).
- **Target:** drive the 51 remaining LineLength errors to 0 by
  implementing the WrapContext-based engine described below.

## Problem recap

The current formatter has wrap logic scattered across emitters
(`_emit_class_declaration`, `_emit_interface_declaration`,
`_emit_method_declaration`, `_emit_formal_parameters`,
`_emit_argument_list`, `_emit_variable_declarator`,
`_emit_binary_expression`). Each does its own
`snapshot → emit → measure → restore` dance. Expression-tree wraps
(method chains, ternaries, conditions) and comment reflow don't
exist at all. The remaining 51 errors all need cross-emitter wrap
coordination — incremental emitter patches have hit diminishing
returns.

## Core abstraction

### `WrapContext` (dataclass)

```python
@dataclass
class WrapContext:
    start_col: int          # column where current construct began
    indent_col: int         # continuation indent for this construct
                            # (typically start_col + 4)
    p3_indent_col: int      # next-line indent fallback
                            # (typically start_col + 8)
    parent: WrapContext | None  # for nested speculation
```

Passed down through emitters as needed. Replaces ad-hoc `start_col`
parameters scattered through the code today.

### `try_priorities` helper

```python
def try_priorities(
    emitter: Emitter,
    candidates: list[Callable[[], None]],
) -> int:
    """Try each emit candidate; return the index of the first that
    fit under _MAX_LINE, or last index if all overflow.

    Each candidate is a thunk that emits via the emitter. Between
    candidates the buffer is rolled back via snapshot/restore.
    """
    initial = emitter.snapshot()
    for i, fn in enumerate(candidates):
        emitter.restore(initial)
        saved = emitter.snapshot()
        fn()
        if emitter.last_lines_max_width(saved[0]) <= _MAX_LINE:
            return i
    return len(candidates) - 1  # all overflowed; last is committed
```

## Per-construct wrap rules (the catalog)

| Construct | Priorities | Status |
|---|---|---|
| Method declaration | P1 single → P2 break-after-`>` → P3 type-params paren-aligned → P4 also force params P3 | Partially done in `062e066` |
| Method invocation / chain | P1 single → P2 break at last `.` → P3 break at every `.` (vertical-aligned dots) | **NEW** — biggest impact |
| Method-call argument list | P1 single → P2 paren-packed 2-line → P3 paren-aligned one-per-line → P4 next-line single-indent | Mostly exists in `_emit_argument_list` |
| Formal parameters | P1 single → P2 paren-aligned → P3 next-line one-per-line at `p3_indent_col` | Just added (`force_wrap`) |
| Variable declarator | P1 inline → P2 break-at-`=` → P3 P2 + RHS expression wrap | Existing, needs RHS recursion |
| Ternary | P1 single → P2 break-before-`:` → P3 break-before-both `?` and `:` | **NEW** |
| Binary expression | P1 single → P2 break-before-leftmost-op (recursive into RHS) | Existing, raw-source fallback is the bug |
| `if`/`while`/`for` condition | P1 single → P2 break at `&&`/`\|\|` (Allman brace switch) | **NEW** |
| Line comment | P1 single → P2 reflow with `//` prefix | **NEW** — accounts for ~12 errors |

## Cross-cutting rules (uniform across all wraps)

1. Universal `->` placement (already implemented for lambdas/switch)
2. All-or-nothing wrap promotion (when any item overflows, promote
   all to next priority)
3. Cumulative continuation indent +4 per wrap level
4. Parenthesized-expression preference — operator continuation
   aligns under the column after `(`
5. C1 emit + warn — when no priority fits, emit anyway with a
   stderr warning rather than silently swallow the overflow

## Implementation order

### Phase A — Foundation (no behavior change, refactor only)

1. Add `WrapContext` dataclass and `try_priorities` helper.
2. Migrate `_emit_argument_list` to use them. Verify all 463 unit
   tests still pass.
3. Migrate `_emit_method_header_wrapped` and
   `_emit_class_header_wrapped`. Verify.

Calibration gate: 463 passing tests + idempotent on consumer
codebase. No behavior change expected.

### Phase B — Expression-tree wraps (high-impact set)

4. **Method-chain wrap** in `_emit_method_invocation`. Break at `.`
   with two priorities: P2 break at last `.`, P3 break at every
   `.` (vertical-aligned). Estimated impact: ~15 of remaining
   errors.
5. **Ternary wrap** in `_emit_ternary_expression`. P2 break-
   before-`:`, P3 break-before-both. Estimated: ~5 errors.
6. **Binary-expression** — replace `_emit_binary_expression` raw-
   source fallback with recursive RHS emit (the spec-correct
   behavior). Estimated: ~5 errors.

### Phase C — Statement-level wraps

7. **Variable-declarator** — when break-at-`=` continuation
   overflows, dispatch the value through its emitter's own wrap
   chain (Phase B emitters now provide this). Estimated: ~10
   errors.
8. **Method-call statement** — same idea for
   `expression_statement` whose expression is a long call.
   Estimated: ~5 errors.
9. **Condition wrap** for `if`/`while`/`for`. When the parenthesized
   condition overflows, break at `&&`/`||` boundaries. The
   surrounding brace placement switches to Allman per the spec's
   "multi-line condition → Allman" rule (already handled by
   `_node_spans_multiple_rows` once we've made it multi-line).
   Estimated: ~5 errors.

### Phase D — Comment reflow

10. Line comment reflow for `//` over 80 chars. Port the javadoc
    reflow algorithm to operate on a sequence of `// ` line
    comments. Treat `// CSOFF` / `// CSON` / `// CHECKSTYLE:` /
    `// SUPPRESS` directives as no-reflow (just like javadoc
    excludes them). Estimated: ~12 errors.

### Phase E — Validation

11. **Adoption gate:** `mvn -Pcheckstyle validate` clean on
    senzing-commons-java.
12. **Cross-check:** run formatter against sz-sdk-java; verify
    no new errors and the existing source diffs are intentional
    (small or clean).
13. **Fuzz suite:** idempotency + AST round-trip on the consumer
    corpus.

## Spec doc updates needed (before Phase A)

Update `docs/java-coding-standards.md`:

- Add a new top-level **"Wrap Priority Engine"** section that:
  - Defines the priority-cascading semantics formally.
  - States the single-indent (+4) vs double-indent (+8)
    conventions and when each applies.
  - Documents the parenthesized-expression preference.
  - Documents the all-or-nothing promotion rule (already there
    in spec, may need cross-references).
- Fix the existing Generic Type Parameters Priority 3 example
  text that has drifted (the spec text says "double-indented
  (8 spaces from the class declaration)" but the implementation
  uses `start_col + 4` = single-indent). Decision: **align text
  to code** (single-indent, +4), matches the rest of the codebase
  and is more compact. Update the example accordingly.
- Add a **"Method Chain Wrap"** section with worked examples
  (break at last `.` vs every `.`, vertical-align dots vs
  single-indent fallback).
- Add a **"Ternary Wrap"** section formalizing the existing tier
  descriptions.
- Add a **"Line Comment Reflow"** section describing when `//`
  lines are reflowed and which directives are exempt.

## Open questions (decide before Phase A)

1. **Indent convention for declaration-header wraps** —
   `start_col + 4` (single-indent, what the code does) vs
   `start_col + 8` (double-indent, what the spec text says).
   **Recommendation:** keep `start_col + 4`. Matches rest of
   codebase and reads more compactly. Update spec text to match.
2. **`WrapContext.parent`** — do we actually need it for any
   current rule, or is each wrap independent? **Recommendation:**
   defer; add later if Phase B surfaces a real need (nested
   wrap-priority decisions where the inner needs to know the
   outer's remaining budget).
3. **Comment reflow exemptions** — `// CSOFF` / `// CSON`
   absolutely exempt. `// TODO(...)` / `// FIXME` — probably can
   reflow (they're just prose). `// @snippet`-style or
   embedded-link comments — exempt by content. **Recommendation:**
   exempt anything matching `^// (CSOFF|CSON|@|CHECKSTYLE|SUPPRESS)`
   or containing a URL.
4. **Recursive AST nodes for chains** — tree-sitter exposes
   `a.b().c()` as nested `method_invocation` nodes. Method-chain
   wrap needs to flatten this chain into a sequence of
   `.identifier(args)` segments before deciding break points.
   Worth a small `_collect_method_chain(node)` helper.

## Estimated effort

| Phase | LOC | Tests added | Errors fixed |
|---|---|---|---|
| A (foundation) | ~50 | 0 (refactor) | 0 |
| B (expression-tree) | ~200 | ~30 | ~25 of 51 |
| C (statement) | ~150 | ~20 | ~20 of 51 |
| D (comment reflow) | ~80 | ~10 | ~12 of 51 |
| E (validation) | 0 | 0 | n/a |
| **Total** | **~480** | **~60** | **target: 0** |

Bounded and incremental. Phases B–D can be tackled in any order;
the Phase A foundation is the only true prerequisite. Adoption
gate after Phase E.

## Reference points in the current codebase

When resuming work, these are the key locations:

- **Existing speculative-emit pattern:**
  `format_java.py:_emit_class_declaration` (the canonical
  `saved = emitter.snapshot(); emit; if overflow: restore +
  wrap` shape).
- **Existing wrap helper:** `_emit_class_header_wrapped`,
  `_emit_method_header_wrapped`, the new `force_wrap` mode in
  `_emit_formal_parameters`.
- **Width-measurement:** `Emitter.last_lines_max_width(since)`
  is the truthful overflow check (includes the in-progress
  line via `len(self._current)`).
- **Method-call wrap:** `_emit_argument_list` already has
  P1/P2/P4 — Phase A migrates it to `try_priorities`.
- **Variable declarator wrap:** `_emit_variable_declarator`
  has break-at-`=`. Phase C extends.
- **Binary expression wrap:** `_emit_binary_expression` has
  break-before-leftmost-op with the raw-source fallback that's
  spec-incorrect (Phase B fix).

## Out of scope for 0.4.0 (deferred to 0.5.0 or later)

- Text blocks in indented context (still raises
  `NotImplementedError`).
- A2 blank-line enforcement (still source-preserved, clamped at
  one blank max). Adopters' code already follows A2 by
  convention, so this matches in practice.
- `module-info.java` formatting.
- Thread-safety of `_PARSER` singleton.
- Class-header indent convention realignment (the single-vs-
  double-indent question for class P3 wrap — pick one and
  document in the spec doc update).
