<!-- markdownlint-disable MD013 -->
<!--
  MD013 (line-length) is disabled because this document defines the
  80-char rule for Java source — the Markdown prose itself sometimes
  exceeds 80 chars for readability of tables and worked examples.
-->

# Java Coding Standards

This document defines the Java formatting and coding style standards.
These standards are enforced by checkstyle (via the `-Pcheckstyle`
Maven profile) and emitted by the canonical formatter
`tooling/scripts/format_java.py` — a pure-Python AST-based formatter
built on `tree-sitter-java`. IDE integrations (VSCode, IntelliJ)
invoke the formatter as a save-time hook; see the "Tooling" section
at the end of this document.

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
  (see "Formatted Log and Diagnostic Messages" below).

---

## Indentation

- Indentation uses **4 spaces** per level. **Do not use tab
  characters** anywhere in Java source — convert any incoming tabs
  to 4 spaces.
- Continuation indentation: **+4 per wrap level** (cumulating to
  **8 spaces** of displacement for the typical double-wrap case
  — see "General Continuation Indentation" for the full rule)
- `case` indent relative to the enclosing switch block's left anchor:
  **+4 spaces** (case bodies are treated like any other block-scoped
  body — see "Switch Statements and Expressions" for details)
- `throws` indent relative to method: **4 spaces** (single indent)
- Double-indented parameters: **8 spaces** from method declaration

---

## Trailing Whitespace and End-of-File Newline

- Trailing whitespace on any line is forbidden. The formatter strips
  it on every emitted line.
- Every file ends with exactly one `\n` at end-of-file — no trailing
  blank line, no missing terminator.

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

Note: **static and instance initializer blocks** (`static { ... }`
and `{ ... }` at class scope) use **Allman** braces — they are
declaration-level members, not control flow. See "Static and
Instance Initializer Blocks."

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

## Import Organization

Imports are organized into four groups, in this order (top to
bottom):

1. Non-static imports from `java.*` and `javax.*`, pooled and sorted
2. Non-static imports from any other package, sorted
3. Static imports from `java.*` and `javax.*`, pooled and sorted
4. Static imports from any other package, sorted

Within each group, imports are sorted in **case-sensitive lexical
order** (Java's `String.compareTo` semantics). Lexical sort
naturally orders by package name first, then class or static-symbol
name within the package, and naturally orders `java.*` before
`javax.*` because `.` (46) < `x` (120) at position 5.

### Blank lines

- One blank line after the `package` declaration before the first
  import (or before the type declaration if no imports follow).
- One blank line between adjacent non-empty groups.
- Empty groups do **not** introduce extra blanks — no double blank
  lines anywhere in the import block.
- One blank line between the last import and the
  class/interface/enum/record declaration that follows.
- File with no imports: one blank line after `package` before the
  type declaration.

### Wildcard imports

- Allowed in any of the four groups.
- **Convention:** use a wildcard when ≥10 items would otherwise be
  imported from the same package. Never required by the formatter.
- The formatter does not enforce the 10-item heuristic at parse
  time (impossible to determine pre-formatting); it accepts any
  wildcard import as-is and places it in its appropriate group.

### `jakarta.*` namespace

`jakarta.*` (the Jakarta EE successor to the older `javax.*`
namespace) is treated like any other third-party package — it
falls into **group 2** (non-static other), not pooled with
`java.*` / `javax.*`. The java/javax pooling rule covers only
those two specific namespaces; `jakarta.*` sorts alphabetically
alongside everything else in group 2.

### Class-level javadoc placement

The type declaration's javadoc (the `/** ... */` block immediately
above `public class Foo`, etc.) sits directly above the type
declaration with no blank line between the closing `*/` and the
declaration. The blank line required by the import-block rule sits
between the last import and the javadoc opening `/**` (or, if no
javadoc, between the last import and the type declaration itself):

```java
import com.example.Bar;

/**
 * Description of the type.
 */
public class Foo
{
    // ...
}
```

---

## Whitespace and Operator Spacing

| Where                                                                                                                                | Rule                                                                     |
| ------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------ |
| Around binary operators (`+`, `-`, `*`, `/`, `%`, `==`, `!=`, `<`, `>`, `<=`, `>=`, `&`, `\|`, `^`, `<<`, `>>`, `>>>`, `&&`, `\|\|`) | Single space on each side                                                |
| Around assignment operators (`=`, `+=`, `-=`, `*=`, `/=`, etc.)                                                                      | Single space on each side                                                |
| Unary operators (`!`, `-`, `+`, `~`, `++`, `--`)                                                                                     | No space between operator and operand                                    |
| Type casts                                                                                                                           | Single space after closing cast paren: `(Type) value`                    |
| After commas                                                                                                                         | Exactly one space                                                        |
| After semicolons in `for` headers                                                                                                    | Exactly one space                                                        |
| Inside parentheses                                                                                                                   | No leading/trailing space                                                |
| Inside braces (non-empty array/collection initializers)                                                                              | Single space after `{`, single space before `}`: `{ 1, 2, 3 }`           |
| Empty braces                                                                                                                         | `{}` (no space)                                                          |
| Around generic type angle brackets `<>`                                                                                              | No space inside or around: `List<String>`, `Map<K, V>`, `<>`             |
| Wildcards                                                                                                                            | Space after `?` before `extends`/`super`: `? extends Foo`, `? super Bar` |

---

## Annotations

### Annotations on type/method/constructor/field declarations

One annotation per line, each on its own line directly above the
declaration. No blank line between consecutive annotations; no
blank line between the last annotation and the declaration:

```java
@Override
@SuppressWarnings("unchecked")
public List<String> getNames()
{
    // ...
}
```

### Annotations on parameters

Single line if the parameter list fits within 80 characters. When
line-breaking is required, each annotation+type pair stays together
on one line, and parameter names are aligned on the first 4-space
tab stop AFTER the longest **annotation+type combo** (not just the
longest type):

```java
public void register(@NonNull  String    name,
                     @Nullable Locale    locale,
                     long                userId)
```

In the example above, the longest annotation+type combo is
`@Nullable Locale` (16 chars), so names align on the first 4-space
tab stop past 16 = column 20 from the parameter type start. A
parameter without an annotation (e.g. `long`) is treated as having
an empty annotation; its type aligns at the parameter type column
and its name aligns with the others. This rule applies in both
priority 2 (paren-aligned) and priority 3 (next-line
double-indented) parameter placement — substitute "annotation+type
combo" for "type" in the existing alignment text.

### Annotations with arguments

Annotation arguments wrap per the method-call argument rule
(priority 1 single-line, priority 2 two-line paren-aligned
comma-packed, priority 3 paren-aligned one-per-line, priority 4
next-line single-indented one-per-line). Treat `@Annotation(...)`
as a call site for wrapping purposes:

```java
@Operation(summary = "Register a new user account",
           description = "Creates a user, validates uniqueness, "
               + "and persists to the primary store",
           responses = { @ApiResponse(...) })
public void register(...)
{
    // ...
}
```

### Repeated annotations

Java 8+ `@Repeatable` annotations stack the same way as
multi-annotation pairs — one per line above the declaration, no
blank between repeats:

```java
@Schedule(hour = "12")
@Schedule(hour = "18")
@Schedule(hour = "0")
public void runReport()
{
    // ...
}
```

### Type-use annotations

Java 8+ type-use annotations sit inline immediately before the
type they annotate, with a single space between annotation and
type. No additional spacing changes:

```java
public @NonNull String findName(@Nullable String fallback);
public List<@NonNull String> getNames();
```

### Annotations on type parameters and type bounds

Inline, the same as type-use annotations:

```java
public <T extends @NonNull Comparable<T>> T pick(...)
```

### Annotations on parameters whose arguments wrap

When a parameter annotation has arguments that themselves wrap,
the annotation+type pair cannot fit on a single line. The
formatter promotes the parameter list directly to **priority 3**
(next-line double-indented, one parameter per line) — parameters
with multi-line annotations are never paren-aligned. This is an
explicit short-circuit consistent with how text-block arguments
force the next-line form (see "Text Blocks").

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

**Priority 2: Parameters aligned to opening parenthesis** — when
Priority 1 overflows 80 characters, place one parameter per line,
with types aligned vertically to the right of the opening
parenthesis, and names left-aligned on the first 4-space tab stop
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

**Priority 3: Double-indented parameters** — when any single
parameter line under Priority 2 exceeds 80 characters, line-break
before the first parameter and place each parameter on its own line
with double indentation (8 spaces from the method declaration).
Types are left-aligned vertically; names are aligned on the first
4-space tab stop after the longest type:

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

### Varargs

Spacing — `String... args`: no space before the ellipsis, single
space after, no other spacing changes from method-parameter rules.

---

## Class Headers — extends, implements, sealed/permits

### Modifier order

The `permits` clause (for sealed types) goes after `extends` and
`implements` (JLS conventional order):

```java
public sealed class Shape extends GeometricObject implements Drawable
    permits Circle, Triangle, Square
```

`non-sealed` is treated as a regular modifier — no special placement,
no extra spacing or line breaks.

### `extends` and `implements` clause wrapping

**Priority 1: Single line**:

```java
public class Foo extends Bar implements Bax
```

**Priority 2: Both clauses move together** to a single continuation
line, single-indented (4 spaces from class declaration). Both
`extends` and `implements` always move together — never one on the
class line and the other on a continuation line:

```java
public class AMuchLongerNameThanFooThatWillPushThingsToLimit
    extends Bar implements Bax
```

**Priority 3: Each on its own continuation line.** Multiple types
within `implements` (or `extends` on an interface) wrap aligned to
the first type after the keyword (throws-clause style):

```java
public class AMuchLongerNameThanFooThatWillPushThingsToLimit
    extends Bar
    implements LongerNameThanBax1,
               LongerNameThanBax2,
               LongerNameThanBax3
```

**Priority 4: Fallback** — when types don't fit at the paren-aligned
column, line-break before the first type and double-indent each
type on its own line (mirroring the throws-clause priority 4 rule).

### `permits` clause wrapping (sealed types)

