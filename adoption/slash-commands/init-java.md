---
description: Adopt or refresh the Senzing Java coding standards in this project.
---

Run the adoption playbook from the standards-repo submodule:

@.java-coding-standards/adoption/adopt-standards-prompt.md

This wires up checkstyle, the FAQ MCP server, the formatter, the bulk-format
scripts, the VSCode integration, the Claude Code hooks, and the CLAUDE.md
sections — all sourced from the submodule pin. Re-run any time to refresh
after a submodule bump or to onboard a fresh Java project.

The command is deliberately distinct from Claude Code's built-in `/init`,
which continues to work unchanged for projects that just need a CLAUDE.md
without the standards machinery.
