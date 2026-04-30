<!-- markdownlint-disable MD013 -->
# Java Coding Standards

This document defines the Java formatting and coding style standards.
These standards are enforced by checkstyle (via the `-Pcheckstyle`
Maven profile) and supplemented by the VSCode Java formatter where
possible. Where the VSCode formatter's limitations produce incorrect
formatting, manual correction or scripted correction is required.

---

## Line Length

- Maximum line length is **80 characters**.
- Exceptions (ignored by checkstyle via `ignorePattern`):
  - `package` and `import` statements
  - Lines containing URLs (`http://`, `https://`, `href`)
  - `static final` field declarations with generic type parameters
    (e.g., `Map<String, Set<ConfigOption>>`)
- Use `// CSOFF` before and `// CSON` after a line to suppress the
  line-length check when breaking the line would harm readability
  (see "Log Message Formatting" below).

---

## Brace Placement

### Allman Style (opening brace on its own line)

Used for **definitions** — the structural blocks that define types and
callable units:

- Class definitions (including inner/nested classes)
- Interface definitions
- Enum definitions (including `@interface` annotation definitions)
- Method definitions
- Constructor definitions

```java
public class OrderProcessor extends Thread
{
    public void run()
    {
        // ...
    }

    private static class BatchHelper
    {
        // ...
    }
}
```

### Same-Line Style (opening brace on the same line)

Used for **control flow** and **inline blocks**:

- `if` / `else if` / `else`
- `for` / `while` / `do`
- `try` / `catch` / `finally`
- `switch`
- `synchronized`
- Lambda expressions
- Array initializers
- Static class initializer blocks (`static { ... }`)

```java
if (value == null) {
    return;
} else if (value.isEmpty()) {
    throw new IllegalArgumentException("empty");
} else {
    process(value);
}

try {
    conn = getConnection();
} catch (SQLException e) {
    logError(e);
} finally {
    close(conn);
}

synchronized (monitor) {
    counter++;
}

switch (action) {
case REFRESH:
    refresh();
    break;
default:
    break;
}

Runnable task = () -> {
    doWork();
};

int[] values = { 1, 2, 3 };
```

### Exception: Multi-Line Conditions

When an `if` condition, `catch` specification, or similar wraps to
multiple lines, the opening brace goes on its **own line** to visually
separate the condition from the body:

```java
if (someVeryLongCondition
    && anotherCondition)
{
    doSomething();
}
```

### Closing Brace Rules

- `catch`, `finally`, `else`, `else if`, and `while` (in do-while)
  appear on the **same line** as the preceding closing brace:

```java
} catch (Exception e) {
} finally {
}

} else {
}

} while (condition);
```

- All other closing braces appear **alone on their own line**.

---

## Method and Constructor Declarations

### Parameter Placement (in priority order by line length)

**Priority 1: Single line** — if the entire declaration fits within
80 characters:

```java
    public String getName()
    {
        return this.name;
    }

    public void setName(String name)
    {
        this.name = name;
    }
```

**Priority 2: Parameters aligned to opening parenthesis** — one
parameter per line, types aligned vertically to the right of the
opening parenthesis, names left-aligned on the first 4-space tab stop
after the longest parameter type:

```java
    public SearchResult(ResultCode      resultCode,
                        QueryStatistic  statistic,
                        String          dataSource1,
                        String          dataSource2)
    {
        // ...
    }
```

**Priority 3: Double-indented parameters** — when parameter types are
too long to fit after the opening parenthesis within 80 characters,
parameters start on the next line with double indentation (8 spaces
from the method), types left-aligned vertically, names aligned on the
first 4-space tab stop after the longest type:

```java
    protected static void registerProtocolHandler(
            String                              schemePrefix,
            Class<? extends ProtocolHandler>    handlerClass)
    {
        // ...
    }
```

### Throws Clause

The `throws` clause always goes on its **own line** after the closing
parenthesis, single-indented (4 spaces from the method declaration).
Exception types appear on the same line if they all fit within 80
characters:

```java
    public void initialize(JsonObject config)
        throws ConfigurationException
    {
        // ...
    }
```

If multiple exception types don't fit on one line, place one per line
with types left-aligned and a comma after all but the last:

```java
    public void processRecord(String data)
        throws ConfigurationException,
               ProcessingException,
               IOException
    {
        // ...
    }
```

### Opening Brace for Methods