Follows the same priority pattern. When the single-line form
overflows, `permits` goes to its own continuation line
single-indented. When the permits-type list itself overflows the
line, types wrap paren-aligned with the first type after
`permits `.

### Combined-clause precedence (extends + implements + permits)

The two clause families are treated independently:

- `extends` + `implements` are **coupled** — they wrap as a unit;
  never one on the class line and the other on a continuation
  line. Splitting them onto separate continuation lines is a last
  resort, used only when the shared continuation line itself
  overflows 80 characters.
- `permits` is **independent** — a different beast that always
  gets its own continuation line when any wrapping happens on the
  class header. Permits never shares a continuation line with
  extends+implements.

**Decision algorithm:**

1. Try the entire header on one line. If fits ≤80, done.
2. Otherwise:
   - **extends+implements placement:** try keeping them on the
     class declaration line. If the combined
     `class Foo extends Bar implements Baz` line fits ≤80, keep
     them there. Otherwise, move both to a single-indented
     continuation line (still together). If even that
     continuation line overflows, split into separate
     continuation lines (extends on one, implements on the next).
   - **permits placement:** try keeping permits on the class
     declaration line — but only if extends+implements also
     stayed there. If extends+implements have moved to a
     continuation OR if the class+permits line would overflow,
     permits goes to its own continuation line single-indented.
     Permits never shares a line with extends+implements when
     any wrapping is in play.

**Worked examples:**

```java
// All fits — single line.
public sealed class Foo extends Bar implements Baz permits A, B, C

// permits doesn't fit; extends+implements stay on class line.
public sealed class FooMaybeLong extends Bar implements Baz
    permits A, B, C

// extends+implements don't fit; both move together to
// continuation; permits gets its own continuation line.
public sealed class FooMuchLonger
    extends Bar implements Baz
    permits A, B, C

// Even extends+implements together don't fit on a continuation;
// each gets its own continuation line; permits also independent.
public sealed class FooMuchLongerStill
    extends ABaseClassWithALongName
    implements LongerInterfaceNameOne, LongerInterfaceNameTwo
    permits A, B, C

// implements types overflow at paren-aligned column; wrap one
// per line at the implements column.
public sealed class FooMuchLonger
    extends Bar
    implements LongerNameThanBax1,
               LongerNameThanBax2,
               LongerNameThanBax3
    permits A, B, C
```

---

## Generic Type Parameters

Spacing — see "Whitespace and Operator Spacing": no space inside or
around `<>`; `<T1, T2>` with comma-space between type parameters;
single space around `extends` keyword in bounds; single space around
`&` in multi-bound.

### Class-level type-parameter list overflow

**Priority 1: Single line** if fits.

**Priority 2: Paren-aligned with first type parameter after `<`.**
Closing `>` at end of last type-parameter line; Allman brace
because the class header is multi-line:

```java
public class AVeryLongClassName<T1 extends Bar,
                                T2 extends Baz,
                                T3 extends Qux>
{
    // ...
}
```

**Priority 3:** push the entire `<...>` to its own line
double-indented (8 spaces from the class declaration), with
each type parameter on its own line at the double-indent
column. Class name remains on the original line; Allman brace:

```java
public class AVeryLongClassName<
        T1 extends Bar,
        T2 extends Baz,
        T3 extends Qux>
{
    // ...
}
```

### Method-level type-parameter list overflow

**Priority 1: Single line** if fits.

**Priority 2:** push the entire `<...>` to its own continuation
line single-indented from the method declaration, with the return
type and method name on the next line single-indented from the
method declaration. The `<...>` and return-type-with-name share
the same indent column:

```java
public <T extends Bar, U extends Baz, V extends Qux>
    T method(List<T> list, U u, V v)
```

**Priority 3:** type parameters paren-aligned with the first type
parameter on the method line; return type and method name on the
next line single-indented:

```java
public <T extends ATypeNameLongerThanBar,
        U extends ATypeNameLongerThanBaz,
        V extends ATypeNameLongerThanQux>
    T method(List<T> list, U u, V v)
```

After the type parameters wrap, the parameter list itself follows
the standard method-parameter rules (priorities 1 / 2 / 3)
independently.

### Bound clause overflow within a single type parameter

When a single bound like
`<T extends VeryLongTypeName & AnotherLongTypeName>` overflows,
break before `&` (binary-operator rule) and align each `&` with the
column where the first bound type started (after `extends `). All
`&` operators align in the same column:

```java
class Foo<T extends VeryLongTypeName
              & AnotherLongTypeName
              & YetAnotherLongTypeName>
```

### Wildcards on long types

Wildcards like `List<? extends VeryLongTypeName>` do not wrap
inside the `<>`. If the line overflows, the surrounding context
(method parameter, generic-type continuation, etc.) wraps. No
special handling for wildcards.

---

## Record Declarations

Record declarations follow the same priority-by-line-length pattern as
method parameter placement, with one extra step: an overflowing
declaration first tries to move the `implements` clause (if any) to its
own line before the field list is wrapped.

### Placement (in priority order by line length)

**Priority 1: Single line** — if the entire declaration fits within
80 characters, keep it on one line:

```java
    public record Foo(String bar) implements Bar;
```

**Priority 2: `implements` on its own line** — if priority 1 overflows,
move the `implements` clause to the next line, single-indented:

```java
    public record Foo(String field1, String field2, String field3)
        implements Bar;
```

**Priority 3: Fields aligned to opening parenthesis** — if priority 2
still overflows, place one field per line aligned to the first column
after the opening parenthesis. Types are left-aligned vertically; field
names are left-aligned on the first 4-space tab stop after the longest
type (mirroring the method-parameter priority 2 rule):

```java
    public record Foo(String      name,
                      int         count,
                      List<UUID>  ids)
        implements Bar;
```

**Priority 4: Fields double-indented on next line** — if any field line
in priority 3 still overflows, line-break before the first field after
the opening parenthesis and double-indent each field (8 spaces from the
record declaration). Types are left-aligned; names are aligned on the
first 4-space tab stop after the longest type (mirroring the
method-parameter priority 3 rule):

```java
    public record Foo(
            String      name,
            int         count,
            List<UUID>  ids)
        implements Bar;
```

### Anti-pattern

Do not break the field list partially, with some fields on the
declaration line and others wrapped beneath:

```java
    // WRONG — hard to read.
    public record Foo(String field1, String field2,
        String field3) implements Bar;
```

The field list either stays entirely on one line (priorities 1–2) or
wraps cleanly with one field per line (priorities 3–4).

### Record compact constructors

A record's compact constructor (`public RecordName { validate(...); }`
form, without an explicit parameter list) uses **Allman brace
placement** per the existing method/constructor rule. Body content
follows standard method-body formatting:

```java
public record RangeSpec(int min, int max)
{
    public RangeSpec
    {
        if (min > max)
        {
            throw new IllegalArgumentException("min > max");
        }
    }
}
```

---

## Enum Constant Bodies

Enum constants can carry constructor arguments and/or anonymous
subclass bodies (constant-specific class bodies). The rules below
apply to both forms and combinations.

### Single-line constant with constructor arguments

When `CONSTANT(arg1, arg2)` fits on one line, keep it on one line.
The blank-line-around-javadoc rule still applies, so the
constant's javadoc sits one blank line above (see "Blank-Line
Rules Between Class Members"):

```java
/** Active state. */
ACTIVE("active", 1),

/** Inactive state. */
INACTIVE("inactive", 0);
```

### Constructor arguments overflow

Arguments follow the method-call argument rule (priority 1
single-line, priority 2 two-line paren-aligned comma-packed,
priority 3 paren-aligned one-per-line, priority 4 next-line
single-indented). Treat the enum constant + its parens like a
method call for wrapping purposes:

```java
// Priority 2 — paren-aligned, comma-packed:
ACTIVE("longer-active-label", 1, 100,
       List.of("primary", "fallback")),

// Priority 3 — paren-aligned, one arg per line:
ACTIVE("longer-active-label",
       1,
       100,
       List.of("primary", "fallback")),

// Priority 4 — next-line single-indented:
ACTIVE(
    "longer-active-label",
    1,
    100,
    List.of("primary", "fallback")),
```

### Constant with anonymous subclass body

Body opening `{` on its own line (Allman). The body is structurally
a class body (an anonymous inner class) and uses Allman braces:

```java
/** Adds two operands. */
PLUS
{
    @Override
    public int apply(int a, int b)
    {
        return a + b;
    }
},

/** Subtracts two operands. */
MINUS
{
    @Override
    public int apply(int a, int b)
    {
        return a - b;
    }
};
```

Constant body method definitions use the standard
method-declaration rules (Allman brace, throws on its own line,
parameter-placement priorities, etc.) — being inside an
enum-constant anonymous body doesn't change their formatting.

### Combination — constructor args AND anonymous body

Args follow the method-call wrap rules; body brace on its own line
(Allman):

```java
/** Plus operator. */
PLUS("plus-operator", 1)
{
    @Override
    public int apply(int a, int b)
    {
        return a + b;
    }
},
```

### Trailing `;` after the last enum constant

The trailing `;` after the last enum constant is **always emitted**
by the formatter, regardless of whether any methods/fields follow.
Java's syntax allows omitting the `;` when nothing follows, but the
project standard is to always include it as a consistent visual cue
that the constants list is closed. (See also the blank-line table
row "Between last enum constant and the `;` separator" in
"Blank-Line Rules Between Class Members".)

When the last constant has no body, `;` ends its line. When the
last constant has a body, `;` attaches to the closing `}` of the
body (no space, same line):

```java
// Last constant has no body — `;` ends its line:
INACTIVE("inactive", 0);

// Last constant has a body — `;` attaches to the closing `}`:
MINUS
{
    @Override
    public int apply(int a, int b)
    {
        return a - b;
    }
};
```

---

## Static and Instance Initializer Blocks

### Static initializer brace placement

Allman style: `static` keyword on its own line, opening `{` on the
next line aligned with `static`'s column, body indented +4, closing
`}` on its own line aligned with `static`. Static initializer
blocks are declaration-level (like methods/constructors), not
control-flow, so they follow the Allman rule:

```java
static
{
    CODES = new HashMap<>();
    CODES.put("A", 1);
}
```

