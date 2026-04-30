# Security

This repo distributes Python scripts and configuration that consumer
projects auto-execute on every Java save (via `emeraldwalk.runonsave`),
on every Claude Code edit (via `PostToolUse` hook), and on every Claude
session start (via the FAQ MCP server). That's a real attack surface,
so the project maintains a small set of invariants about what its
content may contain.

## Maintained invariants

The following rules apply to every PR against this repository.
Reviewers should reject any change that violates them without an
explicit, documented exception:

1. **No network calls in `tooling/scripts/*.py`.** The bulk-format
   scripts are pure-local file rewrites. Future contributors who want
   to add metrics, telemetry, or remote-config fetching must propose
   it as a separate PR with explicit security review.

2. **PyPI dependencies are version-pinned to exact versions.** Both
   `mcp/faq_server.py`'s PEP 723 metadata and any future tooling use
   `package==X.Y.Z` form, never floating ranges or unpinned names.

3. **No `subprocess.run(shell=True)` and no `os.system` in scripts.**
   All process invocation uses argument-list form with explicit
   path quoting. Path arguments come through `pathlib.Path`, never
   directly into a shell.

4. **No `eval` / `exec` of user-supplied content.** The scripts parse
   Java syntax mechanically; they never `exec` strings.

5. **The CLAUDE.md template installed in consumer projects must not
   include any auto-execution directives.** ("Run X every session" or
   similar.) The standards repo provides Claude with knowledge, not
   auto-pilot.

## Threat model addressed by these invariants

- **Compromised standards repo → local arbitrary code execution.** A
  consumer project that bumps the submodule pin to a malicious commit
  would auto-execute the new code on the next Java save / Claude edit
  / session start. Mitigations: GitHub branch protection on `main`;
  required PR reviews; required signed commits; SHA-pinned submodules
  in consumer projects (so a developer's pin reflects exactly what was
  reviewed when the bump landed); submodule bumps in consumer
  projects always go through PR review.

- **Dependency injection via PEP 723 metadata.** A compromised
  standards repo could rewrite `dependencies = [...]` to pull a
  typo-squatted or compromised package. Mitigation: invariant 2
  (exact version pin) constrains what `uv` will install.

- **Shell injection via path substitution.** VSCode's `${file}` and
  Claude Code's `tool_input.file_path` can contain shell
  special characters if a maliciously-named Java file is ever opened or
  edited. Mitigations: VSCode tasks use array-style `args` (no shell
  parsing); the Claude `PostToolUse` hook command quotes the path
  read from JSON; Python scripts treat paths as `pathlib.Path` and
  honor invariants 3 and 4.

- **Third-party VSCode extension supply chain.** `emeraldwalk.runonsave`
  is widely used but a single-developer extension. A compromised
  update would have arbitrary spawn-process privileges in the editor.
  Mitigations: the adoption flow adds it as a recommendation (not
  auto-install); the format-on-save opt-in checkpoint mentions the
  third-party dependency so users can decline; documented trust
  assumption in `adoption/ADOPTION.md`.

## Out of scope

The following are real risks but inherited from any Java project
with any tooling — this repo does not attempt to address them:

- Trust in `uv` (Astral) — standard Python-tooling supply chain risk.
- Trust in GitHub itself for hosting the submodule.
- Trust in `maven-checkstyle-plugin`, the JDK toolchain, and any
  other plugin a consumer's `pom.xml` declares.

## Reporting a vulnerability

Open a GitHub issue against `senzing-garage/java-coding-standards`
with the `security` label, or contact the Senzing team directly if
the issue requires private disclosure.