The opening brace is always **left-aligned on the same column** as the
beginning of the method declaration (Allman style), regardless of which
parameter placement priority is used.

---

## Line Continuation

When a line exceeds 80 characters and must be broken, the continued
line should begin with proper indentation and the **operator** that
connects it to the previous line.

### String Concatenation

Break at `+` operators, with the `+` starting the continuation line:

```java
    throw new IllegalArgumentException(
        "Cannot specify a secondary value when "
            + "the primary value is null.  primary=[ "
            + primary + " ], secondary=[ "
            + secondary + " ]");
```

### Ternary Operator

**Tier 1: Fits on one line** — keep it on one line:

```java
    int x = (num == null) ? 0 : num.intValue();
```

**Tier 2: Condition + `?` value + `:` value exceeds 80 chars but
`?` value fits** — break before `?`, keep `? value : value` together:

```java
    String text = (index == text.length() - 1)
        ? "" : text.substring(index + 1);
```

**Tier 3: `? value : value` itself exceeds 80 chars** — break before
both `?` and `:`, with `:` aligned under `?`:

```java
    StatusLevel statusLevel = (code == null)
        ? null
        : StatusLevel.valueOf(code);
```

**Tier 4: The value after `?` or `:` is itself a long expression** —
enclose the long expression in parentheses and break with operators
aligned/indented relative to the opening parenthesis:

```java
    String result = (condition)
        ? (someVeryLongExpression
           + anotherPart
           + moreParts)
        : (alternativeExpression
           + otherPart);
```

### Boolean Operators

Break before `&&` and `||`:

```java
    if (oldRecord.getStatus() != newRecord.getStatus()
        || !oldRecord.getCategory().equals(newRecord.getCategory())
        || !oldRecord.getPriority().equals(newRecord.getPriority()))
    {
        // ...
    }
```

### Method Chains

Break before the `.` operator, aligning the `.` characters
vertically with the first `.` in the chain:

```java
    String result = builder.toString()
                           .trim()
                           .toLowerCase();
```

If the chain starts too far right for alignment to fit within
80 characters, use continuation indentation instead:

```java
    String result = someVeryLongObjectName
        .getBuilder()
        .toString()
        .trim();
```

### General Continuation Indentation

Continuation lines use **8 spaces** (double indent) from the base
indentation of the statement, consistent with the VSCode formatter's
`continuation_indentation` setting of 2 (2 x 4-space tab size = 8).

---

## Formatted Log and Diagnostic Messages

When log messages or diagnostic output are constructed with
**deliberate alignment** across multiple lines or multiple
statements, use `// CSOFF` and `// CSON` to preserve the
formatting rather than breaking the aligned text to fit 80
characters.

This applies when:

- Labels and separators are visually aligned in the source code
- Column-formatted output where values must line up
- Multi-line usage/help text with intentional indentation
- SQL DDL construction with aligned clauses

**Good use of CSOFF/CSON** — aligned labels and values:

```java
// CSOFF
logInfo("Server status report: ",
        " - - - - - - - - - - - - - - - - - - - - - - - ",
        "    Pending Requests : " + this.queue.getPendingCount(),
        "    Active Workers   : " + this.pool.getActiveCount(),
        "    Idle Time        : " + ((System.nanoTime() - this.lastActivityNanos) / ONE_MILLION) + "ms",
        " - - - - - - - - - - - - - - - - - - - - - - - ");
// CSON
```

Notice how the labels (`"Pending Requests"`,
`"Active Workers"`, `"Idle Time"`) and the `":"` separators
align vertically. Breaking these lines would destroy the visual
alignment that makes the code readable.

**Not needed** — simple single-line log messages that happen to be
long should be broken normally using string concatenation, not
suppressed with CSOFF/CSON:

```java
logWarning("Record " + recordId
    + " has unexpected status: " + status);
```

---

## Javadoc Comments

### Javadoc Line Length

Javadoc comment lines must conform to the 80-character line limit.

### Prose Paragraphs

Reflow prose text to fill lines as close to 80 characters as possible.
Do **not** leave orphaned short words (1-3 words) on a line by
themselves unless it is the very last line of the paragraph.

**Bad:**

```java
    /**
     * The number of milliseconds to sleep between checks on the
     * locks required for
     * tasks that have been postponed.
     */
```

**Good:**