### Instance initializer brace placement

Same as static, just without the preceding keyword. The opening
`{` IS the start of the initializer; closing `}` aligned with the
opening `{`'s column:

```java
{
    this.items = new ArrayList<>();
    this.lock = new Object();
}
```

### Body content

Statements inside follow standard method-body rules: indented +4
from the initializer's brace column, normal statement layout.

### Multiple initializers in one class

Java allows multiple `static { ... }` blocks (or instance
`{ ... }` blocks). Each is a separate member with one blank line
between (see "Blank-Line Rules Between Class Members"):

```java
static
{
    CODES = new HashMap<>();
    CODES.put("A", 1);
}

static
{
    NAMES = new ArrayList<>();
    NAMES.add("foo");
}
```

### Empty initializer

Same Allman shape with no body content:

```java
static
{
}
```

---

## Anonymous Classes

Anonymous class instantiation outside enum-constant contexts (e.g.
`new Runnable() { ... }`, `new Comparator<String>() { ... }`,
listener / SAM-implementation patterns):

- The `new Type(args) {` form keeps the opening `{` **same-line**
  with the `new Type(args)` expression, separated by a single
  space. This differs from class/method declarations (which use
  Allman) but matches the convention: the anonymous class is
  structurally an _expression_ (an instance-creation), not a
  top-level declaration.
- The body inside the anonymous class follows standard rules for
  any class body — method declarations use Allman braces per the
  existing method-declaration rule, fields packed or javadoc'd
  per the blank-line rules, etc.
- The closing `}` of the anonymous class aligns with the column of
  the enclosing statement (where the `new` keyword started) and
  is followed by whatever syntactic terminator the surrounding
  expression requires (`;` for an assignment/call argument list,
  `,` for the next argument, `)` for end of call, etc.).

```java
// Anonymous Runnable used as an argument:
service.execute(new Runnable() {
    @Override
    public void run()
    {
        log.info("starting");
        doWork();
    }
});

// Anonymous Comparator assigned to a local:
Comparator<String> byLengthDesc = new Comparator<String>() {
    @Override
    public int compare(String a, String b)
    {
        return Integer.compare(b.length(), a.length());
    }
};
```

---

## Method Call Arguments

Method calls follow their own priority-by-line-length pattern for
wrapping the argument list. The rules differ from declaration-side
wrapping in two ways: a compact two-line "comma-packed" form is
allowed when the entire argument list fits on two lines, and the
next-line fallback uses single indentation (4 spaces) rather than
the double indentation used by method/record declarations.

### Placement (in priority order by line length)

**Priority 1: Single line** — if the entire call (including any
receiver chain) fits within 80 characters, keep it on one line:

```java
    someVar.someMethod(parameterA, parameterB, parameterC);
```

**Priority 2: Two-line, paren-aligned, comma-packed** — if priority 1
overflows but the entire argument list fits on **exactly two lines**,
break on a comma as late as possible (pack as many arguments as fit
on the call line) and continue the rest on a single continuation
line aligned to the first column after the opening parenthesis:

```java
    someVar.someMethod(parameterA, parameterB1 + parameterB2,
                       parameterC, parameterD);
```

**Priority 3: Paren-aligned, one argument per line** — if the
argument list cannot fit in priority 2's two-line shape, place each
argument on its own line, with all arguments left-aligned to the
first column after the opening parenthesis:

```java
    someVar.someMethod(parameterA,
                       parameterB1 + parameterB2,
                       parameterC,
                       parameterD);
```

**Priority 4: Next-line, single-indented, one argument per line** —
if any single argument is too long to fit on a single line at the
paren-aligned column, line-break before the first argument and place
each argument on its own line with **single indentation (4 spaces)**
from the statement's original indent:

```java
    someVar.someMethod(
        parameterA,
        (parameterB1 + parameterB2 + parameterB3),
        parameterC,
        parameterD);
```

### Anti-pattern

Do not break the argument list partially, with some arguments on the
call line and remaining arguments wrapped beneath at a different
column. The lack of alignment makes it hard to discern distinct
arguments:

```java
    // WRONG — second-line indent doesn't match the paren column.
    someVar.someMethod(parameterA, parameterB1 + parameterB2,
        parameterC, parameterD);
```

The argument list either stays entirely on one line (priority 1),
wraps with paren-aligned continuation (priorities 2–3), or fully
unrolls onto next-line indented arguments (priority 4) — never
mid-form.

---

## Lambdas

### Spacing around `->`

Single space on each side: `x -> body`.

### Parens on single inferred-type argument

Java allows both `x -> body` and `(x) -> body`. The formatter
respects the developer's choice — it does not add or remove parens
around a single argument.

### Block body brace placement

