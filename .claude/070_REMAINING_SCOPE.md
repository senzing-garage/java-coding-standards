# 0.7.0 shape census — decisions and outcomes

Record of the four output shapes the 0.7.0 consumer-trial census found
wrong, the decision taken on each, and what shipped. Census covered 504
files across `senzing-commons-java`, `sz-sdk-java`, `sz-sdk-java-grpc`
and `data-mart-replicator`.

This document holds two lists.

1. **The census itself** — four findings, numbered 1-4 below. All
   four are resolved in 0.7.0.
2. **A later backlog** — eight items, reviewed one at a time on
   2026-10-15 and recorded in the three sections at the end: one
   accepted into 0.7.0, one rejected outright, and six deferred
   under "Still deferred to 0.8".

The two lists are separate. Counts from one do not describe the
other. One further short section, after those three, records
items that belong to neither list, having surfaced while doing
the work.

## 1. Deep orphan — a construct emitted left of the `(` it belongs to

**Decision:** when any argument cannot be laid out without still
overflowing, the whole argument list escalates as if the first argument
had not fit.

**Shipped.** Escalation to priority 4 driven by a per-argument escape
check. One correction during review: the check scanned one row too many.
`Emitter.line_count` excludes the in-progress line, so the scan began on
the row already open when the argument started — for argument 0 that is
the call line, whose indent is always left of the continuation column,
so every wrapping first argument reported a false escape and skipped
priority 3. Fixed by starting one row later; pinned by
`arg_list_wrap/18_arg0_wraps_so_whole_list_breaks`.

Deep orphans across the corpus: **37 → 3**.

## 2. Declaration headers over 80, never wrapped

**Decision:** move `implements` to the next line as the first measure.
Break record components paren-aligned, one per line, if they must also
break.

**Shipped** exactly as decided — this is the spec's existing "Record
Headers" cascade, which had simply never been implemented. Components
emit through the shared parameter cascade with `force_wrap=True`, which
also retires source preservation for them; preservation was replaying an
author's packed layout and producing an 88-column row.

This exposed a second gap: the parameter cascade had never generated the
type/name column alignment the spec always required, so every aligned
list in the corpus was author-written and preserved. Implemented, with
two carve-outs — a single parameter is never padded (no column to form),
and lists containing varargs or receiver parameters are not padded
(their prefix is not a bare type, so one measured width does not model
them). Both are documented in the standards document.

## 3. Enhanced-`for` headers over 80

**Decision:** break before the `:`, with the colon leading the
continuation line, and the opening brace goes Allman because the header
is multi-line.

**Shipped.** A review pass caught that the wrapped path reserved nothing
for its own closing `)`, landing it in column 81 — silently and
idempotently, so no reformat would ever repair it. Now reserves one
character (one, not two, because the Allman brace moves to the next
line).

Over-long enhanced-`for` headers: **25 → 0**.

## 4. Comment orphans

**Decision:** an orphan only counts if its words would have fit on the
previous line without overflowing.

**Partly shipped, partly declined on evidence.**

Shipped: javadoc prose reflow now balances rather than packing greedily
when greedy leaves a trailing fragment of three words or fewer, sharing
one helper with `//` comment reflow, which has balanced since 0.6.0.
Scoped to two-line paragraphs — at three or more the soft-target rebuild
can hand the last line more than greedy did and split an inline
`{@link ...}` tag across rows.

Declined: joining `//` lines the author split. A run of `//` lines gives
no reliable signal for whether it is one wrapped comment or several
adjacent ones. Of 23 candidates, four were commented-out code, one a
tabular legend, and three pairs of independent statements. Merging the
wrong pair silently damages source, which is not a trade worth making
for a cosmetic gain.

Also shipped under this heading, and the more valuable half: an indented
javadoc line now counts as structure rather than prose. That fixed the
last non-converging construct in the corpus — reflow was erasing the
indent that determined paragraph grouping, so each pass regrouped and
reflowed differently.

## Explicitly not defects — do not "fix"

- **`<pre>` ASCII-art diagrams and box drawings.** Preserved verbatim
  and correctly so. `package-info.java` in `data-mart-replicator`
  carries 112 lines over 80 for this reason, identical before and after
  formatting.
