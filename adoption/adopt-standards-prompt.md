# Adopt the Senzing Java Coding Standards

You are Claude Code, asked to adopt the Senzing Java coding standards in
the user's current project. This prompt walks you through the wiring
end-to-end: submodule, build configuration, FAQ MCP server, VSCode
integration, Claude Code hooks, and CLAUDE.md merge. Run it in order;
some steps prompt the user via `AskUserQuestion`.

This same prompt handles **fresh adoption** (project has no standards
machinery yet) and **upgrade-from-copy** (project ships its own copy of
the standards artifacts; replace them with submodule pointers and remove
the local duplicates).

The prompt assumes the standards repo is mounted at
`.java-coding-standards/` after the submodule add in step 2. All template
files referenced below live under
`.java-coding-standards/adoption/claude-md-templates/`.

## Step 0 — Confirm intent

Tell the user briefly what's about to happen: "I'm going to wire up the
Senzing Java coding standards in this project. This will add a git
submodule at `.java-coding-standards/`, update pom.xml profiles, add a
FAQ MCP server entry, configure `.vscode/`, install Claude Code hooks,
and merge a section into CLAUDE.md. I'll prompt you for any choices that
matter (generated-file exclusions, format-on-save opt-in, etc.). Ready?"

Do not require an explicit "yes" — Claude Code adoption is opt-in by
nature of running this prompt. Note any in-flight uncommitted work and
suggest committing or stashing first if the diff looks substantial.

## Step 1 — Detect project shape

Read enough of the project to choose the right branches in later steps:

- **`pom.xml`**: extract `<groupId>`, `<artifactId>`, current Java/Maven
  versions, existing profile ids (looking for pre-existing `checkstyle`,
  `jacoco`, `spotbugs`, `release` profiles to merge with rather than
  duplicate), surefire `<argLine>` block, top-level `<argLine>` property.
- **Source layout**: check whether `src/main/java`, `src/test/java`, and
  `src/demo/java` exist. The bulk-format scripts default to scanning
  these three; the existence of `src/demo/java` informs the
  `{{HAS_DEMO_JAVA}}` placeholder in CLAUDE.md.
- **Existing standards artifacts**: look for any of:
  - `.claude/scripts/`, `.claude/faq_server.py`,
    `.claude/java-coding-standards.md`, `.claude/faqs/`
  - `.vscode/java-formatter.xml`, `.vscode/settings.json`,
    `.vscode/cspell.json`, `.vscode/tasks.json`,
    `.vscode/extensions.json`
  - `checkstyle.xml`, `checkstyle-suppressions.xml`
  - `.mcp.json`
  - `.claude/CLAUDE.md` (always check; the merge in step 9 depends on
    what's there)

  Existence of these artifacts tells you this is an **upgrade**; their
  absence means **fresh adoption**.

Record the project's directory name (last path component of the
project root) — this becomes the FAQ server name `<project>-faq`. Ask
the user to confirm if it doesn't follow Senzing conventions.

## Step 2 — Add the submodule

Add the standards repo as a submodule mounted at `.java-coding-standards/`.
Pin to the latest released tag — look up the current value with:

```bash
git ls-remote --tags https://github.com/senzing-garage/java-coding-standards.git \
  | awk '{print $2}' | sed 's,.*/,,' | sort -V | tail -1
```

Then add the submodule and check out that tag:

```bash
git submodule add \
  https://github.com/senzing-garage/java-coding-standards.git \
  .java-coding-standards
git submodule update --init
cd .java-coding-standards && git checkout <latest-tag> && cd ..
git add .gitmodules .java-coding-standards
```

(Substitute `<latest-tag>` with the value from the lookup above.)

**During the standards repo's local-bootstrap window** (before the
GitHub repo exists), substitute the `file://` URL of the local clone:

```bash
git submodule add \
  file:///Users/<user>/dev/senzing/java-coding-standards \
  .java-coding-standards
```

Ask the user for the local path if you don't already know it. Tell them
explicitly that this is local-only — the consumer branch must not be
pushed to a shared remote until the GitHub URL is rewritten in. The
standards repo's README documents the URL-rewrite procedure.

