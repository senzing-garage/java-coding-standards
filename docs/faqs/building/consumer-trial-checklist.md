# Consumer Trial Checklist (Before Tagging a Standards Release)

## Overview

When preparing to tag a new release of `java-coding-standards`,
trial the candidate against each known adopter before the tag
lands. The shallow gate that 0.5.0 used (`mvn -Pcheckstyle
validate` only) missed a silent data-loss bug because checkstyle
doesn't validate that javadoc snippet markup survives
reformatting. The full gate below catches that class of issue.

## The five gates

A consumer trial PASSES only when ALL five gates pass:

### 1. Checkstyle

```bash
mvn -Pcheckstyle validate
```

Must report `BUILD SUCCESS` with zero LineLength or style
violations. If the consumer has source files that overflow at
the canonical column under the new spec's no-fallback policy,
the developer manually splits the long literal before this
gate goes green.

### 2. Tests

```bash
mvn test
```

Must report `BUILD SUCCESS` with zero failures, zero errors.
A formatter change that breaks tests is a semantic regression
(rare but possible — e.g. annotation arg order, string
escapes).

### 3. Javadoc — never skip

```bash
mvn javadoc:javadoc       # adopt the consumer's default profile
```

Must report `BUILD SUCCESS`. **Run this with the consumer's
default profile, NOT a profile that strips javadoc snippet
markup.**

The sz-sdk-java `java-17` profile sets
`<placement>x</placement>` on the
`maven-javadoc-plugin`, which strips `@snippet` tags entirely
under JDK 17 — useful for back-compat, but masks the entire
class of bug where the formatter drops `// @highlight` /
`// @end` snippet markers. The 0.5.0 release went out with a
real data-loss bug because the trial only ran the JDK-17
profile.

For consumers that target JDK 17+ for javadoc, run the gate
under the profile that DOES include snippet markup (typically
`java-18+`, `java-21`, or no profile at all). Pre-JDK-18 consumers
can use a plain javadoc invocation — the gate is checking
that the formatter didn't drop tokens, not that the resulting
javadoc renders correctly under every JDK.

### 4. Token round-trip

Count source tokens that the formatter could plausibly drop,
pre- and post-format. Counts must match:

```bash
# Snippet markers (javadoc @snippet markup)
grep -cE '(@highlight|@end|@start|@link|@replace)' \
    src/main/java -r > /tmp/pre-counts.txt
grep -cE '(@highlight|@end|@start|@link|@replace)' \
    src/demo/java -r > /tmp/pre-demo-counts.txt

# Trailing whitespace (forbidden per spec)
grep -rl ' $' src/main/java > /tmp/pre-trailing.txt

# Format, then re-count
python3 .java-coding-standards/tooling/scripts/format_file.py \
    src/main/java src/test/java src/demo/java
grep -cE '(@highlight|@end|@start|@link|@replace)' \
    src/main/java -r > /tmp/post-counts.txt
grep -cE '(@highlight|@end|@start|@link|@replace)' \
    src/demo/java -r > /tmp/post-demo-counts.txt
grep -rl ' $' src/main/java > /tmp/post-trailing.txt

diff /tmp/pre-counts.txt /tmp/post-counts.txt              # must be empty
diff /tmp/pre-demo-counts.txt /tmp/post-demo-counts.txt    # must be empty
diff /tmp/post-trailing.txt /dev/null                      # must be empty
```

If any diff is non-empty: the formatter is dropping or
introducing tokens — file a regression before tagging.

### 5. Idempotency — convergence, not a bare `0 modified`

```bash
# Second pass over an already-formatted tree.
python3 .java-coding-standards/tooling/scripts/format_file.py \
    src/main/java src/test/java src/demo/java
# Third pass — this is the one that must report `0 modified`.
python3 .java-coding-standards/tooling/scripts/format_file.py \
    src/main/java src/test/java src/demo/java
```

The gate is **convergence**, and there are two distinct outcomes
that a bare "second pass reports `0 modified`" reading conflates:

- **Converges.** A handful of files change on the second pass and
  then reach a fixed point (the third pass reports `0 modified`).
  This is tolerated. Record the count in the release notes and
  keep it trending down; a _growing_ count is a regression signal
  even though each individual file settles.
- **Never converges.** A file keeps changing on every pass, or
  oscillates between two renderings. This is **blocking** — file
  the case as a regression and don't tag.

So the release-blocking condition is a file that fails to reach a
fixed point, not a non-zero count on the second pass. Releases
have shipped with a small, tracked set of second-pass files where
every one converged.

Report both numbers, since only the pair is meaningful:

```text
files needing a second pass: N (all converging)
files failing to converge:   0     # must be zero to tag
```

To find non-converging files mechanically, format to a fixed
point with a bounded loop and flag anything still changing when
the bound is hit:

```bash
converged=0
for pass in 1 2 3 4; do
  python3 .java-coding-standards/tooling/scripts/format_file.py \
      src/main/java src/test/java src/demo/java
  if git diff --quiet; then converged=1; break; fi
  git commit -aqm "format pass $pass"
done
if [ "$converged" -eq 0 ]; then
  echo "NOT CONVERGED after 4 passes — blocking"
  git show --stat HEAD
fi
```

Note the `converged` flag. An earlier version of this snippet ended
with `git diff --quiet || echo "NOT CONVERGED..."`, which can never
fire: the loop commits after every pass that changed something, so
the working tree is clean by the time the loop exits — whether it
broke early on a quiet diff or fell through all four passes. The
flag records WHY the loop ended, which is the thing being tested.

## What changed in 0.5.0 → 0.5.1

0.5.0's pre-release trial against sz-sdk-java ran ONLY gate 1
(checkstyle). 0.5.0 shipped with a bug that:

- Silently dropped `// @highlight region="..."` line comments
  positioned between `=` and a text-block opener on assignment
  statements (e.g. `String x = // @highlight\n"""...""";`).
- Was idempotent on the broken output (so the data loss was
  unrecoverable by re-running the formatter).
- Was invisible to checkstyle (no rule covers token
  preservation).
- Was invisible to `mvn javadoc:javadoc` under the consumer's
  `java-17` profile (snippet tags were stripped by the profile
  anyway).
- Surfaced when CI ran the `java-21` profile, which doesn't
  strip snippets — javadoc validation failed on unpaired
  `@end region` markers.

Gates 3 and 4 above are designed to catch this and similar
data-loss bugs at consumer-trial time, before the standards
release is tagged. Run them.

## Workflow

```bash
# Setup: clone consumer with the candidate standards pin
cd /path/to/consumer
git checkout -b standards-trial-X.Y.Z
git -C .java-coding-standards fetch <candidate-remote> <candidate-branch>
git -C .java-coding-standards checkout FETCH_HEAD

# Run all five gates
mvn -Pcheckstyle validate                                  # gate 1
mvn test                                                   # gate 2
mvn javadoc:javadoc -P <profile-with-snippets-enabled>     # gate 3

# Pre-format snapshot
grep -cE '(@highlight|@end|@start|@link|@replace)' \
    $(find src -name '*.java') > /tmp/pre-tokens.txt

# Format
python3 .java-coding-standards/tooling/scripts/format_file.py \
    src/main/java src/test/java src/demo/java

# Gate 4 — token round-trip
grep -cE '(@highlight|@end|@start|@link|@replace)' \
    $(find src -name '*.java') > /tmp/post-tokens.txt
diff /tmp/pre-tokens.txt /tmp/post-tokens.txt              # must be empty

# Gate 5 — convergence (repeat until "0 modified"; any file that
# never settles is blocking)
python3 .java-coding-standards/tooling/scripts/format_file.py \
    src/main/java src/test/java src/demo/java
python3 .java-coding-standards/tooling/scripts/format_file.py \
    src/main/java src/test/java src/demo/java
```

If any gate fails, file the case as a regression PR against
the standards repo and re-run the trial after the fix. Don't
tag until every trial passes every gate.

## See also

- [Java formatting standards](java-formatting-standards.md)
- [Javadoc reflow conventions](javadoc-reflow-conventions.md)