```java
    /**
     * The number of milliseconds to sleep between checks on the
     * locks required for tasks that have been postponed.
     */
```

### Tag Descriptions (@param, @return, @throws)

Tag descriptions follow the same reflow rules. Continuation lines
align with the start of the description text (not the tag keyword):

```java
    /**
     * @param category  The category for the report.
     * @param startDate The start date, or <code>null</code>
     *                  if no start date filter is applied.
     * @return The generated report, or <code>null</code> if
     *         the specified parameter is <code>null</code> or
     *         an empty string.
     * @throws IllegalArgumentException If the specified category
     *         is not a recognized report category.
     */
```

### HTML and Inline Tags

Lines containing `{@link ...}`, `{@code ...}`, `<code>...</code>`,
`<p>`, `<ul>`, `<li>`, `<pre>`, etc. should be treated as part of the
prose flow and not left as orphaned short lines.

---

## Switch Statements

- The opening brace for `switch` goes on the **same line**.
- `case` labels are **left-aligned with the switch** (no indentation
  relative to `switch`):

```java
    switch (value) {
    case FOO:
        doSomething();
        break;
    case BAR:
        doOther();
        break;
    default:
        break;
    }
```

---

## Short-Circuit Conditionals

The single-line / brace-less `if` form is **only** allowed when the
body is a short-circuit control-flow statement: `return`, `continue`,
`break`, or `throw`. Assignments, method calls, and any other body
always use braces — even when the result would fit on one line.

When a **standalone `if`** (no `else`) is used to short-circuit a
method with a short-circuit statement, there are three formatting
tiers based on line length:

**Tier 1: Everything fits on one line** — no curly braces needed
(body must be `return`/`continue`/`break`/`throw`):

```java
    if (param == null) return null;
    if (list.isEmpty()) return Collections.emptyList();
    if (i == 0) continue;
    if (s.length() == 0) break;
    if (input == null) throw new NullPointerException();
```

Bodies that are NOT short-circuit (assignments, method calls) always
use braces, even when they would fit on one line:

```java
    // WRONG — assignment/method call is not short-circuit:
    if (moduleName == null) moduleName = "Sz Repository Manager";
    if (env != null) env.destroy();

    // RIGHT — brace it:
    if (moduleName == null) {
        moduleName = "Sz Repository Manager";
    }
    if (env != null) {
        env.destroy();
    }
```

**Tier 2: Condition + opening brace fit on one line** — curly braces
required since the body is on the next line:

```java
    if (someLongVariableName == someOtherLongVariableName && foo == bar) {
        return false;  // short circuit early
    }
```

**Tier 3: Condition itself exceeds 80 characters** — condition broken
across lines, opening brace on its own line (Allman style), curly
braces required:

```java
    if (someLongVariableName1 == someOtherLongVariableNameOrExpression1
        && someLongVariableName2 == someOtherExpressionOrVarName2)
    {
        return null;  // short circuit early
    }
```

### `if`/`else` pairs always use braces

The single-line / brace-less form is **only** allowed for a
standalone `if` (no `else` or `else if`). When an `else` clause is
present, both branches must use curly braces — even when both bodies
would fit on one line.

**Wrong:**

```java
    if (x == null) doA();
    else doB();

    if (x == null) doA(); else doB();
```

**Right:**

```java
    if (x == null) {
        doA();
    } else {
        doB();
    }
```

The same rule applies to `if` / `else if` / `else` chains — once any
branch has an `else`, every branch is braced.

## Single-Line Statements

Braces may be omitted for a single-line **standalone** `if` (no
`else`) **only** when the body is a short-circuit control-flow
statement (`return`, `continue`, `break`, `throw`) AND the whole
thing fits on one line:

```java
    if (value == null) return null;
    if (index < 0) break;
    if (badInput) throw new IllegalArgumentException();
```

Brace-less form is **not** allowed when:

- The body is an assignment or method call (not short-circuit) —
  even if it fits on one line.
- An `else` clause is present — see "Short-Circuit Conditionals"
  above.

Checkstyle's `NeedBraces` module is configured with
`allowSingleLineStatement = true`, so it permits a wider range of
single-line forms than this project's coding standards. The stricter
project rule above takes precedence.

---

## Indentation

- Basic indentation: **4 spaces** (no tabs)
- Continuation indentation: **8 spaces** (double indent)
- `case` indent relative to `switch`: **0 spaces** (left-aligned)
- `throws` indent relative to method: **4 spaces** (single indent)
- Double-indented parameters: **8 spaces** from method declaration

