# Source preservation: what it used to decide, and why those rules were removed

## Question

`_arg_list_takes_source_preserve_path` in `format_java.py` is short: an
argument list is emitted verbatim from source only when it spans multiple
rows AND either contains interleaved comments or sits inside a
`// CSOFF` region. Earlier releases had several more rules in that
function. What were they, why did they exist, and what should I know
before adding anything like them back?

## Short answer

Everything except the comment and CSOFF checks was removed in 0.7.0,
because all of it keyed on **how the file happened to be written** rather
than on the AST. Preservation now fires only for the two reasons that are
about _correctness_ — the wrap engine cannot reflow interleaved comments,
and the standards document explicitly opts out of reflow inside CSOFF
regions. If you are considering a new rule here, the test to apply is:
_would this rule give a different answer for two files that differ only
in whitespace?_ If yes, it belongs in the wrap engine, not here.

## Why preservation existed at all

Two distinct motivations got conflated, and separating them is the whole
lesson.

**Correctness.** Some constructs cannot be re-emitted safely. The wrap
engine has no concept of a comment sitting between two arguments, so
reflowing `foo(a, /* why */ b)` would corrupt it. CSOFF regions are an
explicit author instruction to leave alignment alone — the
"Formatted Log and Diagnostic Messages" rule in the standards exists so
that column-aligned diagnostics and SQL DDL survive. These reasons are
permanent.

**Deference.** The rest was a fallback meaning "the formatter cannot
obviously do better, so keep what is there." That is the part that had to
go.

## The rules that were removed

### The width-based fallback (the big one)

> Preserve when the source spans rows and its first line fits at the
> emission column.

The intent was modest: if an author wrapped an argument list by hand and
the result looks plausible, do not churn it. In practice, on any file the
formatter had already touched, "what is there" is **whatever an earlier
version of the formatter wrote**. So the rule was a propagation channel
for the formatter's own past mistakes. A deep orphaned continuation
survived every subsequent pass because the orphan was in the source and
this gate faithfully re-emitted it. Fixing the wrap engine did not fix the
file, which is a deeply confusing failure mode to debug.

It also made layout history-dependent: two semantically identical files
formatted differently according to how they were typed. That is the
general case of the "a shape the standards document lists as NOT PRODUCED
is still produced" class of bug.

### The single-line width opt-out

> Decline preservation when the full argument list would fit on one line
> at the emission column.

This was a patch on the fallback above, not an independent rule. It
existed to catch gratuitous author wraps — `Modifier.isStatic(\n
modifiers)` — where the source's first line (`Modifier.isStatic(`)
trivially fits and so preservation would echo a pointless break. It
carried real subtlety worth recording, since the code is gone. The width
estimate could not simply collapse whitespace over the source text: it
walked the AST to find `string_literal` / `character_literal` / comment
regions and preserved their text verbatim, normalizing comma spacing only
outside them. A naive regex pass mis-normalizes a comma inside a string
literal (`foo("name=A,value=B")` becoming `foo("name=A, value=B")` for
measurement purposes), over-estimating the width by one character per such
comma and so incorrectly retaining preservation. If you ever need to
measure "would this render on one line" from source text again, that is
the trap. Prefer a speculative emit — the wrap engine's priority 1
candidate answers the same question by construction, which is why the
estimator (`_arg_list_single_line_estimate`, with its `_estimate_normalize`
helper) was deleted rather than kept.

Once the fallback was gone, the case this protected against could not
arise: every multi-row argument list reaches the wrap engine, whose
priority 1 candidate produces the single-line form directly.

### The semantic multi-row opt-out

> Decline preservation when any argument is a multi-row
> `lambda_expression`, `binary_expression` or `method_invocation`.

The reasoning was that these constructs have their own wrap engines and
re-emitting them from scratch yields columns rooted in the current emit
position, rather than echoing a column the developer hand-tuned for a
different indent context. Sound, but again only meaningful while there was
a subsequent path that would have preserved.

### The nested-call and wrapped-argument declines

Two 0.7.0-era rules declined preservation for shapes the nested-call wrap
rules own outright, and for a source layout showing an argument that had
wrapped. Both were added to stop preservation short-circuiting a wrap-engine
rule — the second because "if an argument breaks, the argument list breaks"
lives in the wrap engine's commit checks, which preservation ran ahead of.
Correct at the time, and subsumed the moment the fallback disappeared.

## The trap that makes all of this worth reading

Every one of these rules asked a question about **source layout**, and the
answer changes after the formatter runs. That makes the formatter's output
a function of its own previous output, which produces two failure modes:

1. **Self-perpetuating mistakes** — a bad shape in the file is read as
   author intent and re-emitted forever.
2. **Oscillation** — pass 1 sees single-row source and picks shape A; the
   file now has multi-row source, so pass 2 picks shape B; pass 3 returns
   to A.

The second bit the project more than once. `_arg_owns_its_rows` exists
specifically to answer "does this argument span rows _inherently_?"
structurally — block-bodied lambda, text block, anonymous class — and its
docstring warns against reaching for `_node_spans_multiple_rows`. Two
separate bugs came from ignoring that: an `arguments(Rectangle.class,
Set.of(...))` call alternating between shapes, and the method-chain
back-off test predicting multi-line emission from source rows, which
alternated a `Boolean.TRUE.toString().equals(...)` chain between a packed
and a one-segment-per-line form until 0.7.0 converted it.

## What to do instead

- Put layout policy in the **wrap engine**, where the input is the AST.
- If you need "does this construct inherently occupy multiple rows",
  answer it **structurally** (`_arg_owns_its_rows`), never from row spans.
- Add to `_arg_list_takes_source_preserve_path` only for a _correctness_
  reason — something the wrap engine would actively corrupt. Deference to
  the author's layout is not such a reason.
- A rejected alternative, for the record: a geometric predicate asking
  "is the preserved layout one the formatter would itself produce?" It was
  measured and abandoned. Classifying a layout needs the call line's
  indent, which is not reliably available inside the predicate because the
  emitter's current line is often not the call line; it misclassified
  around 2,000 argument lists. When you need to know that an earlier
  emission escaped its anchor, set an explicit flag at the escape site —
  that is what `Emitter._anchor_escaped` is for.

## Related

- `building/java-formatting-standards` — day-to-day formatter usage.
- `building/consumer-trial-checklist` — how to measure a formatter change
  against real source before releasing it.
- The 0.7.0 entry in `CHANGELOG.md` records the measured effect of the
  retirement: deep orphans 37 to 3, non-idempotent files 25 to 1.
