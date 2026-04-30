## Javadoc and Comment Reflow Conventions

### Rule 1: No orphan words on continuation lines

When wrapping prose in Javadoc, comments, or string literals, do not leave 1–3 orphaned words on a continuation line. A single short word ending a paragraph is fine — but if a continuation line could comfortably fit more content from the next line, prefer a balanced break.

**Bad — orphan continuation:**

```java
/**
 * The number of milliseconds to sleep between checks on the
 * locks required for
 * tasks that have been postponed.
 */
```

**Good — balanced reflow:**

```java
/**
 * The number of milliseconds to sleep between checks on the
 * locks required for tasks that have been postponed.
 */
```

The same rule applies to `// line comments` that wrap.

### Rule 2: Do not invent words to pad lines

When reflowing existing prose to fit 80 characters, **only re-split the existing text**. Do not add filler words, restate ideas, or invent new content to make a line look "fuller."

**Bad — added filler:**

Original:
```java
// Loads the configuration from disk.
```

Reflowed (invented "before initializing the engine" to pad):
```java
// Loads the configuration from disk before initializing the
// engine.
```

**Good — leave it alone if no reflow is needed.**

This rule applies to all reflow operations — Javadoc prose, `@tag` descriptions, `// line comments`, and string concatenations. The `fix_javadoc_reflow.py`, `fix_javadoc_inline_tags.py`, and `fix_javadoc_tags.py` scripts respect this by design (they only re-split existing tokens), but human and AI-generated edits sometimes drift.

### Why these rules

Both conventions exist to keep diffs readable and prevent semantic drift:

- Orphans visually fragment the prose and signal sloppy formatting.
- Inventing filler changes the meaning of a comment and can introduce inaccuracies.

When in doubt, run the bulk-format scripts on the file in question — they make conservative, mechanical edits that respect both rules.

### Where this comes from

These rules emerged from formatting work across multiple Java repos using AI-assisted reformatting, where the early reflow output produced both kinds of artifacts before the rules were codified.