---

## Checkstyle Suppression

Use inline comment pairs to suppress checkstyle for specific lines:

```java
// CSOFF
<line that intentionally exceeds 80 chars>
// CSON
```

Valid uses:

- Log/diagnostic messages with deliberate visual alignment
  (aligned labels, column formatting, separators)
- Usage/help text with intentional indentation
- SQL DDL construction with aligned clauses
- `package-info.java` ASCII art diagrams
- Long `static final` declarations that cannot be sensibly broken

Do **not** use CSOFF/CSON as a general escape hatch for lazy
formatting.

---

## JUnit Test Conventions

- `@Order` annotation increments by **100** (not 1) to allow
  inserting new tests between existing ones.
- Test classes that capture `System.err` or `System.out` using
  System Stubs must be annotated with
  `@Execution(ExecutionMode.SAME_THREAD)` at the class level to
  prevent race conditions with parallel test execution.

---

## Claude Prompt for Java Formatting

The following prompt can be used with a Claude agent to format Java
files according to these standards. This is intended for cases where
the VSCode formatter's limitations produce incorrect formatting.

---

### Prompt

```text
You are formatting Java source files to comply with the project's
coding standards. The maximum line length is 80 characters.

BRACE PLACEMENT RULES:

1. Allman braces (opening brace on its own line) for:
   - Class, interface, enum definitions (including inner/nested)
   - Method and constructor definitions
   The brace is left-aligned with the start of the declaration.

2. Same-line braces for all control flow and inline blocks:
   - if/else if/else, for, while, do, try/catch/finally
   - switch, synchronized, lambda expressions
   - Array initializers, static initializer blocks

3. EXCEPTION: When an if-condition, catch-specification, or similar
   control flow wraps to multiple lines, the opening brace goes on
   its own line to separate the condition from the body.

4. Closing braces: catch/finally/else/while(do-while) go on the
   SAME line as the preceding closing brace. All others alone.

METHOD DECLARATION RULES (in priority order):

Priority 1: Everything on one line if it fits in 80 chars:
    public String getName()

Priority 2: Parameters aligned to opening paren, one per line,
types aligned vertically, names on first 4-space tab stop after
longest type:
    public SearchResult(ResultCode  resultCode,
                        String      category,
                        String      dataSource)

Priority 3: When paren-alignment exceeds 80 chars, double-indent
parameters (8 spaces from method), types left-aligned, names on
first 4-space tab stop after longest type:
    protected static void registerHandler(
            String                            schemePrefix,
            Class<? extends ProtocolHandler>   handlerClass)

THROWS CLAUSE: Always on its own line, single-indented (4 spaces):
    public void initialize(JsonObject config)
        throws ConfigurationException

Opening brace always left-aligned with the method declaration start.

LINE CONTINUATION:
- Continued lines start with the connecting operator (+, &&, ||,
  ?, :, .)
- Continuation indentation is 8 spaces (double indent)
- For string concatenation, break at + operators
- For ternary, break before ? and :
- For boolean conditions, break before && and ||
- For method chains, break before . and align . chars vertically
  with the first . in the chain; if alignment exceeds 80 chars,
  fall back to continuation indentation

FORMATTED LOG/DIAGNOSTIC MESSAGES:
- When log messages have DELIBERATE ALIGNMENT across multiple
  lines (aligned labels, column-formatted values, aligned
  separators), wrap with // CSOFF before and // CSON after to
  preserve the visual alignment.
- Simple single-line log messages that happen to be long should
  be broken normally with string concatenation — do NOT use
  CSOFF/CSON for those.

JAVADOC:
- Reflow prose paragraphs to fill lines close to 80 chars.
- Reflow @param/@return/@throws descriptions the same way.
- Continuation lines for tags align with the description start.
- Do NOT leave orphaned short words (1-3 words) alone on a line
  unless it is the very last line.

SWITCH:
- case labels left-aligned with switch (no extra indent)

TERNARY OPERATOR (4 tiers by line length):
- Tier 1: Fits on one line — keep it
- Tier 2: Break before ?, keep "? val : val" together
- Tier 3: Break before both ? and :, with : aligned under ?
- Tier 4: If value after ? or : is itself long, enclose in parens
  and break with operators aligned to the opening paren

SHORT-CIRCUIT CONDITIONALS:
- Tier 1: "if (x == null) return null;" — all on one line, no braces
- Tier 2: condition + { fits on one line, return on next, } on next
- Tier 3: condition wraps, { on own line (Allman), return, }

SINGLE-LINE IF:
- "if (x == null) return null;" is allowed (no braces needed)

WHAT NOT TO CHANGE:
- Do not reformat code that already conforms to these rules
- Do not change the logic or behavior of any code
- Do not add or remove imports
- Do not reorder methods or fields
- Do not touch lines inside // CSOFF ... // CSON blocks
```

