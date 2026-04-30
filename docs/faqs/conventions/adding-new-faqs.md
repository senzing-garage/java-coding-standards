## Adding New FAQs

The FAQ MCP server reads markdown files at startup from two locations and serves their contents through `search_faqs`, `get_faq`, and `get_faq_categories`:

- **Shared FAQs** — `.java-coding-standards/docs/faqs/<category>/<topic>.md` in the standards-repo submodule. Project-agnostic content that ships with the standards.
- **Project-local FAQs** — `.claude/faqs/<category>/<topic>.md` in the consumer project. Project-specific content (architecture overview, build commands, troubleshooting, release notes, etc.).

The server merges both into one BM25-ranked index, so a single search returns hits from either source.

### How to add a project-local FAQ

1. Pick or create a category directory under `.claude/faqs/` (e.g. `architecture`, `building`, `troubleshooting`, `conventions`).
2. Create a markdown file. **The filename becomes the searchable title** — use dashes for spaces (e.g. `connection-pool-tuning.md` → "connection pool tuning").
3. Keep each file focused on one topic. BM25 ranks shorter, focused documents higher than sprawling ones.
4. Restart the Claude session (or reconnect MCP) so the server re-indexes.

### How to add a shared FAQ (standards-repo contributors only)

Shared FAQs live at `.java-coding-standards/docs/faqs/<category>/<topic>.md`. Two extra rules apply because the content ships to every adopting project:

- **No project-specific examples.** No real class names, file paths, or identifiers from any one consumer. Use synthetic placeholders (`Foo`, `Bar`, `MyService`) when an example is needed.
- **Submit via PR to the standards repo.** New shared FAQs go through the same review as any other change to the standards.

### What belongs in a FAQ vs CLAUDE.md

- **CLAUDE.md** — coding conventions, build commands, package overview; always loaded into context, so keep it lean.
- **FAQ** — design rationale, operational gotchas, troubleshooting recipes, release checklists; pulled on demand, so detail is cheap.
- **Auto-memory** (`~/.claude/projects/.../memory/`) — user preferences and cross-session state; not project-scoped knowledge.

### Feedback loop

After Claude resolves a non-obvious issue (build quirk, dependency interaction, test flake, release hiccup), it should ask the user whether to capture the solution as a new FAQ. The goal is to grow the corpus so future sessions recover the answer instantly via `search_faqs`.

If the lesson is project-specific, the FAQ goes into `.claude/faqs/`. If it's about the standards or the shared tooling itself (formatter, scripts, FAQ server), it belongs in the standards repo and goes in via PR.
