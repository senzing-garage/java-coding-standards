<!--
  CLAUDE.md template — three sections to merge into the consumer
  project's .claude/CLAUDE.md. Placeholders:

    {{PROJECT_NAME}}       — the project's directory name (e.g.
                              senzing-commons), used in the FAQ
                              server name
    {{PROJECT_GROUP_ID}}   — Maven groupId (e.g. com.senzing)
    {{HAS_DEMO_JAVA}}      — "true" if src/demo/java exists,
                              else "false"

  The /init-java adoption flow merges these sections into a project's
  CLAUDE.md without disturbing project-specific sections like
  Architecture Overview, Development Notes, etc.

  When the same headings already exist (e.g. project was on the
  pre-submodule version of these standards), the prompt replaces
  the body and leaves surrounding project-specific prose alone.
-->

## Java Coding Standards

**IMPORTANT — apply when generating or modifying Java code:** All Java code
(new and existing) in this repository must conform to the formatting rules in
`.java-coding-standards/docs/java-coding-standards.md`. Apply these rules
**from the start** — do not write code first and reformat afterward. When in
doubt about a specific case (parameter alignment, method continuation,
ternary tier, javadoc reflow), read the full standards document or search
the FAQ:
`mcp__{{PROJECT_NAME}}-faq__search_faqs(query="java formatting")`.

### Quick reference

- **80-character line limit** (enforced by checkstyle via `-Pcheckstyle`).
  Lines beyond 80 chars must be wrapped.
- **Allman braces** for class/interface/enum/method/constructor definitions
  (opening `{` on its own line, left-aligned with the declaration).
- **Same-line braces** for control flow: `if`/`else`/`for`/`while`/`do`/
  `try`/`catch`/`finally`/`switch`/`synchronized`, lambdas, array
  initializers, static init blocks.
- **Multi-line conditions**: when an `if`/`catch`/etc. condition wraps to
  multiple lines, the opening brace goes on its own line (Allman) to
  visually separate condition from body.
- **Method parameters** (priority order): single line if it fits; otherwise
  paren-aligned with types/names columnized; otherwise next-line
  double-indented.
- **`throws` clauses** go on their own line, single-indented.
- **Continuation indentation**: 8 spaces (double indent).
- **Operators on continuation lines**: break **before** `+`, `&&`, `||`, `?`,
  `:`, `.` (the operator starts the continuation line).
- **Short-circuit `if`**: `if (cond) statement;` on one line is preferred
  (Tier 1) when it fits; otherwise add braces.
- **Javadoc**: reflow prose and `@param`/`@return`/`@throws` to fill lines
  near 80 chars; do not leave 1-3 orphan words on a line.
- **CSOFF/CSON**: only for deliberately aligned multi-line output
  (column-formatted diagnostics, ASCII art, SQL DDL with aligned clauses)
  — never a general escape hatch.

### Verification

Run checkstyle: `mvn -Pcheckstyle validate` (must report `BUILD SUCCESS`
before opening a PR).

### Bulk formatting scripts

Five scripts in `.java-coding-standards/tooling/scripts/` (run from project
root) automate common reformat passes — useful for legacy code or batch
updates, **not a substitute** for writing compliant code in the first
place:

- `python3 .java-coding-standards/tooling/scripts/fix_allman_braces.py`
- `python3 .java-coding-standards/tooling/scripts/fix_javadoc_reflow.py`
- `python3 .java-coding-standards/tooling/scripts/fix_javadoc_inline_tags.py`
- `python3 .java-coding-standards/tooling/scripts/fix_javadoc_tags.py`
- `python3 .java-coding-standards/tooling/scripts/fix_need_braces.py`

For single-file reformatting (used by the VSCode keybinding and the Claude
Code `PostToolUse` hook):

```bash
python3 .java-coding-standards/tooling/scripts/format_file.py path/to/File.java
```

The orchestrator runs all five scripts in canonical order against the
single file.

VSCode formatter config (`.java-coding-standards/tooling/ide/java-formatter.xml`)
handles Allman for methods/types and same-line for control flow but cannot
fully enforce all rules. The `building/java-formatting-standards` FAQ
summarizes day-to-day usage.

## FAQ MCP Server

This project ships a local FAQ MCP server registered in `.mcp.json` under
the name `{{PROJECT_NAME}}-faq`. It serves both:

- **Shared FAQs** from the standards-repo submodule
  (`.java-coding-standards/docs/faqs/`) — coding standards, javadoc reflow
  rules, system-stubs/ResourceLock test pattern, FAQ-authoring conventions.
- **Project-local FAQs** from `.claude/faqs/<category>/<topic>.md` —
  project-specific architecture, conventions, build/release notes,
  troubleshooting.

The server merges both into one BM25-ranked search index. Tool surface:

- `mcp__{{PROJECT_NAME}}-faq__get_faq_categories`
- `mcp__{{PROJECT_NAME}}-faq__search_faqs(query=...)`
- `mcp__{{PROJECT_NAME}}-faq__get_faq(title=...)`

**Use it BEFORE making design assumptions or troubleshooting.** Specifically:

- Before changing build, test, or release configuration (`pom.xml`,
  surefire, checkstyle, jacoco, spotbugs, release process), call
  `search_faqs` for relevant topics.
- Before modifying public APIs, search for any documented invariants or
  rationale.
- When a build, test, or dependency issue surfaces, search the
  `troubleshooting` category first.
- When unsure what is documented, call `get_faq_categories` to enumerate
  what's available.

**After resolving a non-obvious issue**, ask the user whether to capture
the solution as a new FAQ. Project-specific lessons go in
`.claude/faqs/<category>/<topic>.md`. Lessons about the standards
themselves go via PR to the standards repo. Restart the session so the
server re-indexes.

FAQs are pulled on demand, so detail is cheap there. Keep CLAUDE.md lean
and push operational/troubleshooting depth into FAQ files.

## Testing Configuration

Tests use JUnit Jupiter with parallel execution enabled (configured in
`pom.xml` surefire plugin):

- Classes run concurrently.
- Methods within a class run in same thread (default).
- Dynamic parallelism factor.

### System Stubs, ExecutionMode, and ResourceLock

Tests that **stub environment variables** or **capture stdout / stderr**
must follow the project's `system-stubs` + `@Execution(SAME_THREAD)` +
`@ResourceLock` pattern to avoid build-log noise and inter-class capture
races. Before writing such a test, search the FAQ:
`mcp__{{PROJECT_NAME}}-faq__search_faqs(query="system stubs")`.

Headline rules:

- Use `system-stubs-jupiter` **programmatically at the method level**
  (`new EnvironmentVariables(...).execute(...)`, `new SystemOut().execute(...)`,
  `new SystemErr().execute(...)`) — never the `@ExtendWith` annotation form.
- Tag the test (or the class) with `@Execution(ExecutionMode.SAME_THREAD)`
  — `System.setOut` / `setErr` are JVM-wide, so concurrent redirects race.
- Add `@ResourceLock(Resources.SYSTEM_OUT)` and/or
  `@ResourceLock(Resources.SYSTEM_ERR)` for cross-class mutual exclusion.
  When both are present, **always declare `SYSTEM_OUT` first, `SYSTEM_ERR`
  second** to avoid deadlock.
- If the production code starts a background thread in its constructor,
  place the `new ...()` call **inside** the `stub.execute(...)` lambda so
  the redirect is active before the thread starts.

Full pattern, examples, and the JVM-warning suppression details are in the
shared `testing/system-stubs-and-output-capture` FAQ.