---

## Scripted Formatting Notes

### Python Scripts Used

Five Python scripts automate bulk formatting. They are stored in
`.claude/scripts/` and can be run from the project root:

#### 1. fix_allman_braces.py — Brace Placement

Moves opening braces from same-line to Allman style for class,
interface, enum, method, and constructor definitions.

**Key logic:**

- Identifies lines ending with `{` (space + brace)
- Classifies as class/interface/enum (by keyword), method/constructor
  (by `) {` ending), or control flow (by keyword prefix)
- Skips control flow, lambdas, anonymous classes, array initializers,
  static initializers, enum constant bodies, continuation lines
  (starting with operators like `||`, `&&`, `+`, etc.)
- For `throws` clauses on the same line as `)`: splits into three
  lines (closing paren, throws clause single-indented, brace at
  method indent)
- For multi-line method signatures where `) {` is on a continuation
  line: scans backward to find the method's base indentation

**Lessons learned:**

- `try (` (try-with-resources) must be recognized as control flow,
  not just `try {`
- Lines starting with operators (`||`, `&&`, `+`, `-`, `?`, `:`, `.`)
  are continuation lines, not method definitions — even if they end
  with `) {`
- `new ClassName(...) {` is an anonymous class body, not a class
  definition
- `CONSTANT("val") {` is an enum constant body
- Closing paren search must go **forward** (first unescaped `)` after
  opening paren), not backward from end of line — otherwise the
  `(Ambiguous)` suffix on match keys captures the wrong paren
- For the brace indentation on multi-line methods: scan backward
  skipping blank lines, comments, and annotations to find a line at
  lower indentation — that's the method's base indent
- An agent incorrectly added a static import for an inner enum
  (`Stat`) that doesn't exist as a top-level class — be careful
  about agents making import changes to "simplify" qualified names

#### 2. fix_javadoc_reflow.py — Prose Paragraph Reflow

Reflows Javadoc prose paragraphs to fill lines close to 80 characters.

**Key logic:**

- Identifies consecutive prose lines (starting with `*` followed
  by a space, no `@` tag, no HTML, no `{@link}` start)
- Joins all words and re-wraps at 80-char boundary
- Only modifies paragraphs where a short line could fit more words
  from the next line

**Lessons learned:**

- Must handle the first line specially (it's already confirmed as
  prose) to avoid infinite loops in the collection loop
- Tag continuation lines (extra-indented after the `*` prefix) should not be
  treated as prose continuations — they belong to `@param` etc.
- Lines where `{@link ...}` or `<code>` appear after a short word
  are NOT tag starts — they're prose with inline tags. The script
  stops the paragraph at `{@` which can leave orphans before them.
  These need manual fixup.

#### 3. fix_javadoc_tags.py — Tag Description Reflow

Reflows `@param`, `@return`, and `@throws` tag descriptions.

**Key logic:**

- Detects `@param name`, `@return`, `@throws Type` tag lines
- Calculates the continuation alignment (description start column)
- Collects continuation lines until a new tag, blank comment line,
  or end of comment
- Joins all words and re-wraps with proper first-line and
  continuation-line prefixes

**Lessons learned:**

- The continuation alignment must match the original description
  start, not a fixed offset
- `@return` has no parameter name, so the regex must handle both
  `@param name desc` and `@return desc` patterns

#### 4. fix_need_braces.py — Short-circuit if collapse / if-else bracing

Fixes brace placement for `if` / `else` patterns. Behaviour depends
on (a) whether an `else` is present and (b) whether the body is a
short-circuit control-flow statement.

