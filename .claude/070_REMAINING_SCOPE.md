# 0.7.0 shape census — decisions and outcomes

Record of the four output shapes the 0.7.0 consumer-trial census found
wrong, the decision taken on each, and what shipped. Census covered 504
files across `senzing-commons-java`, `sz-sdk-java`, `sz-sdk-java-grpc`
and `data-mart-replicator`.

**All four census findings are resolved in 0.7.0**, as are three of
the four items this document originally deferred — see the two
sections at the end for what shipped and what remains.

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
`arg_list_wrap/18_arg0_wraps_but_paren_aligned_still_fits`.

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

## Still deferred to 0.8

- The last second-pass file, `AbstractSchedulingService.java`, a
  chain-with-lambda that settles on pass 2. It is layout-dependent —
  pristine source and pass-1 output share an AST yet format
  differently — but the responsible read has NOT been identified. A
  predicate trace diverges inside
  `_arg_list_takes_source_preserve_path`, yet preservation fires zero
  times on that file, so that answer is discarded and cannot be the
  cause. Do not assume the chain cascade.
- Optional: surface the 23 line-comment orphan candidates as advisories
  through the existing `FormatterWarning` channel, leaving the judgment
  to a human.
