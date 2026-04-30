# Post-Adoption Verification Checklist

Run after the `/init-java` adoption flow completes (or after any
submodule pin bump). Step 13 of the adoption prompt invokes this
checklist; it can also be run manually any time.

## Mandatory gates

### 1. Submodule is mounted and pinned

```bash
git submodule status
```

Expected: a single line for `.java-coding-standards/` showing a clean
SHA pin (no `+` or `-` prefix; those mean uncommitted local changes or
unsynced state).

### 2. Checkstyle passes

```bash
mvn -Pcheckstyle validate
```

Expected: `BUILD SUCCESS`. If violations surface, do **not** auto-fix
the source — run the bulk-format scripts (or the orchestrator) and
review the resulting diff.

### 3. Tests pass

```bash
mvn test
```

Expected: all tests pass. Adoption should not change test outcomes —
if tests fail, something's wrong with the configuration migration.

### 4. Bulk-format scripts converge to idempotent

```bash
python3 .java-coding-standards/tooling/scripts/format_file.py
```

The expected output depends on the project's history with the
format scripts:

**Project never ran any version of these scripts, or last ran
them at the same SHA the submodule is now pinned to**: zero
modifications on the first run. One line per script:

```
Processed N files, modified 0 files.
Processed N files, modified 0.
Processed N files, modified 0.
Processed N files, modified 0.
Processed N files, modified 0, 0 short-circuit fixes applied.
```

**Project ran an older version of the scripts in the past**
(common during Phase 3+ migrations of repos that shipped their
own copies under `.claude/scripts/` before the standards repo
existed): some files may be modified on the first post-adoption
run. The scripts evolve over time — most notably,
`fix_allman_braces.py` was corrected to handle wrapped-condition
Allman splits and now contains a Case 5 cleanup that re-aligns
previously-buggy outputs from older script versions. Review the
resulting diff, commit it as a separate "format compliance"
commit, and confirm a **second** orchestrator run reports 0
modifications across all five scripts (this is the idempotency
gate — the codebase is in steady-state compliance only when a
fresh pass is a no-op).

If any modifications appear that don't match either expected
pattern, inspect the diff before committing.

### 5. FAQ MCP server starts and indexes both shared and project-local FAQs

After restarting Claude Code so the MCP host re-launches the server:

- Call `mcp__<project>-faq__get_faq_categories`. Expected: the response
  lists shared categories (`building`, `conventions`, `testing`) plus
  any project-local categories that exist.
- Call `mcp__<project>-faq__search_faqs(query="java formatting")`.
  Expected: the shared `building/java-formatting-standards` FAQ ranks
  near the top.
- Call `mcp__<project>-faq__search_faqs(query="system stubs")`.
  Expected: the shared `testing/system-stubs-and-output-capture` FAQ
  ranks near the top.

### 6. VSCode formatter wires up

Open the project in VSCode. Open any Java file. Confirm:

- The `redhat.java` extension reports the formatter as configured (the
  formatter dropdown shows the submodule path).
- `editor.formatOnSave` is **disabled** for `.java` files (test by
  saving — the JDT formatter should not run).
- The "Format Java file to Senzing standards" task appears in the
  Tasks runner (Cmd+Shift+P → "Tasks: Run Task").

### 7. (Opt-in only) Format-on-save fires

If the user opted in to format-on-save during adoption: edit a Java
file in VSCode, introduce a small standards violation (e.g. a `if (x)
return;` with a non-short-circuit body — `if (x) y = 1;`), save.
Expected: the file is rewritten in place to add braces.

### 8. (Opt-in only) `SessionStart` freshness nudge

If the user opted in to the freshness nudge: run `git fetch` in the
submodule to simulate upstream having moved ahead, then start a new
Claude Code session. Expected: a one-line message
`NOTE: .java-coding-standards is N commits behind upstream/main. Run
/init-java to refresh.`

## Soft gates (worth checking, not failure conditions)

### `.mcp.json` references the submodule path

Open `.mcp.json` and confirm the `command`/`args` reference
`.java-coding-standards/mcp/faq_server.py` (not a project-local copy).

### `.claude/settings.json` has the hooks block

Confirm `PostToolUse`, `Stop`, and (if opted in) `SessionStart` arrays
exist with commands referencing `${CLAUDE_PROJECT_DIR}` and the
submodule path.

### `.github/workflows/` was not touched

Confirm `git diff --stat .github/workflows/` is empty. CI workflows
are owned by senzing-factory; the adoption flow treats them as out
of scope.

### `.gitignore` does not silently hide any of the prompt's new files

Run `git check-ignore -v` on each path the prompt creates and
confirm none is reported as ignored:

```bash
git check-ignore -v \
  .vscode/tasks.json \
  .vscode/extensions.json \
  .claude/settings.json \
  .claude/commands/init-java.md \
  || echo "OK — no files ignored"
```

If any path reports a match, step 7 of the adoption prompt missed
adding the corresponding `!` exception. Fix the gitignore and
re-run `git add` against the affected files.

`git diff --stat .gitignore` may be non-empty if step 7 added `!`
exceptions to allowlist files under `.vscode/*` or `.claude/*`
that the project's existing rules would otherwise hide. That diff
is expected.

### Generated-file exclusions are in place

If step 11 produced exclusions, confirm:

- `checkstyle-suppressions-local.xml` exists at the project root and
  is referenced by the second `<suppressionsLocation>` entry in pom's
  checkstyle profile.
- `.java-coding-standards-excludes` exists at the project root with
  the gitignore-style globs.
- Both files are committed (not gitignored).

## What to do if a gate fails

| Failure                                                | Likely cause                                                                                           | Fix                                                                                                                                                                                 |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `mvn -Pcheckstyle validate` fails                      | Source has rule violations the previous tooling missed, or the pom checkstyle profile is misconfigured | Run the bulk-format scripts; inspect the resulting diff; commit it as a separate "format compliance" commit                                                                         |
| `mvn test` fails after adoption but passed before      | Configuration migration introduced a regression                                                        | Compare the pom diff, the surefire `<argLine>` change, and the system-stubs/byte-buddy flags; revert to the prior pom and re-apply the surefire snippet manually                    |
| FAQ server doesn't start                               | mcp dependency install failure (`uv` couldn't fetch), or path mismatch in `.mcp.json`                  | Run the script directly with `uv run --script .java-coding-standards/mcp/faq_server.py --help`; if uv reports a network error, that's a uv/PyPI issue not specific to this adoption |
| `get_faq_categories` returns "No FAQ categories found" | `--shared-faqs-dir` argument not reaching the script, or the submodule is missing/empty                | Check `.mcp.json` args; run `git submodule update --init`                                                                                                                           |
| Format-on-save doesn't fire                            | `emeraldwalk.runonsave` extension declined or not yet installed                                        | Install the extension from the Marketplace; reload window                                                                                                                           |
