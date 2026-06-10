# Java Formatting Standards

## Overview

All non-generated Java source files must conform to the formatting rules defined in `.java-coding-standards/docs/java-coding-standards.md`. Consult it before writing or reformatting Java code.

## When generating new code

**Apply these standards from the start.** Do not write Java code in a free-form way and then reformat — generate it already compliant:

- Pick brace placement based on the construct (Allman for type/method/constructor definitions; same-line for control flow and lambdas).
- Wrap long lines at `+`, `&&`, `||`, `?`, `:`, `.` with the operator starting the continuation line.
- Use the parameter placement priority (single line → paren-aligned → next-line double-indented).
- Reflow javadoc to fill near 80 chars; never leave 1-3 orphan words on a continuation.
- Single-line `if` is **only** for short-circuit control flow: body must be `return`/`continue`/`break`/`throw`, the `if` must be standalone (no `else`), and the whole thing must fit on one line. `if (x == null) return null;` is fine.
- Assignments and method calls always get braces, even when they fit. `if (env != null) env.destroy();` and `if (moduleName == null) moduleName = "...";` are wrong — brace them.
- For `if`/`else` pairs, always brace both branches regardless of body type or fit.
- Put `throws` on its own line, single-indented from the method.

After generation, run `mvn -Pcheckstyle validate` to confirm compliance. The bulk formatter described below is an aid for legacy code or batch updates — it is not a substitute for writing compliant code on the first pass.

## Key Rules

- **80-character line limit** — enforced by checkstyle via `-Pcheckstyle`
- **Allman braces** for class, interface, enum, record, method, and constructor definitions
- **Same-line braces** for control flow: if/else, for, while, do, try/catch/finally, switch, synchronized, lambdas, array initializers
- **Allman braces** for static / instance initializer blocks (spec B10)
- **Continuation indentation**: +4 per wrap level (cumulating to 8 spaces of displacement for the typical double-wrap; see the full standards doc for the per-level rule)
- **Operators on continuation lines**: break BEFORE `+`, `&&`, `||`, `?`, `:`, `.`
- **CSOFF/CSON**: only for deliberately aligned multi-line output (aligned labels, SQL DDL, column-formatted diagnostics) — NOT a general escape hatch
- **Javadoc**: reflow prose and @tag descriptions to fill lines near 80 chars; don't leave orphaned short words
- **Switch case labels**: indented +4 from the block's left anchor (the column where the closing `}` aligns)
- **Single-line `if`** is reserved for short-circuit control flow only — body must be `return`/`continue`/`break`/`throw`, no `else`, and the whole thing must fit on one line. Assignments and method calls always use braces, even when they fit. `if`/`else` pairs always brace both branches.

## Checkstyle Configuration

The standards repo ships two checkstyle config files; consumer projects reference them via the submodule path in `pom.xml`'s `maven-checkstyle-plugin` configuration:

- `senzing-checkstyle.xml` — enforces LineLength (80), RightCurly, NeedBraces, UnusedImports, Indentation, OperatorWrap, FileTabCharacter, CSOFF/CSON suppression.
- `senzing-checkstyle-suppressions.xml` — globally suppresses checks that are not yet enforced (Indentation, NoWhitespaceAfter, FinalParameters, HiddenField, ParameterNumber, MagicNumber, AvoidNestedBlocks, MethodLength, FileLength, AvoidStarImport, RegexpSingleline).

Project-specific suppressions (e.g. for auto-generated files) layer in via a project-local `checkstyle-suppressions-local.xml` next to the project's `pom.xml` — passed to checkstyle alongside the shared base via the multi-value `<suppressionsLocation>` syntax.

## Formatter architecture (0.3.0+)

`tooling/scripts/format_file.py` is the single end-user entry point. It's a thin wrapper that invokes the canonical formatter at `format_java.py` **in-process** — no JVM, no subprocess pipeline. Same input → same output regardless of caller (VS Code save, Claude Code edit hook, CLI, CI pre-commit).

