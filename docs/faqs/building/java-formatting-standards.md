## Java Formatting Standards

### Overview
All non-generated Java source files must conform to the formatting rules defined in `.java-coding-standards/docs/java-coding-standards.md`. Consult it before writing or reformatting Java code.

### When generating new code

**Apply these standards from the start.** Do not write Java code in a free-form way and then reformat — generate it already compliant:

- Pick brace placement based on the construct (Allman for type/method/constructor definitions; same-line for control flow and lambdas).
- Wrap long lines at `+`, `&&`, `||`, `?`, `:`, `.` with the operator starting the continuation line.
- Use the parameter placement priority (single line → paren-aligned → next-line double-indented).
- Reflow javadoc to fill near 80 chars; never leave 1-3 orphan words on a continuation.
- Single-line `if` is **only** for short-circuit control flow: body must be `return`/`continue`/`break`/`throw`, the `if` must be standalone (no `else`), and the whole thing must fit on one line. `if (x == null) return null;` is fine.
- Assignments and method calls always get braces, even when they fit. `if (env != null) env.destroy();` and `if (moduleName == null) moduleName = "...";` are wrong — brace them.
- For `if`/`else` pairs, always brace both branches regardless of body type or fit.
- Put `throws` on its own line, single-indented from the method.

After generation, run `mvn -Pcheckstyle validate` to confirm compliance. The bulk-fix scripts below are an aid for legacy code or batch updates — they are not a substitute for writing compliant code on the first pass.

### Key Rules
- **80-character line limit** — enforced by checkstyle via `-Pcheckstyle`
- **Allman braces** for class, interface, enum, method, and constructor definitions
- **Same-line braces** for control flow: if/else, for, while, do, try/catch/finally, switch, synchronized, lambdas, array initializers, static initializers
- **Continuation indentation**: 8 spaces (double indent)
- **Operators on continuation lines**: break BEFORE `+`, `&&`, `||`, `?`, `:`, `.`
- **CSOFF/CSON**: only for deliberately aligned multi-line output (aligned labels, SQL DDL, column-formatted diagnostics) — NOT a general escape hatch
- **Javadoc**: reflow prose and @tag descriptions to fill lines near 80 chars; don't leave orphaned short words
- **Switch case labels**: left-aligned with switch (no extra indent)
- **Single-line `if`** is reserved for short-circuit control flow only — body must be `return`/`continue`/`break`/`throw`, no `else`, and the whole thing must fit on one line. Assignments and method calls always use braces, even when they fit. `if`/`else` pairs always brace both branches.

### Checkstyle Configuration

The standards repo ships two checkstyle config files; consumer projects reference them via the submodule path in `pom.xml`'s `maven-checkstyle-plugin` configuration:

- `senzing-checkstyle.xml` — enforces LineLength (80), RightCurly, NeedBraces, UnusedImports, Indentation, OperatorWrap, FileTabCharacter, CSOFF/CSON suppression.
- `senzing-checkstyle-suppressions.xml` — globally suppresses checks that are not yet enforced (Indentation, NoWhitespaceAfter, FinalParameters, HiddenField, ParameterNumber, MagicNumber, AvoidNestedBlocks, MethodLength, FileLength, AvoidStarImport, RegexpSingleline).

Project-specific suppressions (e.g. for auto-generated files) layer in via a project-local `checkstyle-suppressions-local.xml` next to the project's `pom.xml` — passed to checkstyle alongside the shared base via the multi-value `<suppressionsLocation>` syntax.

### VSCode Formatter
- `.java-coding-standards/tooling/ide/java-formatter.xml` — Eclipse JDT formatter profile (Allman for methods/types, same-line for blocks). Consumer's `.vscode/settings.json` references it via `"java.format.settings.url"`.
- `.vscode/settings.json` — `editor.formatOnSave` disabled for the `[java]` scope (the JDT formatter cannot fully enforce these standards; rely on the orchestrator script instead).
- **Limitation**: the VSCode/JDT formatter cannot enforce per-block-type brace placement (cannot have Allman for methods AND same-line for if/for in the same file). The bulk-fix scripts cover what the JDT profile cannot.

### Automation Scripts

Five Python scripts in the shared `.java-coding-standards/tooling/scripts/` directory automate bulk formatting fixes. Run from project root:

```bash
python3 .java-coding-standards/tooling/scripts/fix_allman_braces.py
python3 .java-coding-standards/tooling/scripts/fix_javadoc_reflow.py
python3 .java-coding-standards/tooling/scripts/fix_javadoc_inline_tags.py
python3 .java-coding-standards/tooling/scripts/fix_javadoc_tags.py
python3 .java-coding-standards/tooling/scripts/fix_need_braces.py
```

- `fix_allman_braces.py` — moves opening braces to Allman style for class/interface/enum/method/constructor definitions; splits `throws` clauses onto their own line.
- `fix_javadoc_reflow.py` — reflows plain Javadoc prose paragraphs (skips paragraphs that begin with `{@link}`/`<code>`/etc.).
- `fix_javadoc_inline_tags.py` — reflows Javadoc paragraphs that contain inline tags (`{@link}`, `<code>`, etc.) but are still prose. Catches the cases `fix_javadoc_reflow.py` intentionally skips.
- `fix_javadoc_tags.py` — reflows `@param`, `@return`, `@throws` tag descriptions.
- `fix_need_braces.py` — fixes brace placement on `if` / `else` blocks. For a **standalone `if`** with a short-circuit body (`return`/`continue`/`break`/`throw`), collapses `if (cond)\n    body;` to a single line when it fits within 80 chars (Tier 1); otherwise braces are added (Tier 2). For non-short-circuit bodies (assignments, method calls), braces are always added — even on already-inline `if (cond) someVar = ...;` lines that checkstyle would otherwise allow. For `if`/`else` pairs, both branches are **always** braced — never single-lined, even when the bodies would fit.

The scripts scan `src/main/java`, `src/test/java`, and `src/demo/java` if present. Use `--src-dirs` to override the default list and `--exclude` to skip globs (e.g. auto-generated files). For single-file reformatting (single-file mode), pass a file path as a positional argument; the orchestrator `format_file.py` runs all five scripts against that one file in canonical order.

### Full Reference

See `.java-coding-standards/docs/java-coding-standards.md` for the complete standards document, including method declaration priority rules, ternary operator tiers, short-circuit conditional formatting, and the Claude prompt for formatting.