## Step 3 — Wire up `pom.xml`

Update or add three profiles using the templates at
`.java-coding-standards/adoption/claude-md-templates/`:

- `pom-checkstyle-profile.xml` — replaces any existing `checkstyle`
  profile. `<configLocation>` points at the shared config in the
  submodule. **No `<suppressionsLocation>` is needed**: the shared
  `senzing-checkstyle.xml` declares two `<module name="SuppressionFilter">`
  entries internally — one for the shared baseline (always
  present) and one optional entry that picks up a project-local
  `checkstyle-suppressions-local.xml` at the project root when it
  exists. (The path is resolved by checkstyle relative to the
  Maven working directory; no Maven property substitution is
  involved, so the value in the XML is a bare relative path
  rather than `${project.basedir}/...`.) Step 11 generates this
  file interactively. If an existing project pom carries a
  `<suppressionsLocation>` line from an earlier standards version
  (≤ 0.2.0), **delete that line** when you replace the profile —
  leaving it in is harmless but misleading, since the new
  mechanism subsumes it.

  **Multi-module note.** Both suppressions paths above resolve
  relative to the Maven working directory (where `mvn` was
  invoked, not the per-module `${project.basedir}`). For
  multi-module projects, run `mvn -Pcheckstyle validate` from the
  project root so both `.java-coding-standards/` and
  `checkstyle-suppressions-local.xml` resolve correctly. Invoking
  from a child module's directory will fail to find them.

- `pom-jacoco-profile.xml` — adds the `jacoco` profile if missing.
  Preserves any pre-existing `jacoco` profile config the project had,
  unless the user explicitly chose to overwrite.
- `pom-spotbugs-profile.xml` — adds the `spotbugs` profile if missing.
  Same merge rule.

Also apply the surefire snippet (`pom-surefire-snippet.xml`):

- Add an empty `<argLine></argLine>` to top-level `<properties>` if not
  already there.
- Update the `maven-surefire-plugin` configuration to include
  `<argLine>@{argLine} -XX:+EnableDynamicAgentLoading -Xshare:off</argLine>`
  if not already there.

Show the user a unified diff of pom.xml before/after and let them
confirm.

## Step 4 — Wire up the FAQ MCP server

Read `.java-coding-standards/adoption/claude-md-templates/mcp-json-stanza.json`
as the canonical entry shape. Substitute `{{PROJECT_NAME}}` with the
project's directory name from step 1.

### Branch A: no existing `.mcp.json` and no existing FAQ server

Create `.mcp.json` from the template. Create empty
`.claude/faqs/` directory ready for project-specific FAQ files.

### Branch B: existing `.mcp.json` + local `.claude/faq_server.py`

Replace the existing entry to invoke the submodule's `faq_server.py`:

- Preserve any existing per-project server name (e.g. `senzing-commons-faq`).
- Use the new `command`/`args` shape from the template.
- After confirming the user is OK with the diff, **delete
  `.claude/faq_server.py`** (the submodule version supersedes it).
- Leave `.claude/faqs/` and its existing project-local FAQ files
  untouched. The server will merge them with the shared FAQs.

### Branch C: existing `.mcp.json` but for a different (non-FAQ) server

Add the new `<project>-faq` server entry alongside whatever else is
there. No deletions.

In all branches, show the user the `.mcp.json` diff before applying.

## Step 5 — Wire up `.vscode/`

Merge templates from
`.java-coding-standards/adoption/claude-md-templates/`:

- **`.vscode/settings.json`** ← merge `vscode-settings-snippet.json`:
  - Always set `"java.format.settings.url"` to the submodule path.
  - Always add the `[java]` scoped override disabling
    `editor.formatOnSave` for Java only.
  - Conditionally add the `emeraldwalk.runonsave.commands` block —
    gated on the user opt-in below.
  - Preserve all other existing settings.