`format_java.py` is a pure-Python AST-based formatter built on `tree-sitter-java`. For each file it:

1. **Parses** the source bytes to a tree-sitter CST.
2. **Walks** the CST top-down, dispatching each node type to its registered emitter function via the `_NODE_EMITTERS` table.
3. **Emits** spec-compliant text via an output buffer (`Emitter`) that tracks column / indent level and strips trailing whitespace per spec A5.
4. **Wraps** when the natural single-line form would overflow 80 chars — the wrap-priority engine handles throws clauses, method-call args (P1 → P2 paren-aligned → P4 next-line single-indent), variable-declarator break-at-`=`, class-header type-parameter wrap, binary-expression wrap at the leftmost operator, and source-preservation of developer-authored multi-line conditions / params.

Unknown node types raise `NotImplementedError` with a clear "not yet supported" diagnostic; the dispatcher never silently passes source text through. The deliberate out-of-scope construct for 0.3.0 is `module_declaration` (no consumer project uses Java modules yet).

The grammar version (`tree-sitter-java==0.23.5`) and the Python binding (`tree-sitter==0.25.2`) are pinned in `tooling/scripts/requirements.txt`. Bumps go through a calibration re-run against the 83 fixture pairs under `tooling/scripts/tests/fixtures/`.

## VSCode integration

- `.vscode/settings.json` — `[java].editor.formatOnSave: false` (we do NOT use redhat.java's built-in format-on-save). `emeraldwalk.runonsave` instead invokes `format_file.py` on Java save.
- Why not let redhat.java do format-on-save? The redhat.java extension doesn't implement the Senzing spec — running it on save would produce output the canonical formatter then has to rewrite. One invocation via `emeraldwalk.runonsave` is cleaner.

## Running the formatter

End-to-end:

```bash
# Bulk pass over the project's source roots (defaults: src/main/java,
# src/test/java, src/demo/java when present).
python3 .java-coding-standards/tooling/scripts/format_file.py

# Format a specific directory tree.
python3 .java-coding-standards/tooling/scripts/format_file.py src/main/java

# Format a single file in place.
python3 .java-coding-standards/tooling/scripts/format_file.py path/to/File.java
```

Output: one summary line — `Formatter: N files processed, M modified.` Exit code 0 on success (regardless of how many files were modified), 1 on parse errors, 2 on missing-file or import-error conditions.

For inspecting a single file's formatted output without rewriting it:

```bash
# Print the formatted output to stdout.
python3 .java-coding-standards/tooling/scripts/format_java.py --format path/to/File.java

# Exit 1 if the file would be reformatted, 0 if compliant.
python3 .java-coding-standards/tooling/scripts/format_java.py --format path/to/File.java --check
```

## Upgrading from 0.2.x

The 0.3.0 release replaced the previous JDT + six-script pipeline with the single in-process tree-sitter formatter described above. If your project is upgrading from 0.2.x:

- `format_file.py` keeps the same CLI surface (positional paths, `--src-dirs`, `--exclude`, `--exclude-from`), so VSCode tasks, Claude Code hooks, and pre-commit configs continue to work.
- A consumer's first post-upgrade run typically produces a sizeable one-time reformat because the new formatter is spec-compliant by construction. Commit that diff as a "format compliance" follow-up; a second run reports zero modifications (the idempotency gate).
- Consumers should delete legacy artifacts after upgrading: `.claude/scripts/fix_*.py`, `.vscode/java-formatter.xml`, and any cached `~/.cache/senzing-jdt-formatter/` JDT JAR. The standards repo no longer ships any of those.
- A JDK is no longer required to run the formatter. Only Python 3.10+ plus the runtime deps in `tooling/scripts/requirements.txt`.

## Full Reference

See `.java-coding-standards/docs/java-coding-standards.md` for the complete standards document, including method declaration priority rules, ternary operator tiers, short-circuit conditional formatting, and the per-construct spec sections.