- **Standalone `if`** (no `else`):
  - If the body is short-circuit (`return`, `continue`, `break`,
    `throw`) AND the collapsed line fits within 80 chars, collapse
    to a single line `if (cond) body;` (Tier 1).
  - Otherwise (non-short-circuit body, or it doesn't fit) wrap with
    braces (Tier 2).
- **`if` paired with `else`** (or `else if`): always brace both
  branches, regardless of body type or whether the bodies would fit
  on one line. Single-line / brace-less form is never used for
  if/else pairs.

The script also reformats already-inline `if (cond) body;` lines
where `body;` is non-short-circuit (e.g.
`if (moduleName == null) moduleName = "default";`) by adding braces.

**Key logic:**

- Walk each `.java` file looking for both already-inline
  `if (cond) body;` and multi-line `if (cond)\n   body;` patterns
- Recognize `return`/`continue`/`break`/`throw` as the only
  permitted single-line bodies
- For a standalone `if` with a short-circuit body that fits in
  80 chars, collapse to one line; otherwise wrap with braces
- For an `if`/`else` pair, always brace both branches — never single
  line, even when both bodies fit

**Lessons learned:**

- Single-line / brace-less form is reserved for short-circuit
  control-flow only. Assignments and method calls always use braces
  even when they would fit on one line — this keeps the
  control-flow signal visually distinct from ordinary statements.
- Single-line / brace-less form is also reserved for standalone
  `if`. The asymmetric form `if (cond) stmt;\nelse {…}` reads
  poorly, and the symmetric `if (cond) stmt;\nelse stmt;` form
  blurs the structure of the conditional. Always brace both
  branches when an `else` is present.
- Skip lines whose body looks like a sub-construct (`{`, another
  `if`, etc.) to avoid mangling nested control flow

#### 5. fix_javadoc_inline_tags.py — Inline-tag paragraph reflow

Reflows javadoc paragraphs that mix prose with inline tags
(`{@link}`, `{@code}`, `<code>`, …). The base
`fix_javadoc_reflow.py` is conservative and bails the moment a
paragraph contains an inline-tag line; this complement picks those
up.

**Key logic:**

- Same paragraph-detection as `fix_javadoc_reflow.py`, except
  `is_prose_line()` accepts lines that contain inline tags rather
  than rejecting them on the leading-`{@` check
- Reflow proceeds normally once the paragraph is captured
- Still skips block-level HTML (`<p>`, `<pre>`, `<li>`, `<ul>`, …)
  and `@tag` continuation lines, so it does not mangle structured
  javadoc

**Lessons learned:**

- Block-level HTML markers (`<p>`, `<pre>`, `<ul>`, `<ol>`, `<li>`,
  `<table>`, `<tr>`, `<td>`, `<th>`) must still terminate a
  paragraph — otherwise unrelated chunks merge
- `@tag` continuation lines (extra-indented after the `*` prefix)
  must still terminate a paragraph for the same reason

### VSCode Formatter Limitations

The Eclipse-based VSCode Java formatter cannot fully enforce these
standards due to the following limitations:

1. **No per-block-type brace placement**: `brace_position_for_block`
   controls if/for/while/try/catch/synchronized as one group. Cannot
   have Allman for some and same-line for others. Current setting:
   `end_of_line` (same-line for all block types).

2. **No separate synchronized brace setting**: Synchronized blocks are
   lumped into `brace_position_for_block`.

3. **Cannot keep single-statement if-blocks on one line with Allman**:
   The `keep_if_then_body_block_on_one_line` setting only works with
   `end_of_line` brace position.

4. **Does not wrap Javadoc prose**: The formatter handles Javadoc
   structure (indentation, tag alignment) but does not reflow long
   prose lines at 80 characters. Javadoc line wrapping is manual.

5. **Does not reflow @tag descriptions**: Same limitation as prose.

Settings that ARE correctly configured:

- `brace_position_for_method_declaration`: `next_line` (Allman)
- `brace_position_for_type_declaration`: `next_line` (Allman)
- `brace_position_for_constructor_declaration`: `next_line` (Allman)
- `brace_position_for_block`: `end_of_line` (same-line)
- `brace_position_for_switch`: `end_of_line` (same-line)
- `brace_position_for_lambda_body`: `end_of_line` (same-line)
- `brace_position_for_array_initializer`: `end_of_line` (same-line)
- `continuation_indentation`: `2` (= 8 spaces with 4-space tab)
- `keep_then_statement_on_same_line`: `true`
- `indent_switchstatements_compare_to_switch`: `false`
- `lineSplit`: `80`