Same-line opening `{` after `->` (matching the existing
same-line-brace rule for control flow). Closing `}` on its own
line at the column where the surrounding statement starts (the
lambda's anchor):

```java
list.forEach(x -> {
    log.info("processing {}", x);
    process(x);
});
```

### Long block bodies

Body inside braces follows standard block rules. Statements
indented +4 from the lambda's anchor.

### Lambda inside a method call — wrap structure

When a lambda is one (or one of multiple) arguments to a method
call AND the overall call doesn't fit on a single line, the call
uses one-argument-per-line shape (single-indent from the call
statement) and the lambda goes on its own line at +4 from the
call statement. Within the lambda:

- Try fitting `(params) -> body` on the lambda's line.
- If `(params) -> body` overflows, move `->` to its own line at
  +4 from the lambda's start (= +8 from the call statement) per
  the universal `->` placement rule (see "Universal arrow
  placement rule" under "Switch Statements and Expressions").
- The body then sits on the `->` line if it fits there, else
  wraps per its own continuation rules (operator continuation
  with parenthesized-expression preference).

```java
// Lambda fits on one line within the call:
compute(
    (int first, int second, long third) -> first + second + third);

// Params fit single-line but `(params) -> body` overflows;
// `->` moves to its own line, body fits on the `->` line:
compute(
    (int first, int second, long thirdAndLongerName)
        -> first + second + thirdAndLongerName);

// Lambda is one arg among multiple in the call; each call arg on
// its own line, lambda following its own rules:
compute2(
    (int first, int second, long thirdAndLongerName)
        -> first + second + thirdAndLongerName,
    secondComputeArg);
```

### Lambda parameter list wraps to multiple lines

When the parameters themselves don't fit on one line, they wrap
per method-declaration rules (paren-aligned with the first
parameter, types vertical, names on the first 4-space tab stop
after the longest type). `->` always goes to its own line in
this case (at +4 from the lambda's start). Body follows its own
rules:

```java
// Params wrap paren-aligned, body single-line:
compute(
    (int    first,
     int    second,
     long   thirdAndLongerName)
        -> first + second + thirdAndLongerName);

// Same param wrap, body is a long unparenthesized expression
// that wraps via standard operator continuation:
compute(
    (int    first,
     int    second,
     long   thirdAndLongerName)
        -> (first + second) * thirdAndLongerName
            / (first - second) * thirdAndLongerName);

// Same param wrap, body is a parenthesized expression;
// continuation aligns paren-aligned per the
// parenthesized-expression rule:
compute(
    (int    first,
     int    second,
     long   thirdAndLongerName)
        -> ((first + second) * thirdAndLongerName
            / (first - second) * thirdAndLongerName));
```

In practice, lambda forms with this much wrapping read more
clearly with a block body and explicit `return`; the rules above
describe the layout when the expression form is used despite the
complexity.

### Lambda as RHS of assignment, return, field initializer

Same shape — `=` then lambda. If body is a block, `{` at end of
line, body indented +4 from statement, closing `}` aligned with
statement start. If lambda's `->` line overflows (e.g. params
alone are long), apply the multi-arg parameter wrap above:

```java
Runnable r = () -> {
    log.info("starting");
    doWork();
};
```

---

## Method References

### Spacing around `::`

No space on either side: `Class::method`, `instance::method`,
`Class::new`, `String[]::new`, `super::method`, `this::method`.

```java
list.stream().map(Integer::parseInt).collect(toList());
list.forEach(this::process);
list.stream().map(String::length).collect(toList());
list.stream().map(MyClass::new).collect(toList());
list.stream().toArray(String[]::new);
```

### Method reference within method-chain wraps

When a fluent chain overflows, break at `.` per the existing
Method Chain rule (vertically align `.` chars; fall back to
single-indent if alignment would push lines past 80). Method
references inside chain calls are just argument values; no
special handling:

```java
// Chain wraps; method refs are argument values:
result = userRepository.findAll().stream()
                                 .filter(this::isActive)
                                 .map(User::getName)
                                 .collect(toList());

// Chain start too far right for dot-alignment — single-indent
// fallback:
result = sessionContextHolder
    .getActiveLocaleService()
    .stream()
    .filter(LocaleService::isEnabled)
    .map(LocaleService::getName)
    .collect(toList());
```

### Long method reference itself

There is no syntactic place to break inside `Class::method`. If
the line containing the reference overflows, wrapping happens in
the surrounding context (the chain's `.` or the enclosing call's
argument list), not inside the reference.

### Method reference with explicit type witness

No space inside `<>`, no space around `::`:

```java
list.stream().collect(Collectors::<String>toList);
result = MyUtility::<String>parseAs;
result = MyUtility::<String, Integer>parseAs;
Supplier<List<String>> supplier = ArrayList::<String>new;
```

### Method reference as method-call argument

Treated like any other argument value; surrounding call uses
standard wrap priorities. Method refs combine naturally with
lambdas, method chains, and regular arguments:

```java
// Priority 1:
service.run(MyClass::cleanup);
list.removeIf(String::isEmpty);

// Call wraps per priority 3 — method ref is just one arg:
service.process(input,
                String::valueOf,
                ErrorHandler::log);

// Mixed with a lambda — lambda per "Lambdas", ref per this section:
service.execute(
    config,
    () -> doWork(),
    ErrorHandler::handle);
```

---

## Text Blocks

### Opening `"""` placement

Java requires the opening `"""` to be followed by a newline, so the
opening always terminates the line that introduces the text block
(after `=`, `(`, `,`, `return`, etc.).

### Closing `"""` placement

The closing `"""` lives on its own line at +4 from the introducing
statement's column (single-indent). Content lines are at the same
column as the closing `"""` or further right:

```java
String json = """
    {
      "name": "Foo",
      "value": 42
    }
    """;
```

### Content preservation

Text block contents are the developer's verbatim string — the
formatter does **not**:

- Enforce 80-character limit inside the block.
- Condense multiple consecutive blank lines (the
  blank-line-condensation rule explicitly excludes text-block
  contents).
- Normalize spacing or alignment of content.
- Reflow content paragraphs.

The formatter only positions the opening and closing `"""` and
ensures the closing's column is consistent. Internal lines are
preserved byte-for-byte.

### Text blocks as method-call arguments

When a method call has a text block as one of its arguments
(whether single or multiple), the surrounding call always uses a
**priority 4 shape** (one argument per line, single-indent from
the call statement) — the formatter does NOT try priority 1/2/3
forms for calls containing a text block argument. The text
block's opening `"""` ends the call line (after `(` for the first
arg, or after `,` for subsequent args). Content lines and closing
`"""` are at +4 from the call statement:

```java
// Single text block argument:
service.executeQuery("""
    SELECT *
    FROM users
    WHERE id = ?
    """);

// Text block as first arg, simple second arg — every arg on its
// own line at +4:
service.executeQuery("""
    SELECT *
    FROM users
    WHERE id = ?
    """,
    userId);

// Multiple args including a text block, all on their own lines:
service.executeQuery("""
    SELECT *
    FROM users
    WHERE id = ?
    """,
    userId,
    IsolationLevel.READ_COMMITTED);
```

**Convention:** text blocks used directly inline as method-call
arguments tend to be visually cluttered. Prefer hoisting the text
block into a `final` local variable first and then passing the
variable. The above rule applies when the inline form is
unavoidable.

### Text block as RHS of assignment, return, or condition

Same opening-`"""`-ends-the-line, closing-`"""`-at-+4 rule.
Closing `"""` is followed by `;` or `,` or `)` etc. as the syntax
requires:

```java
String json = """
    {
      "name": "Foo"
    }
    """;

return """
    Hello,
    World
    """;
```

### Empty text block

The minimum text block is two source lines: opening `"""` ends
one line, closing `"""` is on the next line, with no content
between:

```java
String empty = """
    """;
```

This produces an empty string. No special formatting handling is
required beyond the standard opening/closing rules above.

---

## Line Continuation

When a line exceeds 80 characters and must be broken, the continued
line should begin with proper indentation and the **operator** that
connects it to the previous line.

### String Concatenation

Break at `+` operators, with the `+` starting the continuation
line. Two shapes apply depending on the chain's pattern.

**Greedy packing (default).** Pack as many `+ operand` pairs per
continuation line as fit within 80 chars; break at the operator
boundary when adding the next pair would overflow:

```java
    throw new IllegalArgumentException(
        "Cannot specify a secondary value when "
            + "the primary value is null.  primary=[ "
            + primary + " ], secondary=[ " + secondary + " ]");
```

**Label/value pair-aligned (canonical `toString()` pattern).**
When a `+` chain alternates string ↔ non-string and each
subsequent string literal carries a delimiter-prefix character
from `{" ", ",", ";", "]", ")", "}", "|", ":"}` — the canonical
Senzing diagnostic message "label=[ value ]" pattern — the
formatter breaks before each subsequent label so every
continuation line carries one `label + value` pair:

```java
    return "name=[ " + name
        + " ], age=[ " + age
        + " ], status=[ " + status
        + " ]";
```

The first label literal is the line anchor and doesn't need a
delim prefix — the gate is "lenient" in that regard. The shape
applies in both grouping-paren context (where labels paren-align
under the `(`) and at the +4 indent (no governing paren).

**Multi-row-inner-forces-outer-break invariant.** If an operand's
own emit introduced newlines (a nested call's arg list wrapped,
a parenthesized binary wrapped, etc.), the subsequent `+`
operator MUST break to a new line. Without this, the operator
would visually merge with the wrapped operand's tail at the same
column, stranding the chain. This applies to greedy, pair-
aligned, and paren-aligned shapes uniformly.

### Ternary Operator

**Tier 1: Fits on one line** — keep it on one line:

```java
    int x = (num == null) ? 0 : num.intValue();
```

Tier 1 also requires that no nested emit introduced newlines —
a ternary whose consequence or alternative contains a multi-row
construct (long binary that wrapped, nested call that wrapped)
is NOT eligible for Tier 1 even if the total width happens to
fit, because the resulting layout is not really "single-line."
When the newline-detection gate rejects Tier 1, the cascade
falls to Tier 2 (and onward) at the appropriate continuation
column.

**Tier 2: Condition + `?` value + `:` value exceeds 80 chars but
`?` value fits** — break before `?`, keep `? value : value` together:

```java
    String text = (index == text.length() - 1)
        ? "" : text.substring(index + 1);
```

If the consequence wraps multi-row (e.g. it's a long binary
chain that pair-aligns onto multiple lines), the `:` also breaks
to a new line at the same continuation column as `?` — applying
the multi-row-inner-forces-outer-break invariant to the
`?` → `:` boundary. T2 morphs into a T2/T3 hybrid as needed:

```java
    return ((flag)
            ? "name=[ " + name
            + " ], count=[ " + count
            + " ]"
            : "no data");
```

Inside a governing `(`, the ternary's `?` and `:` continuation
column is `paren_align_col` (the column after the governing
`(`), and that paren-align context is inherited by any binary
expression appearing inside the consequence or alternative — so
the inner `+` continuations line up under the same column the
`?` / `:` use.

**Tier 3: `? value : value` itself exceeds 80 chars** — break before
both `?` and `:`, with `:` aligned under `?`:

```java
    StatusLevel statusLevel = (code == null)
        ? null
        : StatusLevel.valueOf(code);
```

**Tier 4: The value after `?` or `:` is itself a long expression** —
enclose the long expression in parentheses and break with operators
aligned/indented relative to the opening parenthesis. This is a
specific application of the more general
"Parenthesized-Expression Continuation" rule documented below:

```java
    String result = (condition)
        ? (someVeryLongExpression
           + anotherPart
           + moreParts)
        : (alternativeExpression
           + otherPart);
```

### Boolean Operators

Break before `&&` and `||`. When the boolean expression is wrapped
in grouping parentheses, operator continuation aligns under the
column after the opening paren — see
"Parenthesized-Expression Continuation" below for the general rule.

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

**Same-method greedy packing.** When every segment in the chain
calls the same method name AND the chain has an explicit
receiver (the canonical `sb.append(x).append(y).append(z)`
builder pattern), the formatter packs as many `.METHOD(args)`
segments per continuation line as fit, instead of strict
one-per-segment dot-alignment. The continuation column remains
the dot-aligned column; the segments just pack horizontally
until the next would overflow:

```java
    StringBuilder sb = new StringBuilder();
    sb.append("Status: ").append(status).append(", count: ")
      .append(count).append(", details: ").append(details);
```

Mixed-name chains (`.builder().setReader().get()`) keep the
strict one-per-segment shape — the greedy gate doesn't fire
because the segments have different semantics and benefit from
vertical alignment.

If the chain starts too far right for alignment to fit within
80 characters, use continuation indentation instead:

```java
    String result = someVeryLongObjectName
        .getBuilder()
        .toString()
        .trim();
```

### General Continuation Indentation

The continuation indent is **+4 spaces per wrap LEVEL** — not per
continuation **LINE**. Multiple continuation lines at the same wrap
level all share the same indent. The "cumulative" word refers to
nesting one wrap level inside another (a deeper construct that
itself wraps), not to stacking successive operator continuations
within a single wrap.

**Worked example** (CORRECT):

```java
result = service.executeWithFallback(
    "primary failed: "
        + describeFailureFunctionWithLongerName(input)
        + " " + describeInputs(input));
```

| Wrap level                           | Content                                 | Indent                  |
| ------------------------------------ | --------------------------------------- | ----------------------- |
| 0 — statement base                   | `result = service.executeWithFallback(` | column 0                |
| 1 — call arg list wraps to next-line | `"primary failed: "`                    | +4                      |
| 2 — string-concat operator breaks    | `+ describe...(input)`                  | +8                      |
| 2 — same string-concat continues     | `+ " " + describe...`                   | +8 (aligned with prior) |

Both `+` continuation lines are at +8 — they belong to the same
wrap level (the string-concat inside the call arg). Only a NEW
wrap level (e.g. one of those `+` operands itself wrapped because
it was a long expression) would add another +4.

**Anti-pattern** (WRONG):

```java
result = service.executeWithFallback(
    "primary failed: "
        + describeFailureFunctionWithLongerName(input)
            + " " + describeInputs(input));
```

The second `+` line here is at +12 — that would be correct only
if it opened a new wrap level (it doesn't).

**Worked example, deeper nesting** (lambda body inside call):

```java
compute(
    (int    first,
     int    second,
     long   thirdAndLongerName)
        -> (first + second) * thirdAndLongerName
            / (first - second) * thirdAndLongerName);
```

| Level | Content                                               | Indent   |
| ----- | ----------------------------------------------------- | -------- |
| 0     | `compute(`                                            | column 0 |
| 1     | `(int first, ...` (lambda inside call)                | +4       |
| 2     | `-> ...` (arrow on own line within lambda)            | +8       |
| 3     | `/ (first - second) ...` (body operator continuation) | +12      |

**Edge case — when cumulative indent itself exceeds 80**: the
emit-and-warn rule from "Wrap Behavior — Cross-Cutting Rules"
applies. In practice
deep wraps that overflow are a signal to extract intermediate
locals (a `final String message = "..."; service.use(message);`
is usually clearer than 4 levels of nested wrap anyway).

### Parenthesized-Expression Continuation (governing `(`)

When an expression sits inside a **governing `(`** — the column
immediately after that `(` becomes the operator-continuation
anchor — operator continuation aligns under that column if it
doesn't itself overflow 80 chars; otherwise it falls back to the
standard cumulative +4 indent rule.

**What counts as a governing `(`:**

1. **Grouping parentheses** — `(a + b + c)` written explicitly by
   the developer to group an expression. This was the only case
   in 0.4.x; 0.5.0 extends to the cases below.
2. **Control-flow required parens** — the syntactically-required
   parens of `if (cond)`, `while (cond)`, `for (...)`,
   `synchronized (...)`, `switch (...)`. A multi-line condition
   / clause aligns its operator continuations under the column
   after the `(`. (`catch (...)` is grammatically the same shape
   but its contents are a type list + name, not an expression
   with operator continuation, so the rule has no practical
   effect there.)
3. **For-statement clause parens** — the `for (init; cond; update)`
   header re-anchors each clause (initializer / condition /
   update) to the column after the `(` when the header wraps
   multi-line.
4. **Single-arg method/constructor call parens whose argument is
   a binary expression** — `super("..." + foo() + "...")`,
   `throw new IllegalArgumentException(msg + arg)`, etc. The
   inner binary aligns its operator continuations under the
   column after the call's `(`. Restricted to single-arg binary
   args; multi-arg call parens, lambda args, method-chain args,
   and object-creation args do NOT engage this rule (they use
   their own per-construct wrap shapes).

This applies to ALL operators (`+`, `-`, `*`, `/`, `&&`, `||`,
`?`/`:` in ternaries, etc.) and to nested constructs:

```java
// String concat in grouping parens — operator aligns under (:
result = ("active state with details: "
          + describeDetails(input));

// Ternary expression in grouping parens — both ? and : align under (:
String status = (level >= 3 ? "high"
                : level >= 1 ? "medium"
                             : "low");

// Boolean expression in if-condition — && / || align under (:
if (firstCondition
    && secondCondition
    && thirdCondition)
{
    foo();
}

// For-statement clauses align under for's (:
for (int readCount = source.read(buf);
     readCount >= 0;
     readCount = source.read(buf))
{
    sink.write(buf, 0, readCount);
}

// Single-arg binary call paren — inner + aligns under super's (:
super("prefix " + value
      + " suffix");

// Falls back to cumulative +4 indent when paren-alignment itself
// overflows:
result = ("a very long string that starts deep inside many wrappers"
        + describeDetails(input)
        + describeOrigin(input));
```

**What does NOT count as a governing `(`:**

- **Multi-arg method-call parens** — `f(a, b, c)` argument lists
  use the priority 1–4 argument-wrap rules (single-line /
  two-line packed / paren-aligned one-per-line / next-line
  single-indent), not paren-aligned operator continuation.
- **Single-arg lambda / method-chain / object-creation args** —
  `.execute(() -> ...)`, `.then(chain.of.calls())`,
  `f(new Bar(...))`. These constructs have their own
  per-construct wrap shapes that the call paren shouldn't
  override.

The non-parenthesized form (no governing `(` in any of the four
cases above) continues to use the standard cumulative +4 rule.

**Shallow-operand rejection.** When a paren-aligned chain's
inner operand wraps to a column SHALLOWER than the chain's own
operator-continuation column (e.g. an inner method call's
arg-list wraps via emit_p4 at `block + 4` while the chain is
paren-aligned at a much deeper governing-`(` column), the
paren-aligned shape is rejected and the chain falls back to the
+4 cascade where the operand typically fits single-line.
Prevents the visual-escape pattern where an operand's body
"escapes" left past the chain's anchor.

---

## Cuddled `else` / `catch` / `finally` / `while` (do-while)

The closing `}` of a preceding block is followed by a single space
and the next keyword (`else`, `else if`, `catch`, `finally`,
`while` in do-while). The keyword always shares a line with the
closing `}`. This holds whether the _previous_ block's condition
was single-line or multi-line:

```java
} else {
} else if (cond) {
} catch (IOException e) {
} finally {
} while (cond);
```

### Opening brace placement for the new block

The opening brace placement of the NEW block (after `else if` /
`catch`) depends on **its own** condition shape:

- If the next block's condition fits on a single line, the
  opening `{` stays same-line (same-line-brace rule).
- If the next block's condition itself wraps to multiple lines,
  the opening `{` for that block goes Allman (on its own line),
  per the multi-line-condition rule.

For `else` and `finally`, which have no condition, the opening
`{` is always same-line: `} else {`, `} finally {`.

### Worked examples

```java
// Single-line conditions throughout — all cuddled, all
// same-line opening braces:
if (cond) {
    foo();
} else if (otherCond) {
    bar();
} else {
    baz();
}

// First if's condition wraps; the `}` and `else if` still
// cuddle — and because the else-if condition wraps too, the
// else-if's opening { goes Allman:
if (oldRecord.getStatus() != newRecord.getStatus()
    || !oldRecord.getCategory().equals(newRecord.getCategory()))
{
    foo();
} else if (oldRecord.getPriority() != newRecord.getPriority()
           || oldRecord.getOwner() != newRecord.getOwner())
{
    bar();
} else {
    baz();
}

// try/catch/finally — same rule. Single-line catch condition
// stays cuddled with same-line brace; multi-line catch (multi-
// type catch wrap) cuddles the `} catch` but uses Allman
// brace because catch's condition is multi-line:
try {
    risky();
} catch (IOException e) {
    log.error("io", e);
} finally {
    cleanup();
}

try {
    risky();
} catch (FileNotFoundException
         | AccessDeniedException
         | InterruptedIOException
         | TimeoutException e)
{
    log.error("filesystem", e);
} finally {
    cleanup();
}

// do/while — `} while` cuddles. Long condition wraps; closing
// `}` still cuddles with `while`:
do {
    foo();
} while (cond);

do {
    foo();
} while (firstCondition
         && secondCondition
         && thirdCondition);
```