- **Javadoc `{@snippet}` / `@highlight` / `@replace` directives.** Half
  of all remaining over-80 lines in the corpus. Wrapping them breaks the
  region markup they depend on.
- **Long `import` statements and `@ValueSource` annotations.** No
  wrappable structure.
- **A single string literal already longer than the limit.** Shortening
  it requires splitting the literal, which is a code change and outside
  what an AST-preserving formatter may do.

## Folded into 0.7.0 after this census was written

These three were deferred when the census was first written, then
folded into 0.7.0 later in the release. They are recorded here as
resolved so this document does not contradict `CHANGELOG.md`.

- **Shape B via lambda bodies.** `_is_nested_or_chained_call` now
  traverses `lambda_expression` when the call is the lambda's body, so
  an expression-bodied lambda is transparent to nested-call rule 2.
  Block-bodied lambdas stay opaque. 544 argument lists changed
  classification, none in the other direction.
- **Javadoc reflow at three or more lines**, including inline-tag
  atomicity. A minimum-raggedness pass charging every line — the last
  one included — replaced the soft-target rebuild, with 0.7.0's own
  layout as the floor so it can improve but not regress. 210
  paragraphs improved, zero regressions.
- **Five of the six second-pass files.** Two more layout-reading
  decisions were retired: the basic-`for` header now escalates when a
  clause wraps rather than only on overflow, and the Tier 1 brace
  collapse no longer gates on the SOURCE condition's row span.
  Second-pass files 6 to 1.

## Reviewed item by item, 2026-10-15

Each item below was walked through with a worked example from the
504-file corpus and decided individually, on the date in the heading
above. Figures are measured rather than estimated, against the
implementation each entry describes — not against a single commit,
since the item accepted here shipped after this section was written
and its figures were re-measured then. Several figures carried from
earlier drafts turned out to be wrong and are corrected in place,
each noted where it occurs.

### In 0.7.0

- **A declaration and its bare-assignment twin format differently.**
  A declared `Object x = recv.a().b(c)` breaks at `=`; the assignment
  `this.x = recv.a().b(c)` stays inline with the chain wrapped — two
  shapes for one construct, with the left-hand sides padded to equal
  length so the right side starts at the same column. Of 108 generated
  pairs varying receiver length, segment count, argument width and
  name width, 98 have a value that wraps and **27** of those settled
  on different shapes. (An earlier draft said 78 pairs diverging in
  every case; re-measuring before the fix shipped corrected both
  halves of that.)

  `_emit_assignment_expression` carries a comment asserting the
  opposite: that a declaration and "its bare-reassignment twin …
  should format identically rather than diverging on whether the LHS
  carries a type". The invariant was false and had been since at least
  0.6.0, which renders this exact pair byte-identically to this
  release before the fix — a statement about the pair, not the
  construct, since 0.7.0's chain-head work moved other shapes of it.

  **Shipped.** The declarator's Step 1 required the value on a single
  line, so a wrapping chain fell to break-at-`=`, while the
  assignment's accepted a multi-row value as long as every line fit.
  The declarator now admits the same multi-row value — guarded on the
  value having left the ladder and anchor-escape flags clear, because
  a value whose rows all fit may have got there by falling back to
  continuation indentation, which is the dangling-receiver shape this
  release removed elsewhere. Width alone cannot see that: taking the
  width test on its own looks like 48 more lines of compliance and is
  really **84 → 275** dangling receivers across **21 → 42** files
  (counted with the `_dangling_heads` helper the new tests ship).

  Done on a spike branch and merged after the corpus confirmed it.
  200 of 504 files change shape, over-80 **1571 → 1562** with no file
  gaining one, advisories (289) and convergence (1 second-pass, 0
  third) unchanged, and zero named-node-sequence differences. All 108
  generated pairs now agree.

### Decided against

- **Array creation with an initializer does not get the row-owning
  exemption, and should not.** Reviewed all five affected corpus
  files one at a time; the preferred shape was the current one in
  five cases out of five, including a long array whose elements wrap
  either way.

  The principle settles it independently of taste. The exemption is
  for arguments whose multi-row-ness is _inherent_ — a block lambda,
  anonymous class or text block cannot be one line. An array literal
  such as `new String[] { a, b }` can. It spans rows only because
  something wrapped it, which is exactly the case the "if an
  argument breaks, the list breaks" rule exists to catch. The array
  never qualified.

  This is a decision, not a postponement: no later work makes the
  array eligible.