- **`.vscode/tasks.json`** ← merge `vscode-tasks-snippet.json`:
  - Add the two tasks ("Format Java file to Senzing standards" and
    "Format and reload Java file (Senzing standards)") if not present.
  - Preserve any existing tasks.

- **`.vscode/extensions.json`** ← merge `vscode-extensions-snippet.json`:
  - Add `redhat.java` (always; it's the formatter consumer).
  - Add `emeraldwalk.runonsave` only if the user opts in to format-on-save
    (the next sub-step).
  - Preserve any existing recommendations; deduplicate.

### Format-on-save opt-in

Ask the user via `AskUserQuestion`:

> **Question:** Enable format-on-save? When you save a Java file, the
> bulk-format scripts will run automatically and reformat the file in
> place. Requires the third-party `emeraldwalk.runonsave` VS Code
> extension (we'll recommend it via `.vscode/extensions.json`, you'll
> approve install on first project open).
>
> Alternative: skip this and use the keybinding for explicit on-demand
> formatting.
>
> Options: **Yes — wire up format-on-save** / **No — keybinding only**

If yes: include the `emeraldwalk.runonsave.commands` block and the
extension recommendation. If no: omit both.

### Print the keybinding instructions

The format-on-demand keybinding is User-level (not workspace) and
cannot be auto-installed. Print the snippet from
`.java-coding-standards/adoption/claude-md-templates/keybindings-template.json`
verbatim and tell the user how to apply it (Cmd+Shift+P → "Open
Keyboard Shortcuts (JSON)" → paste).

### Install the slash command

Copy `.java-coding-standards/adoption/slash-commands/init-java.md` to
the project's `.claude/commands/init-java.md`. After this is in place
the user can re-run the adoption flow as `/init-java` from any future
Claude Code session.

### Install the Claude Code hooks

Merge `.java-coding-standards/adoption/claude-md-templates/claude-hooks-snippet.json`
into `.claude/settings.json`:

- **Mandatory hooks**: `PostToolUse` (auto-format every Edit/Write/
  MultiEdit) and `Stop` (final checkstyle pass when Claude is about to
  hand back to the user).
- **Opt-in hook**: `SessionStart` (prints a one-line nudge if the
  submodule is behind upstream main). Ask the user via
  `AskUserQuestion`:

  > Enable submodule-freshness nudges? On session start, if the
  > standards submodule is behind upstream, Claude Code will print a
  > one-line reminder to run `/init-java` to refresh.
  >
  > Options: **Yes** / **No**

  Include only if yes.

If `.claude/settings.json` already has `hooks` for any of these events,
merge entries into the existing arrays rather than replacing.

## Step 6 — `.vscode/cspell.json`: no-op

The standards adoption does **not** modify `.vscode/cspell.json`. cspell
configuration is not a coding-standards concern (the formatting rules
themselves introduce no new vocabulary). Generic Java/Maven/test-tooling
words belong in a separate Senzing Java project-template repo.

For fresh adoptions where no `cspell.json` exists yet, point the user
at any already-adopted Senzing Java project (e.g. senzing-commons-java)
to copy its `.vscode/cspell.json` as a starter and prune as needed.

Skip this step entirely.

## Step 7 — `.gitignore`: no new entries; reconcile silent ignores

The standards adoption itself introduces no files that need to be
added to `.gitignore`:

- `.java-coding-standards/` is **tracked** via `.gitmodules`.
- The extension-point files (`checkstyle-suppressions-local.xml` from
  step 11, `.java-coding-standards-excludes` if you decide to write
  one) are **committed**, not ignored.
- Generic Java/Maven entries (`target/`, `.flattened-pom.xml`,
  `.idea/`, etc.) are project-template concerns and out of scope.

However — and this is **mandatory** — the prompt **must** verify
that the project's existing `.gitignore` does not silently hide any
of the files steps 4, 5, and 9 create. Common project gitignores
include broad patterns like `.vscode/*` or `.claude/*` that exempt a
hand-curated allowlist; without intervention, `git add` silently
drops the new files and they never reach the PR.

### What to check

For each file the prompt creates (or modifies, if the modification
is on an untracked file), run `git check-ignore -v <path>` to see
whether an existing rule matches:

- `.vscode/tasks.json` — created in step 5
- `.vscode/extensions.json` — created in step 5
- `.claude/settings.json` — created (or merged into) in step 5
- `.claude/commands/init-java.md` — installed in step 5
- `.vscode/settings.json` — modified in step 5 (only relevant if it
  was previously untracked due to an ignore rule)

If `git check-ignore` reports a match for any of these, the file
is being silently dropped.

### How to fix

Add an `!` exception line to `.gitignore` for each affected path,
placed below the matching ignore rule. For example, if the project
has:

```gitignore
.vscode/*
!.vscode/cspell.json
!.vscode/settings.json
```

…and the prompt is creating `.vscode/tasks.json` and
`.vscode/extensions.json`, append:

```gitignore
!.vscode/extensions.json
!.vscode/tasks.json
```

After adding exceptions, re-run `git check-ignore -v <path>` on
each affected file. The output should now reference the negation
line (`!.vscode/tasks.json`) instead of the original ignore rule.

Show the user the `.gitignore` diff before saving, especially if
the project's existing gitignore has many rules — appended `!`
exceptions can interact unexpectedly with later rules in the same
file (a later `.vscode/*` would re-ignore them). When in doubt,
place the `!` exceptions in the same block as the ignore rule
that matched.

If `git check-ignore` reports no matches for any of these paths,
this step is a no-op. The verification is mandatory; the
modification is conditional.

## Step 8 — GitHub workflows: no-op

CI workflows for Senzing Java repos are owned by
`senzing-factory/build-resources` and its sibling reusable workflows.
The standards repo does not ship workflows.

Verify only that the consuming project already has the senzing-factory
cspell + checkstyle workflow stubs in `.github/workflows/`. If they're
missing, point the user at the senzing-factory documentation rather
than installing anything yourself.

If the senzing-factory checkstyle workflow does not yet do
`submodules: recursive` on checkout, mention this — the workflow needs
that update so the submodule contents are available at CI run time.
That's a senzing-factory PR, not a change in this repo.

## Step 9 — Wire up CLAUDE.md

Load `.java-coding-standards/adoption/claude-md-templates/full-section-template.md`
and substitute placeholders:

- `{{PROJECT_NAME}}` → project directory name (from step 1)
- `{{PROJECT_GROUP_ID}}` → Maven groupId (from step 1)
- `{{HAS_DEMO_JAVA}}` → "true" if `src/demo/java` exists, else "false"

Then merge into `.claude/CLAUDE.md`:

### If no CLAUDE.md exists

Create one with:

1. A `# CLAUDE.md` header
2. A "## Project Overview" stub the user fills in:

   ```markdown
   ## Project Overview

   <!-- TODO: describe what this project does, who uses it, and any
        load-bearing conventions Claude should know up front. The /init
        adoption flow created this stub; replace it with real content. -->
   ```

3. The three sections from the template ("Java Coding Standards", "FAQ
   MCP Server", "Testing Configuration"), placeholders substituted.

### If a CLAUDE.md exists with old (copied-in) standards sections

Replace the bodies of the matching headings ("Java Coding Standards",
"FAQ MCP Server", "Testing Configuration") with the new template
content, **preserving all other sections** (Project Overview,
Architecture, Development Notes, Code Patterns, Release Process, etc.).

Specifically, you must NOT touch:

- Any "## Project Overview" prose.
- Any "## Architecture Overview" / package descriptions.
- Any "## Development Notes" project-specific content.
- Any "## Code Patterns" examples.
- Any "## Workflow Preferences" or similar project policies.

If the existing CLAUDE.md has a "Workflow Preferences" / "Source Edit
Policy" section telling Claude to present diffs rather than auto-applying
edits to `src/`, **leave it alone** — that's a project-specific policy
that should remain in CLAUDE.md and is not part of the standards adoption.

### If a CLAUDE.md exists with project-specific content but no standards sections

Append the three sections at the end (or after a logical insertion point
like "## Java Coding Standards" before "## Development Notes"). Don't
touch existing content.

Show the user a diff before saving.

## Step 10 — Migrate any pre-existing local copies

If step 1 surfaced existing standards-machinery copies, diff them
against the submodule version, report any project-specific drift, and
delete the local copies once the user confirms.

Files to diff and remove (paths in the project root unless noted):

- `.claude/scripts/fix_*.py` ↔ `.java-coding-standards/tooling/scripts/fix_*.py`
- `.claude/faq_server.py` ↔ `.java-coding-standards/mcp/faq_server.py` (server is generalized; project-name strings will differ — that's expected)
- `.claude/java-coding-standards.md` ↔ `.java-coding-standards/docs/java-coding-standards.md`
- `.claude/faqs/<category>/<topic>.md` for each shared topic
  (`building/java-formatting-standards`, `building/javadoc-reflow-conventions`,
  `conventions/adding-new-faqs`, `testing/system-stubs-and-output-capture`)
  ↔ the submodule's `docs/faqs/...` versions
- `.vscode/java-formatter.xml` ↔ `.java-coding-standards/tooling/ide/java-formatter.xml`
- `checkstyle.xml` ↔ `.java-coding-standards/checkstyle/senzing-checkstyle.xml`
- `checkstyle-suppressions.xml` ↔ `.java-coding-standards/checkstyle/senzing-checkstyle-suppressions.xml`

For each file: if identical → safe to delete. If drift exists → show
the diff to the user, ask whether the drift is project-specific (move
to a project-local FAQ or keep the file) or stale (delete).

**Project-local FAQs that don't have a shared counterpart** stay
untouched. The server will merge them with the shared corpus.

## Step 11 — Generated-file exclusions (interactive)

This step is **mandatory** — the prompt must not silently skip it even
when nothing turns up.

### a. Auto-detect candidates

Scan for telltale signs of generated files:

- Anything under `target/generated-sources/` (or other Maven generated
  output dirs configured via `<source>` plugin entries in pom.xml).
- Files whose first 20 lines contain markers like:
  `// THIS FILE IS GENERATED`, `// Auto-generated`, `// Generated by`,
  `@Generated` annotation usage.
- Files referenced by `<sourceDirectory>` or `<source>` tags in the
  pom that point at non-`src/main/java` paths.

Build a candidate list — but don't assume any of them should actually
be excluded yet.

### b. Inspect any prior `checkstyle-suppressions.xml`

If step 10 found a project-local `checkstyle-suppressions.xml` (now
slated for deletion), extract any `<suppress files="..."/>` entries
that mention specific source files (not blanket category suppressions).
Add those filenames to the candidate list.

### c. Ask the user

Use `AskUserQuestion` with the candidate list as `multiSelect: true`
options:

> **Question:** Which files (if any) should be excluded from the Java
> coding standards? Typically: auto-generated files. We've detected:
> [list]. Select those that should be excluded, and add any others as
> custom text.

If the auto-detect found nothing and there's no prior suppressions
file, ask anyway:

> **Question:** Are there any files in this project that should be
> excluded from the coding standards (typically: auto-generated files
> like wrappers, generated DTOs, etc.)? If yes, paste the file paths
> or globs. If none, just say "none".

### d. Write the exclusion files

For each confirmed exclusion, write two project-local files at the
project root:

- **`checkstyle-suppressions-local.xml`** — one
  `<suppress checks="." files="REGEX"/>` entry per file. Use a regex
  that anchors at the filename (e.g. `SzExceptionMapper\.java` matches
  any path ending in that filename). **No pom wiring needed**: the
  shared `senzing-checkstyle.xml` declares an optional
  `<module name="SuppressionFilter">` that loads this file from the
  project root automatically when it exists.
- **`.java-coding-standards-excludes`** — one gitignore-style glob per
  line (e.g. `**/SzExceptionMapper.java`). Comments allowed. The
  bulk-format scripts read this file via `--exclude-from`.

Both files are committed (not gitignored). Show the user what was
written.

## Step 12 — Optional starter-FAQ generation (interactive opt-in)

Ask the user:

> **Question:** Would you like me to draft a starter set of
> project-specific FAQs by analyzing the project's README, pom.xml,
> package-info.java files, and top-level class javadoc? You'll review
> each draft inline before it's saved.
>
> Recommended for first-time adoptions; skip for projects that already
> have a developed FAQ corpus.
>
> Options: **Yes — generate drafts for review** /
> **No — start with an empty FAQ corpus**

If yes:

1. **Source-analysis pass.** Read:
   - `README.md` (and any `docs/*.md` if present) for
     project overview, build commands, usage examples.
   - `pom.xml` for build commands, key dependencies, plugin
     configuration, JDK version.
   - `package-info.java` for each public package.
   - Top-level public class javadoc for the most-imported types
     (heuristic: rank classes by `import` reference count across the
     codebase).

2. **Draft 3–5 starter FAQs**, one per useful insight. Likely
   categories:
   - `architecture/<project>-overview.md` — high-level module
     structure, key abstractions.
   - `architecture/<key-package>-conventions.md` — for the most
     architecturally load-bearing packages.
   - `building/<project>-build-commands.md` — extracted from
     README + pom.
   - `usage/<key-type>-patterns.md` — only if the source has clear
     usage examples in javadoc.

3. **Show each draft inline** with the file path it would be written
   to. Per draft: **Save as-is** / **Save with edits** / **Discard**.

4. **Save approved drafts** to `.claude/faqs/<category>/`. Discarded
   drafts are not saved.

5. Tell the user the FAQ corpus grows over time via the
   `conventions/adding-new-faqs` feedback loop ("after resolving any
   issue, ask the user if they want to add it as an FAQ").

If no, or if no source-derivable insights surface: empty
`.claude/faqs/` directory. The server still serves all shared FAQs
from the submodule.

## Step 13 — Run verification

Use the checklist at
`.java-coding-standards/adoption/verification-checklist.md`:

```bash
git submodule status                          # clean .java-coding-standards/
mvn -Pcheckstyle validate                     # BUILD SUCCESS
mvn test                                      # all tests pass
python3 .java-coding-standards/tooling/scripts/format_file.py
```

The orchestrator's expected output depends on the project's
history with the format scripts:

- **Project never ran any version of these scripts**, or last ran
  them at the same SHA the submodule is now pinned to: 0
  modifications. The codebase is already in steady-state
  compliance and subsequent runs are no-ops.
- **Project ran an older version of the scripts in the past**
  (e.g. the older copies at `.claude/scripts/` migrated away in
  step 10): some files may be modified by the orchestrator on
  this first post-adoption run. The bulk-format scripts evolve
  over time — most notably, `fix_allman_braces.py` was corrected
  to handle wrapped-condition Allman splits, and Case 5 of that
  script automatically re-aligns previously-buggy outputs left
  behind by older script versions. Treat the resulting diff as
  expected work product: review it, commit it as a follow-up
  "format compliance" commit, and confirm a second orchestrator
  run reports 0 modifications (idempotency).

Restart Claude Code at the end of the session so the FAQ MCP server
re-indexes; verify by calling
`mcp__<project>-faq__get_faq_categories` after restart.

If checkstyle violations surface, **don't auto-fix the source** — show
them to the user, suggest running the bulk-format scripts (or the
orchestrator), and let the user apply.

## Step 14 — Summarize

Produce a concise final report:

- **Files touched**: list with one-line description each.
- **Files removed**: any local copies migrated away in step 10.
- **Project-specific exceptions**: what went into
  `checkstyle-suppressions-local.xml` and
  `.java-coding-standards-excludes`.
- **Starter FAQs saved**: count and titles (if step 12 ran).
- **Items the user should review manually**: any drift findings from
  step 10 the user wanted to keep, the keybinding install, anything
  else flagged during the run.
- **What's next**: tell them they can re-run via `/init-java` after
  any submodule pin bump or to refresh the FAQ corpus.