---

## Labels and Labeled break/continue

Java loop/block labels:

- **Label** (`outer:`, `processing:`, etc.) appears on its own
  line at the column of the labeled statement (the `for` /
  `while` / `do` keyword's column).
- **Labeled `break LABEL;` / `continue LABEL;`** uses a single
  space between the keyword and the label name.
- No blank line required between the label and its statement; no
  blank line required between the label and preceding code
  (though a blank line is permitted for visual separation).

```java
outer:
for (int i = 0; i < n; i++) {
    for (int j = 0; j < m; j++) {
        if (matrix[i][j] < 0) {
            break outer;
        }
        if (matrix[i][j] == SKIP) {
            continue outer;
        }
    }
}
```

---

## Blank-Line Rules Between Class Members

### Member-level rules

| Boundary                                                                  | Rule                                        |
| ------------------------------------------------------------------------- | ------------------------------------------- |
| Right after class opening `{` (before first member)                       | No blank                                    |
| Right before class closing `}` (after last member)                        | No blank                                    |
| Between consecutive constructors                                          | One blank line                              |
| Between consecutive methods                                               | One blank line                              |
| Between method and inner class (either order)                             | One blank line                              |
| Between consecutive inner classes / nested types                          | One blank line                              |
| Around static initializer blocks                                          | One blank line on each side                 |
| Around instance initializer blocks                                        | One blank line on each side                 |
| Between last field and first non-field                                    | One blank line                              |
| Between last enum constant and the `;` separator                          | No blank — `;` directly after last constant |
| Between the `;` (after enum constants) and the first method/field, if any | One blank line                              |

### Javadoc-driven blank-line rule

The rule below applies to fields and enum constants: every javadoc
block within a class/enum body has a blank line immediately above
it, separating it from the previous member. Fields and enum
constants with no leading javadoc pack together with no blank line
between them.

| Member shape                                               | Layout                                                                                                                                                      |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Non-private field with javadoc                             | One blank line above the `/**` opening                                                                                                                      |
| Private field with javadoc (allowed but not required)      | One blank line above the `/**` opening                                                                                                                      |
| Adjacent fields without javadoc (typically private)        | No blank — packed                                                                                                                                           |
| Non-private enum constant (always javadoc'd by convention) | One blank line above the `/**` opening                                                                                                                      |
| Private nested utility enum constants (no javadoc)         | Single line if all constants fit within 80 chars (e.g. `private enum Mode { QUIET, NORMAL, VERBOSE; }`); otherwise one constant per line, no blanks between |

**Convention note:** non-private fields and non-private enum
constants should be individually javadoc'd describing their
purpose. This is a coding convention (suitable for checkstyle
enforcement); the formatter only handles the resulting blank-line
layout. Javadoc on private fields is allowed but not required.

### Inner-body blank-line normalization

Multiple consecutive blank lines anywhere in the source — except
inside triple-quote text block literals (`"""..."""`) — are
condensed by the formatter to a single blank line. Text block
contents are preserved verbatim.

---

## Wrap Behavior — Cross-Cutting Rules

These rules apply to every wrappable construct in this document
(method parameters, method-call arguments, record fields, throws
clauses, implements/permits lists, multi-catch types, switch
multi-label, lambda parameters, generic type parameters, array
initializers, etc.).

### Wrap Priority Engine

Every wrappable construct in this document is emitted through a
single priority-cascade engine. Each construct declares an ordered
list of **candidate shapes** (single-line, paren-aligned, next-line
single-indent, etc.). The engine commits the **first candidate
whose rendered output fits** within the line-length budget; if all
candidates overflow, the engine commits the last candidate anyway
per the **emit-but-warn** rule (see "When wrap rules can't bring
a line under 80").

**How the budget is computed.** The budget for any wrap decision
is `_MAX_LINE` (80) minus a **tail reserve** that accounts for
trailing tokens the candidate cannot see — the `;` after an
expression statement, the `)` closing an enclosing parenthesized
expression, the `) {` after an `if` / `while` / `for` condition,
the trailing `.method(args)` after a chain's receiver, and so on.
Each enclosing construct bumps the reserve before emitting its
inner expression and restores it afterwards. The composition is
additive: an `if (binary && other) {` reserves `2 + 1 = 3` chars
(`) {` from the `if`, `)` from the paren-expression that holds
the condition), so the binary expression's wrap engine treats the
effective max as 77 even though no character past column 77 has
yet been written.

**Speculative emission.** Candidates emit their full shape into
the buffer; the engine measures the resulting line widths and,
on overflow, rolls back the buffer and tries the next candidate.
This means a wrap decision is a function of the **rendered**
widths — including any nested wraps that fired during the
candidate's emission — not of the source-text widths. Different
input layouts that parse to the same AST produce the same output,
which is what makes the formatter idempotent.

**Cumulative continuation indent.** Each wrap level adds 4 spaces
of continuation indent on top of the surrounding context. Multiple
continuation lines at the same wrap level share the same indent;
only entering a deeper wrap level adds another 4. The full rule
and worked examples are in "Line Continuation / General
Continuation Indentation" above.

### Multi-row inner forces outer break

When emitting a chain or wrappable construct, if an inner
operand / clause's own render introduced newlines (a nested call
that wrapped, a parenthesized binary that wrapped, etc.), the
next separator (operator, comma, `:`) MUST break to a new line
before being emitted. Without this, the separator visually
merges with the wrapped inner's tail at the same column,
"stranding" the chain at a confusing position.

This invariant applies uniformly to:

- Binary expression cascades (greedy, pair-aligned, paren-
  aligned) — explicit anti-stranding check: break before the
  next `+` / `-` / `*` / etc. when the previous operand
  wrapped.
- Ternary expressions — explicit check: break before `:` when
  the consequence wrapped, even in Tier 2 (T2 morphs into a
  T2/T3 hybrid).
- Method chains — explicit check (in both the standard P2 and
  the same-method greedy P2 candidate): break before the next
  segment when the previous segment's argument list wrapped
  multi-row.
- Argument lists — anti-stranding is handled implicitly by the
  per-arg `widths_ok` width gate during speculative packing,
  not by an explicit "previous arg wrapped → break" branch.
  When a prior arg's emission wraps, the next pack-attempt
  usually overflows the current line and falls back to a new-
  line break naturally. This gives the same end-result as the
  explicit check, but the mechanism is different.

This is the same anti-stranding principle that 0.4.3's Bug 1 fix
applied to method chains, generalized across constructs.

### Wrap promotion is all-or-nothing

When **any** item in a wrappable list would overflow at the
current priority's column, the formatter promotes **all** items
in that list to the next priority's form. Wrap shape is uniform
within a single declaration / call / clause — never mixed (some
items on the open line, others wrapped at a different indent
beneath).

Practical implication: when emitting a wrappable list, the
formatter must compute whether ALL items fit at the current
priority's column; if any item would push a line past 80 chars,
the entire list moves to the next priority's form.

**Carve-out for two-line packed shapes.** Some constructs have a
distinct "two-line packed" priority (multi-catch priority 2 with
`|`-packed types across two lines; method-call priority 2 with
comma-packed args across two lines). These are not partial-mix
anti-patterns — they are intentional, fully-specified shapes
defined for the case where the entire item list fits on exactly
two lines. The all-or-nothing rule applies at the transition
_from_ those two-line packed forms to the one-per-line form
(priority 3), and from priority 3 to next-line-indented (priority
4). Within the two-line packed shape, the break point is the
latest separator that keeps both lines under 80 — that's a fixed
mechanical rule, not a partial wrap.

### Method-call priority 2 — "exactly two lines" definition

The two-line, paren-aligned, comma-packed form applies when the
entire argument list — from after the call's opening `(` through
and including the closing `)` — spans **exactly two source lines**.
The call's `methodName(` ends the first line; the closing `)`
ends the second line.

The break point is the **latest comma** at which both resulting
lines fit ≤80 characters (paren-aligned continuation column on
the second line). If no such comma exists, priority 2 does not
apply and the formatter promotes to priority 3 (one arg per line).

**Edge-case clarifications:**

- The closing `);` / `),` / `)` syntax (whichever the surrounding
  context requires) counts as part of the second line.
- A call with exactly two arguments where neither fits with the
  other on the first line is still priority 2 (mechanically, the
  comma-packed form with the break landing on the only comma).
- When BOTH priority 2's two-line shape AND priority 3's
  one-per-line shape would fit, the formatter chooses priority 2
  (higher priority). Priority 3 only applies when two-line
  doesn't fit.
- When the comma-packed second line lands exactly at 80
  characters (including the closing `);`), it counts as fitting
  — priority 2 applies.

### When wrap rules can't bring a line under 80

When the longest type name (or expression, or label) is itself so
long that even the last-resort priority still produces lines >80
characters, the formatter **emits the last-resort form anyway** —
it does NOT auto-add `// CSOFF`/`// CSON` suppression or
otherwise hide the violation.

Rationale: `// CSOFF`/`// CSON` markers preserve their signal
value ("deliberately aligned, do not auto-format") only if the
formatter doesn't auto-emit them. Auto-suppression would also
hide the underlying issue — the developer wouldn't be prompted to
shorten/rename the type or restructure.

**Formatter behavior:** emit a warning to stderr when any line
remains >80 chars after applying all wrap rules:

```text
WARNING: <path>:<line> — <length> chars after final wrap.
Type '<offending-type-name>' is the constraint.
Consider renaming, extracting, or adding `// CSOFF`/`// CSON`
manually.
```

A bulk-format run aggregates these warnings into a punch-list at
the end so the developer sees a summary rather than scrolling
through per-file output. The developer then decides: rename the
type, extract a type alias, restructure the method, or add
explicit `// CSOFF`/`// CSON` markers. **No `--auto-csoff` flag**
— auto-adding suppression is not an option the formatter offers.

This "emit but warn" behavior applies analogously to all
constructs where wrap rules can't bring lines under 80 (multi-
catch priority 3, switch-case-multi-label priority 2, long single
exception in throws clause, etc.).

**Wrap-engine overflow advisories.** Each wrap engine (binary
expression, ternary expression, method chain, argument list)
fires a `FormatterWarning` when its last-resort candidate
commits a layout whose on-disk widths exceed 80 chars. The
advisory points at the source site so the developer knows
which literal / operand to split. Speculative emits earlier in
the cascade that overflowed but rolled back don't fire — only
the committed candidate's advisory persists.

**Source-preservation with no fallback.** When the formatter
encounters an argument list whose source already wraps multi-
line, it may preserve the developer's layout verbatim
(re-anchoring continuation columns at the canonical
`paren_align_col + 4` or `block + 4` target). If the re-anchored
layout still overflows 80 chars (because a contained string
literal or expression is itself too long), the formatter fires
the advisory and emits anyway — it does NOT fall back to a
shallower column or to raw verbatim. The overflow becomes a
checkstyle LineLength violation the developer must resolve by
splitting the offending literal at a word boundary, extracting
a long expression to a local variable, or restructuring. This
breaks the propagation cycle where source-preserved verbatim
layouts silently re-appeared each format pass.

---

## Miscellaneous Clarifications

### Comment placement

**Above-statement comments** (single-line `//` or block `/* */`):
no blank line between the comment block and the statement it
documents. Multiple stacked comment lines are preserved together:

```java
// This handles the negative-balance case.
if (balance < 0) {
    rejectTransaction();
}
```

**End-of-line side comments**: exactly two spaces between the end
of code and `//`, then a single space after `//`:

```java
balance -= fee;  // strip transaction fee
```

**Inline `/* */` comments** (typically used as parameter
documentation hints): standard spacing — space before and after:

```java
result = compute(/* timeoutMs= */ 5000, /* retry= */ true);
```

### Line Comment Reflow

A `//` line comment that starts at the current indent column
and would render past 80 characters is **greedy-reflowed** into
multiple `// `-prefixed lines at the same indent. Each
reflowed line carries the `// ` prefix so the result re-parses
as a sequence of individual `line_comment` nodes — that's
what keeps the reflow idempotent across passes.

**Greedy fill** — words are placed onto each line until the
next word would exceed the budget; the next word starts a new
line at the same column.

```java
// Before:
                    // this comment is exceptionally long and exceeds the eighty character budget by a wide margin

// After:
                    // this comment is exceptionally long and exceeds the eighty
                    // character budget by a wide margin
```

**Exemptions — these comments are NEVER reflowed:**

- **Checkstyle / suppression directives** — the meaning of
  these markers depends on a single-line shape that pairs with
  a matching marker elsewhere in the file. Any comment whose
  content begins with one of these tokens is preserved as-is:

  - `CSOFF` (and its closing `CSON`)
  - `CHECKSTYLE:OFF` (and its closing `CHECKSTYLE:ON`)
  - `SUPPRESS` (e.g. `// SUPPRESS CHECKSTYLE …`)

- **`@`-prefixed tags** — any comment whose content begins
  with `@`. The exemption is intentionally broad (it covers
  `// @snippet`, `// @param`, `// @SuppressWarnings`-style
  markers, `// @author` notes, tool-specific `@`-prefixed
  pragmas, etc.) — the assumption is that any `@`-token
  carries syntactic meaning the developer placed deliberately,
  and reflowing the comment could split the tag from its
  argument across lines.

- **URLs** — any comment containing `://` is preserved
  verbatim. Splitting a URL on whitespace would mangle it; the
  trade-off is that URL-bearing comments may exceed 80 chars.
  Wrap the URL in a `<code>` block inside javadoc if the URL
  is documentation rather than an inline note.

**No paragraph merge.** Consecutive `//` comments are reflowed
**independently**, never merged into a single paragraph. The
developer might have authored adjacent comments that document
distinct things, and merging them would conflate unrelated
text. If a logical paragraph needs reflow as a unit, use a
javadoc `/** */` block (which IS reflowed as a paragraph).

**Side comments (end-of-line `// …`)** are NOT reflowed — they
are tied positionally to the preceding code on the same line,
and shifting them to additional lines below would break that
association. A side comment that would push the line past 80
characters is left as a LineLength violation for the developer
to address (rephrase the comment, shorten the code, or hoist
the comment to its own line above the statement).

### Array initializers

Array literals `{ … }` follow a four-priority cascade. The exact
cascade depends on the context (assignment vs. embedded) and on
whether the RHS is a bare literal or an `array_creation_expression`
(`new Type[] { … }`).

#### Assigned context — bare literal RHS (`Type x = { … };`)

Cascade in priority order:

**Priority 1** — single line:

```java
String[] labels = { "A", "B", "C" };
```

**Priority 2** — break BEFORE the `=`, array literal fits on the
continuation line at block+4:

```java
String[] labels
    = { "firstItem", "secondItem", "thirdItem", "fourthItem" };
```

**Priority 3** — `= {` on the LHS line, elements greedy-packed
across multiple continuation lines at block+4, `};` on its own
line at the LHS indent. Middle continuation lines must carry at
least two elements each; the LAST continuation line may carry a
single element:

```java
String[] labels = {
    "firstItem", "secondItem", "thirdItem", "fourthItem", "fifthItem",
    "sixthItem", "seventhItem", "eighthItem", "ninthItem", "tenthItem"
};
```

**Priority 4** — one element per line. Fires when Priority 3 would
place a single element on a middle line, or when any individual
element is too long to share its line with another:

```java
String[] labels = {
    "someReallyLongFirstItemNameThatTakesSoMuchSpace",
    "anotherLongerName",
    "aShortThirdItem"
};
```

#### Assigned context — `new Type[] { … }` RHS

**Priority 2 is skipped.** Cascade: Priority 1 → Priority 3 →
Priority 4. Rationale: moving `= new Type[] {` onto a
continuation line at block+4 consumes so much horizontal budget
that the elements themselves usually cannot fit — the break
sacrifices too much line budget for the sake of a consistent
break-before-operator shape. Jumping straight to Priority 3
keeps `= new Type[] {` on the LHS line and gives elements the
full block+4 budget.

```java
args = new String[] {
    "--port", "9080", "--interface", "localhost"
};
```

#### Unassigned context (return value, argument, annotation value)

No `=` to break before, so Priority 2 is not applicable. Cascade:
Priority 1 → Priority 3 → Priority 4.

```java
return new String[] {
    "firstItem", "secondItem", "thirdItem", "fourthItem", "fifthItem",
    "sixthItem"
};
```

Spacing inside `{ }` follows "Whitespace and Operator Spacing"
(single space inside non-empty braces; `{}` for empty).

### Multi-dimensional arrays

- **Declaration**: `int[][] grid` — brackets adjacent to type, no
  spacing between brackets.
- **Allocation with sizes**: `new int[m][n]` — no spaces inside
  brackets, no spaces between brackets.
- **Nested initializers**: the OUTER initializer skips Priority 3
  (greedy pack of sub-arrays) and jumps straight to a
  one-sub-array-per-line layout for readability. Each SUB-ARRAY
  then recursively applies its own cascade (Priority 1 → Priority
  3 → Priority 4 — Priority 2 does not apply to sub-arrays because
  they have no owning `=`).

**Priority 1** — everything fits on one line:

```java
int[][] matrix = { { 1, 2, 3 }, { 4, 5, 6 }, { 7, 8, 9 } };
```

**Priority 2** — break BEFORE the `=`, whole array fits on one
continuation line at block+4 (same rule as one-dimensional
arrays; skipped when the RHS is a `new Type[][] { … }` form):

```java
int[][] matrix
    = { { 1, 2, 3 }, { 4, 5, 6 }, { 7, 8, 9 } };
```

**Priority 3 is skipped for the outer array** — jump straight to
one-sub-array-per-line.

**Priority 4** — each sub-array on its own line at block+4. Each
sub-array itself is subject to its own cascade recursively; if a
sub-array fits inline it stays inline, otherwise it wraps per its
own Priority 3 → Priority 4:

```java
int[][] matrix = {
    { 1, 2, 3 },
    { 4, 5, 6 },
    { 7, 8, 9 }
};

// Sub-array itself too long — inner Priority 3 fires per row:
int[][] wideMatrix = {
    {
        100, 200, 300, 400, 500, 600, 700, 800, 900,
        1000, 1100, 1200
    },
    {
        1300, 1400, 1500, 1600, 1700, 1800, 1900, 2000
    }
};
```

### Nested ternary

Allowed but **require parentheses around the nested ternary** to
make precedence explicit:

```java
// CORRECT — nested ternary explicitly parenthesized:
int level = (score >= 90)
    ? 3
    : ((score >= 50) ? 1 : 0);

// WRONG — nested ternary without parens (ambiguous precedence):
int level = score >= 90 ? 3 : score >= 50 ? 1 : 0;
```

The outer ternary in the correct example follows ternary tier 3
(break before both `?` and `:`, with `:` aligned under `?`). The
nested inner ternary `((score >= 50) ? 1 : 0)` is wrapped in its
own grouping parens — short enough to stay on one line here. If
the inner ternary itself were long enough to require wrapping,
its `?` and `:` would paren-align under the inner `(` per the
"Parenthesized-Expression Continuation" rule.

Long nested ternaries should generally be rewritten as
`if`/`else` ladders or extracted to a small helper method; the
parenthesized form exists for the rare cases where ternary
nesting genuinely reads cleaner.

### `assert` statements

`assert cond;` or `assert cond : detail;` forms follow standard
statement rules. Single space after the `assert` keyword, single
space around `:` (matching binary-operator spacing). If the line
overflows, wrap per the standard operator-continuation rules.

### `synchronized (expr)` blocks

Treated as control-flow — same-line brace
`synchronized (expr) {` when `(expr)` fits on one line with the
brace; Allman brace on its own line when `(expr)` itself wraps
to multiple lines. Condition wrapping uses the standard
boolean-expression wrapping rules.

### Cast expressions

- **Basic spacing**: single space after closing cast paren —
  `(Type) value`.
- **Nested casts**: `(OuterType) (InnerType) value` — single space
  between casts.
- **Cast applied to a parenthesized expression**:
  `(Type) (a + b)` — single space before the inner paren.
- **Cast applied to a method call**: `(Type) obj.method()` — no
  extra parens needed around the call.
- **Intersection-type casts** `(A & B) value` — single space
  around `&`, single space after closing cast paren.
- **Long cast expression that wraps**: cast follows continuation
  rules of the surrounding expression; no special handling for
  the cast itself.

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

### Reflow invariants

The formatter must preserve the following content verbatim and must
NOT reflow across these boundaries:

- **`<pre>...</pre>` blocks inside javadoc**: contents preserved
  verbatim — never reflowed.
- **`{@code ...}` / `{@literal ...}` inline tags**: contents
  preserved verbatim.
- **`@param` / `@return` / `@throws` continuation lines**: indented
  to the description-start column on subsequent wrap lines.
- **HTML lists** (`<ul>`, `<ol>`, `<li>`): break behavior must
  preserve list-item boundaries.
- **`@snippet` directives**: contents not reflowed.

**Block-level HTML markers** that terminate a paragraph (so
unrelated chunks don't merge): `<p>`, `<pre>`, `<ul>`, `<ol>`,
`<li>`, `<table>`, `<tr>`, `<td>`, `<th>`. Tag continuation
lines (extra-indented after the `*` prefix) also terminate a
paragraph.

---

## Switch Statements and Expressions

The opening brace for `switch` goes on the **same line** (control-flow
brace placement). `case` labels are indented **+4 spaces from the
block's left anchor** — where the block's closing brace aligns —
regardless of whether the case uses the arrow form (`case A -> body;`)
or the traditional colon form (`case A: body; break;`).

```java
// Traditional colon form (switch statement):
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

For a switch expression on the right-hand side of an assignment, the
block's left anchor is the **statement's start column** (where the
closing `};` aligns), not the `switch` keyword's column:

```java
String message = switch (status) {
    case ACTIVE -> "active";
    case INACTIVE -> "inactive";
};
```

### Arrow placement

The `->` follows the case label with a single space — no column
alignment across cases. This avoids ugly displacement when one or
more cases have long patterns (record patterns, deconstruction,
pattern guards) that would push the alignment column far to the
right of the others:

```java
case ACTIVE -> "active";
case INACTIVE -> "inactive";
case PENDING -> "pending";

// Mixed simple labels and long patterns read cleanly:
case Point(int x, int y) -> handlePoint(x, y);
case String s -> handleString(s);
case null -> handleNull();
```

### Multi-label case wrap

**Priority 1: Single line** when it fits:

```java
case ACTIVE, RESUMING, RECONNECTING -> "active";
```

**Priority 2: Paren-aligned with first label after `case `.** Per
the universal `->` placement rule (see "Universal arrow placement
rule" below), `->` moves to its own line at `case_column + 4`
because the case-and-arrow line itself wrapped:

```java
case AReallyLongValueOne,
     AReallyLongValueTwo,
     AReallyLongValueThree
    -> "result";
```

No priority 3 fallback for multi-label case wrap. Going
double-indented on the next line would land labels at a column
further right than priority 2's paren-alignment, so it doesn't help
with overflow. If priority 2 doesn't fit, the developer must
shorten label names — the formatter cannot resolve it.

### Arrow body that's a block

Same-line `{` after `->`, matching control-flow brace placement.
`yield` indented +4 from the case body start:

```java
case ACTIVE -> {
    log.info("active path");
    yield "active";
}
```

### Long arrow body (single expression)

Wraps per the inner expression's own rules (method-call
priorities 1–4, ternary tiers, string concat, etc.). See also the
"Parenthesized-Expression Continuation" rule under "Line
Continuation" — when an expression is wrapped in **grouping
parentheses**, operator continuation aligns under the column
immediately after the opening parenthesis:

```java
// Parenthesized expression — continuation aligns under (
case ACTIVE -> ("active state with details: "
                + describeDetails(input));

// Non-parenthesized expression — continuation at +4 indent
case ACTIVE -> "active state with details: "
        + describeDetails(input);

// Method-call argument list overflow — paren-align (priority 2)
case ACTIVE -> someService.computeAndFormat(input,
                                            options,
                                            configuration);
```

### Switch statement (no assignment)

Same arrow-form rules apply. Closing `}` aligns with the `switch`
keyword's column (standard same-line-brace control flow):

```java
switch (status) {
    case ACTIVE -> log.info("active");
    case INACTIVE -> log.info("inactive");
}
```

### Mixing arrow form and traditional `case … :` blocks

Allowed within a single switch — the formatter does not forbid it.
Checkstyle or code review may discourage mixing as a style concern;
the formatter accepts both styles in the same switch.

### Pattern matching — type patterns

Standard Java spacing: single space between type and identifier:

```java
if (obj instanceof String s) { use(s); }
case String s -> handleString(s);
```

### Pattern matching — record / deconstruction patterns

Record patterns wrap like method **declarations** (one component
per line, paren-aligned with the first component or next-line
double-indented), NOT like method calls — there is no "comma-packed
two-line" form for record patterns:

```java
// Priority 1 — entire case + arrow + body fits on one line.
case Point(int x, int y) -> handle(x, y);

// Priority 2 — pattern wraps paren-aligned (one component per
// line, aligned to first component after the pattern's `(`).
// Closing `)` ends the last component line. `->` moves to its
// own line at case_column + 4. Post-arrow body fits on the
// `->` line (single-line body):
case AVeryLongRecord(int firstField,
                     int secondField,
                     int thirdField)
    -> handle(firstField, secondField, thirdField);

// Priority 2 — same pattern wrap; post-arrow body itself wraps
// per its own rules (here, method-call paren-aligned args):
case AVeryLongRecord(int firstField,
                     int secondField,
                     int thirdField)
    -> handle(firstField + someLongExpression,
              secondField + someLongExpression,
              thirdField + someLongExpression);

// Priority 3 — when paren-aligned component column would push
// lines over 80 chars, components move to next-line
// double-indented (case_column + 8). Closing `)` ends the
// last component line. `->` still on its own line at
// case_column + 4.
case AVeryLongRecord(
        int firstField,
        int secondField,
        int thirdField)
    -> handle(firstField, secondField, thirdField);
```

**Anti-pattern** — never leave `->` at the end of the pattern's
closing-`)` line and break the body's call below at the call's
opening `(`. Always move `->` to its own line first when the
pattern wraps:

```java
// WRONG:
case AVeryLongRecord(int firstField,
                     int secondField,
                     int thirdField) -> handle(
    firstField, secondField, thirdField);
```

Nested patterns wrap recursively at each level using the same
priority rules.

### Pattern guards

`when condition` stays on the same line as the case label — the
`when` keyword never moves to a new line. If the
case+pattern+when+condition+arrow line overflows, the **guard
expression** wraps per its own rules (operator continuation;
parenthesized-expression preference) AND `->` moves to its own
line at `case_column + 4` per the universal `->` placement rule:

```java
// Priority 1 — fits.
case Integer i when i > 0 -> handlePositive(i);

// Long condition — wraps at boolean operators; `->` on own line.
case Integer i when i > 0
        && i < MAX_VALUE
        && isInRange(i)
    -> handle(i);

// Or with parentheses, paren-aligned operator continuation:
case Integer i when (i > 0
                     && i < MAX_VALUE
                     && isInRange(i))
    -> handle(i);
```

### `instanceof` pattern in long `if` conditions

Same expression-continuation rules as any other condition. The
`instanceof Pattern p` is just an expression. Breaks happen at
`&&`/`||` per the existing rule:

```java
if (obj instanceof Point(int x, int y) p
        && x > 0
        && y > 0)
{
    handle(p);
}
```

### Universal arrow placement rule

This rule applies to ALL switch arrow forms (simple labels,
multi-label, record patterns, pattern guards) and is the same rule
used by lambdas (see "Lambdas"):

- When the line containing `case LABEL ->` itself overflows or
  breaks (because the LABEL or pattern is too long, or wraps to
  multiple lines), `->` moves to its own line single-indented
  from the case (`case_column + 4`).
- When only the post-arrow BODY wraps (the
  `case LABEL -> first-body-token` line still fits), `->` stays
  attached to the case label and the body wraps below per its
  own continuation rules.

---

## Multi-catch

### Spacing around `|`

Single space on each side, matching binary-operator spacing:
`IOException | SQLException`.

### Wrap rules

**Priority 1: Single line** when the entire catch fits within 80:

```java
} catch (IOException | SQLException e) {
    log.error("io or sql failed", e);
}
```

**Priority 2: Two-line form** when priority 1 overflows but the
entire exception type list fits on exactly two lines. Exception
types pack as many as fit on the catch line; the remainder go on
a single continuation line with `|` at the start, **paren-aligned
with the first exception type's column** on the catch line. Break
happens at the latest `|` that lets both lines fit ≤80. Allman
opening brace because the catch condition is multi-line:

```java
} catch (FileNotFoundException | AccessDeniedException
         | InterruptedIOException | TimeoutException e)
{
    log.error("filesystem-related failure", e);
}
```

**Priority 3: One exception type per line** when the type list
cannot fit on two lines. `|` at the start of each continuation
line, paren-aligned with the first exception type's column. The
identifier `e` stays attached to the last exception type. Allman
brace:

```java
} catch (FileNotFoundException
         | AccessDeniedException
         | InterruptedIOException
         | TimeoutException
         | AnotherLongExceptionType e)
{
    log.error("filesystem-related failure", e);
}
```

**No priority 4 fallback.** A double-indent next-line form would
save only one character per continuation line (`} catch (` is 9
chars wide vs. an 8-char double-indent). The marginal savings
aren't worth the structural disruption. If priority 3 produces
lines that overflow 80, the developer must rename or restructure
exception types — the formatter does not introduce a priority 4
fallback for multi-catch.

### `} catch (` placement

The closing brace of the preceding `try` block shares a line with
`catch (`, regardless of whether the catch condition wraps:

```java
try {
    risky();
} catch (IOException e) {
    log.error("failed", e);
}

try {
    risky();
} catch (FileNotFoundException
         | AccessDeniedException
         | InterruptedIOException
         | TimeoutException e)
{
    log.error("failed", e);
}
```

Single-line catch condition → same-line opening brace. Multi-line
catch condition → Allman opening brace on its own line.

---

## Try-with-resources

### Single-resource form

**Priority 1: Single line** — entire
`try (Resource r = expr) {` fits on one line; same-line brace:

```java
try (FileInputStream in = new FileInputStream(file)) {
    process(in);
}
```

**Priority 2+: Break before `=`.** When priority 1 overflows,
always break **before** the `=` operator (operator at the start
of the continuation line per the existing
"break before binary operators" rule). The continuation indent
for the `=` line is **+4 past the column of the `try (` opening
paren** (the first 4-space tab stop after the open paren). The
RHS expression after `=` then follows its own wrap rules. The
opening `{` of the try block goes on its own line (Allman)
because the try condition is multi-line.

```java
// RHS fits on a single line after =:
try (FileInputStream in
        = new FileInputStream(someLongFilePathExpression))
{
    process(in);
}

// RHS is a method call whose args fit on two lines, paren-
// aligned and comma-packed:
try (SomeResource resource
        = new SomeResource(parameter1, parameter2,
                           parameter3, parameter4))
{
    process(resource);
}

// RHS method-call args don't fit on two lines; one arg per
// line, paren-aligned:
try (SomeResource resource
        = new SomeResource(longerParameter1,
                           longerParameter2,
                           longerParameter3,
                           longerParameter4))
{
    process(resource);
}

// An individual arg pushes the call past 80; line-break before
// first arg and indent +4 past the call's line:
try (InputStreamReader in
        = new InputStreamReader(
            someExpressionToGetInputStream,
            someExpressionToGetEncoding))
{
    process(in);
}
```

### Multi-resource form

Multiple resources are **always** broken across multiple lines —
never multiple resource declarations on a single line, even if
they would fit. Each resource declaration ends with `;` at the
end of its line; the LAST resource has **no** trailing `;` (Java
9+ allows it but the project standard is to omit). Subsequent
resources are paren-aligned with the start of the first resource
(the column right after `try (`). Allman opening brace because
the try condition is always multi-line in this form:

```java
try (FileInputStream in = new FileInputStream(input);
     FileOutputStream out = new FileOutputStream(output))
{
    transfer(in, out);
}

try (conn;
     FileInputStream in = new FileInputStream(file))
{
    process(conn, in);
}
```

If any individual resource declaration in a multi-resource form
overflows on its own line, the same break-on-`=` rule applies
recursively for that resource. The `=` continuation indent is
still measured from the column of the `try (` paren (so all
wrapped `=` lines align consistently across the multi-resource
block):

```java
try (FileInputStream in = new FileInputStream(input);
     SomeReallyLongResourceTypeName resourceName
         = new SomeReallyLongResourceTypeName(longArg1, longArg2);
     FileOutputStream out = new FileOutputStream(output))
{
    process(in, resourceName, out);
}
```

Single-line resource → same-line brace. Multi-line condition
(single resource that wraps via break-on-`=`, or any
multi-resource form) → Allman brace on its own line.

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

## Tooling

The canonical formatter is `tooling/scripts/format_java.py` — a
pure-Python AST-based formatter built on `tree-sitter-java`. It
walks the parsed CST and emits spec-compliant text directly,
covering every rule defined above.

### Entry point

`tooling/scripts/format_file.py path/to/File.java` is the
single-file entry point used by the VSCode keybinding and the
Claude Code `PostToolUse` hook. It is a thin wrapper that invokes
`format_java.py` for the given file (or batch).

### Guarantees

- **Idempotent by construction.** Formatting any
  formatter-produced file again produces no changes.
- **AST round-trip equivalence.** Output re-parses to the same
  AST as the input (modulo whitespace and comments), so the
  formatter never changes Java semantics.
- **Emit + warn on overflow.** When wrap rules cannot bring a
  line under 80 chars, the formatter emits the last-resort wrap
  shape AND prints a warning to stderr identifying the offending
  line and the constraining type/expression. It does NOT
  auto-add `// CSOFF`/`// CSON` markers — those must be added by
  the developer if the overflow is intentional.

### Verification

Run checkstyle to verify a formatter run produced spec-compliant
output:

```bash
mvn -Pcheckstyle validate
```

Must report `BUILD SUCCESS` before opening a PR.

### IDE configuration

VSCode and IntelliJ users can configure on-save hooks to invoke
`format_file.py` against the edited file. The standards repo's
`adoption/` flow wires this up automatically; see the
`/init-java` skill or the FAQ
`docs/faqs/building/java-formatting-standards.md`.
