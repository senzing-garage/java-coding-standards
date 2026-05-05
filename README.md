# Senzing Java Coding Standards

The canonical home for the formatting rules, build configuration, FAQ
content, and tooling shared across Senzing Java projects. Consumer
projects mount this repo as a git submodule at
`.java-coding-standards/` and reference its files directly — there is
no published artifact (no Maven Central, no PyPI). One submodule pin
gives a project the rules, the docs, the FAQ corpus, the formatter
profile, the bulk-format scripts, and the FAQ MCP server in lockstep.

## What's in here

```
checkstyle/
    senzing-checkstyle.xml                — checkstyle config consumed by
                                             maven-checkstyle-plugin
    senzing-checkstyle-suppressions.xml   — shared base; consumer projects
                                             layer their own
                                             checkstyle-suppressions-local.xml

docs/
    java-coding-standards.md              — the canonical 912-line rules doc
    faqs/                                 — shared FAQs the FAQ server bundles
        building/java-formatting-standards.md
        building/javadoc-reflow-conventions.md
        conventions/adding-new-faqs.md
        testing/system-stubs-and-output-capture.md

tooling/
    ide/java-formatter.xml                — Eclipse JDT formatter profile
                                             consumed by both jdt-formatter
                                             (CLI) and redhat.java (IDE)
    jdt-formatter/                        — thin Java CLI wrapping the
                                             Eclipse JDT formatter.
                                             The fat JAR is NOT
                                             committed; it's published
                                             as a GitHub Release asset
                                             per release tag, with a
                                             SHA-256 sidecar.
                                             format_file.py downloads
                                             on first use and caches.
        pom.xml                           — depends on
                                             org.eclipse.jdt:org.eclipse
                                             .jdt.core; tracked by
                                             Dependabot (21-day cooldown)
        src/main/java/.../JdtFormatter.java
    scripts/                              — orchestrator + override scripts
        _cli.py                           — shared argparse + iter helpers
        format_file.py                    — orchestrator: runs JDT pass
                                             then six fix_*.py overrides
        fix_allman_braces.py              — Allman brace placement override
        fix_javadoc_reflow.py             — javadoc no-orphan reflow
        fix_javadoc_inline_tags.py        — javadoc inline-tag reflow
        fix_javadoc_tags.py               — @param/@return/@throws reflow
        fix_need_braces.py                — short-circuit if rules
        fix_throws_alignment.py           — column-aligned throws clauses

mcp/
    faq_server.py                         — generic FAQ MCP server, invoked
                                             by consumer projects via uv
                                             with PEP 723 inline metadata

adoption/
    ADOPTION.md                            — human-readable adoption guide
    adopt-standards-prompt.md              — master Claude Code prompt
    slash-commands/init-java.md            — installed in consumer projects
                                              as .claude/commands/init-java.md
    claude-md-templates/                   — drop-in pom / mcp / vscode /
                                              claude-hooks templates
    verification-checklist.md              — post-adoption gates

SECURITY.md                                — maintained invariants for
                                              contributors
README.md                                  — this file
```

## How a consumer adopts this

```bash
# In the consumer project:
cd <project-root>
git submodule add \
  https://github.com/senzing-garage/java-coding-standards.git \
  .java-coding-standards
git submodule update --init
```

Then, in a Claude Code session against the project:

```
@.java-coding-standards/adoption/adopt-standards-prompt.md run this
```

Claude walks the adoption flow end to end — pom updates, MCP server
entry, VSCode integration, Claude Code hooks, CLAUDE.md merge,
generated-file exclusion prompt, optional starter-FAQ generation,
verification gates. Re-run later as `/init-java` (the slash command
gets installed by the first run) any time you want to refresh after a
submodule pin bump.

See `adoption/ADOPTION.md` for the full guide, including the manual
(non-Claude) path.

## Distribution philosophy

**Pure git submodule, no published artifacts.** The standards repo is
the single source of truth for rules, configs, docs, and tooling. A
single SHA pin in a consumer's `.gitmodules` selects exactly which
version of all of those a project is on — no skew between
"checkstyle.xml v1" and "FAQ corpus v2" because they ship as one
submodule snapshot.

CI workflows are out of scope and stay with
`senzing-factory/build-resources`. The standards repo only provides
the config files those workflows already consume.

## Contributing

Improvements to the standards, scripts, FAQs, or templates are
welcome. PRs go to the `main` branch and require:

- Branch protection: no direct pushes; reviewer approval required.
- Signed commits.
- The maintained invariants in `SECURITY.md` continue to hold.

When updating a shared FAQ, keep it project-agnostic (no real class
names, file paths, or identifiers from any one consumer — use
synthetic placeholders).

## Versioning

Tags follow semver. Pre-1.0 (`v0.x.y`) the API surface is still
stabilizing — minor versions may carry meaningful behavioral changes
to scripts and templates. Once a `v1.0.0` is cut, semver guarantees
apply normally.

Consumer projects pin to a tag SHA. Bumps are submitted as PRs in
consumer projects so the diff is visible to reviewers and never
silently rolled in CI.

## License

Apache 2.0 (matches the consumer projects).