### Still deferred to 0.8

- **An array initializer indents its body from the statement's line
  start rather than from the construct.** Split out of the exemption
  question above, where it was doing the arguing. In paren-aligned
  position the contents land left of their own opening brace —
  column 12 under a brace at column 28. A real emission defect,
  independent of any exemption, and the reason the exemption looked
  tempting in the first place.

- **The last second-pass file, `AbstractSchedulingService.java`.**
  Settles on pass 2 and is stable after. Pass 1 is NOT wrong: both
  passes carry the same 2 over-80 lines and the same 2 advisories,
  and are AST-identical to each other. Pass 2 is 20 lines shorter and
  collapses `getBackingTasks().forEach(task -> {` onto one line. So
  this is a cosmetic convergence gap, not a correctness one, and the
  consumer-trial checklist already runs to convergence.

  The responsible read has NOT been identified. An earlier claim of a
  chain-cascade ordering problem was RETRACTED — the evidence was a
  comparison of two inputs that already agreed. A trace diverges
  inside `_arg_list_takes_source_preserve_path`, yet preservation
  fires zero times on this file, so that answer is discarded too. The
  only item here whose cost cannot be bounded.

- **Advisories for line-comment orphans the formatter creates.**
  **13**, not the 23 this document claimed before it was measured.
  Those are runs where reflow stranded 1-3 words that the author had
  not. A further ~716 such runs exist in the formatted corpus but are
  author-written and untouched; advising on those would be noise.
  Explicitly excluded from 0.7.0 once already.

- **Retiring the paragraph splitter's `{@`-at-line-start rule.**
  **458 sites** across the corpus stop short where the inline tag
  would have fitted on the line above. The CHANGELOG calls this the
  only javadoc item on the backlog, which is accurate but gives no
  sense of scale — this is the largest blast radius on the list.

  Not a fix but a rule REPLACEMENT: a tag-per-line list is a
  legitimate authored shape, and the splitter cannot currently tell
  it from a line it gave up on. Retiring the rule without that
  distinction reflows deliberate layouts.

- **Hand-managed save/reset/restore of `_anchor_escaped` and
  `_chain_ladder_fired`** at 26 assignment sites. Recorded as a
  MAINTAINABILITY item, not a latent defect — an earlier draft of
  this document overstated it.

  Two real leaks were found and fixed during the release (the
  declarator's overflow backtrack, the assignment's probe-wins exit).
  Both were output-neutral, and that was measured, not assumed:
  reinstating both changes **0 of 504** corpus files and **0 of 552**
  generated shapes that nest a declarator inside a lambda body or
  anonymous-class body — the geometry the leak would have to corrupt.

  A naive context manager would also be wrong. The two flags have
  different lifetimes at the same call site: `_anchor_escaped`
  deliberately ACCUMULATES across the declarator backtrack, while
  `_chain_ladder_fired` is per-construct and must be restored.
  Treating them alike reintroduces the bug class it is meant to
  prevent.

- **The declaration advisory is blind to trailing side comments.**
  It measures the statement before `_attach_trailing_side_comments`
  runs, so a trailing `// …` that pushes the line past 80 is never
  reported: **834** such lines across 27 files, **831** of them with
  no advisory. Demonstrated, unlike the item above.

  Costs nothing in correctness — the line is over 80 and checkstyle
  rejects it, so the channel under-reports rather than hides. Not a
  regression either: 0.6.0 leaves 836. Awkward to fix late because
  moving the advisory would take the count from 289 to over a
  thousand, and the better answer may be to wrap the comment rather
  than merely report it.

  The best-diagnosed item here; worth doing first in 0.8.

## Also deferred, noted during the release

Not part of either list above — these surfaced while doing the work
rather than in the census or the 2026-10-15 review, and are
recorded here so the backlog is complete in one place.

- **Extending nested-call rules 1 and 3 through lambdas.** 0.7.0
  taught the traversal to reach through a lambda body for rule 2
  only. The CHANGELOG says so where it describes the tail
  placement, and calls the rest a separate change. It is.
