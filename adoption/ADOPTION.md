# Adopting the Senzing Java Coding Standards

This document tells you how to adopt these standards in a Java project.
The recommended path is via Claude Code with the bundled adoption
prompt; a manual path is provided for users who don't use Claude.

## Recommended path: `/init-java` via Claude Code

After the standards repo is added as a submodule, the
`adoption/slash-commands/init-java.md` file gets installed into the
project as `.claude/commands/init-java.md`. Once that's in place, type
`/init-java` in any Claude Code session against this project and Claude
runs the full adoption flow.

### First-time adoption (slash command not yet installed)

The first run is a chicken-and-egg situation: the slash command isn't
in the project yet because the submodule hasn't been added. Two ways
to bootstrap:

1. **Quote the prompt directly** to Claude:

   > Run the standards adoption prompt at
   > `https://github.com/senzing-garage/java-coding-standards/blob/main/adoption/adopt-standards-prompt.md`
   > against this project. Add the submodule first if needed.

   Claude reads the prompt over the web (it's plain markdown) and
   walks the steps. The first step adds the submodule, after which
   the slash command becomes available for future runs.

2. **Add the submodule manually first**:

   ```bash
   git submodule add \
     https://github.com/senzing-garage/java-coding-standards.git \
     .java-coding-standards
   git submodule update --init
   ```

   Then in Claude Code, run:

   > @.java-coding-standards/adoption/adopt-standards-prompt.md run this

### What the adoption prompt does

The prompt (`adopt-standards-prompt.md`) is the canonical specification
of what gets wired up. Briefly:

| Step | What it does |
|---|---|
| 1 | Detect project shape (single/multi-module, JDK version, existing artifacts) |
| 2 | Add the `.java-coding-standards/` submodule |
| 3 | Update `pom.xml` profiles (checkstyle, jacoco, spotbugs, surefire) |
| 4 | Add `<project>-faq` MCP server entry to `.mcp.json` |
| 5 | Configure `.vscode/` (settings, tasks, extensions, keybinding hint, hooks, slash command) |
| 6 | `.vscode/cspell.json` — no-op (out of scope) |
| 7 | `.gitignore` — no-op (out of scope) |
| 8 | GitHub workflows — no-op (owned by senzing-factory) |
| 9 | Merge three sections into `.claude/CLAUDE.md` |
| 10 | Migrate any pre-existing local copies of standards artifacts |
| 11 | **Interactive**: identify generated-file exclusions |
| 12 | **Interactive opt-in**: draft starter project-specific FAQs |
| 13 | Run `mvn -Pcheckstyle validate`, `mvn test`, format-script smoke |
| 14 | Summarize what changed |

### What you'll be asked

Three interactive checkpoints:

1. **Format-on-save**: enable the `emeraldwalk.runonsave` extension
   to reformat Java files on every save? (Alternative: keybinding-only.)
2. **Submodule freshness nudge**: enable a `SessionStart` hook that
   prints a one-line reminder if the submodule is behind upstream?
3. **Generated-file exclusions**: which (if any) files should be
   excluded from the standards (typically auto-generated code)?
4. **Starter FAQs** (optional opt-in): draft 3–5 project-specific FAQs
   from README + pom + package-info + javadoc analysis, with per-draft
   review?

Everything else runs without prompting.

### Trust and security

The adoption flow auto-runs Python scripts in three places (VSCode
keybinding, `emeraldwalk.runonsave` if opted in, Claude Code
`PostToolUse` hook). Three trust assumptions worth understanding:

- **The standards repo itself**: branch protection, signed commits, and
  SHA-pinned submodules in consumer projects mean a malicious upstream
  change can't reach your machine without an explicit pin bump that
  goes through PR review.
- **The `mcp` Python package**: pinned to an exact version
  (`mcp==1.27.0`) in `mcp/faq_server.py`'s PEP 723 metadata so `uv`
  can't pull a typo-squatted replacement.
- **`emeraldwalk.runonsave`**: a third-party VSCode extension. We add
  it as a *recommendation* (not auto-install), and the format-on-save
  opt-in checkpoint mentions the trust assumption explicitly. You can
  decline.

The `SECURITY.md` in this repo's root documents the maintained
invariants (no network calls in scripts, no `subprocess.run(shell=True)`,
no `eval`/`exec` of user content, etc.).

## Manual path (no Claude)

If you prefer to wire things up by hand (or want to see what the
adoption prompt does before running it), follow each step in
`adopt-standards-prompt.md` directly. The templates under
`claude-md-templates/` are drop-in for the build/IDE/Claude
configuration; the CLAUDE.md template uses simple `{{PROJECT_NAME}}`
placeholders you substitute manually.

The pieces that genuinely benefit from Claude (and are tedious by hand)
are step 9 (CLAUDE.md merge that preserves project-specific sections)
and step 10 (drift detection between local copies and the submodule).
Everything else is mechanical.

## After adoption

- **Re-run `/init-java`** after any submodule pin bump to refresh
  configuration files and CLAUDE.md sections against the latest
  standards content.
- **Add project-specific FAQs** under `.claude/faqs/<category>/<topic>.md`.
  The `conventions/adding-new-faqs` shared FAQ documents the workflow.
- **Contribute back to the standards repo** when you find improvements
  to the rules, scripts, or shared FAQs — open a PR against
  `senzing-garage/java-coding-standards`.

## Optional: pre-commit hook

A pre-commit hook that runs `format_file.py` against staged Java files
is **not** installed by the adoption flow but is documented here for
projects that want a commit-time gate in addition to the save-time +
keybinding + Claude-hook flows. Sample:

```bash
# .git/hooks/pre-commit
#!/bin/bash
staged=$(git diff --cached --name-only --diff-filter=ACMR | grep '\.java$')
if [ -n "$staged" ]; then
  python3 .java-coding-standards/tooling/scripts/format_file.py $staged
  git add $staged
fi
```

This is intentionally a per-project, opt-in choice — automated commit
hooks have their own trust considerations independent of the standards.
