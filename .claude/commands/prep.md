# Prepare for Commit

**TWO MODES:**

- **DEFAULT (fast)**: same correctness checks as `--full`, but parallelized and with hardcoded omissions (doc-build, examples, assembly, redundant builds). NO LLM JUDGMENT about what's relevant — the only "skips" are mechanical (hardcoded fast-mode-omits) or trivially testable (lock-file diff is a one-line shell test, not a decision the agent makes).
- **`--full` (thorough)**: adds doc build, examples, dep audit unconditionally, assembly. Use before a release tag.

**Both modes ALWAYS run, in every project language present:** stale-files, format-check, lint, type-check, compile, test, FAQ review, status+next-steps, changelog. Speed comes from PARALLELISM and from skipping things that aren't correctness gates (doc, examples, assembly), not from skipping language tests.

**MANDATORY: You MUST launch an Opus agent (`model: "opus"`) to perform the checks. This is NOT optional. The agent provides independent verification. If you skip the agent or run checks manually instead, you are violating this directive. "Nothing to commit" or "already pushed" does NOT exempt you from launching the agent — the agent validates the CURRENT STATE of the branch.**

**EXECUTION:** Pass this entire prompt as the agent's task, plus the **mode** (`fast` or `full`). The agent must:

1. Detect ALL languages present in the project (`pom.xml` / `build.gradle` → Java; `pyproject.toml` / `requirements.txt` → Python; etc.). Run checks for **every** detected language; the agent does NOT decide which ones to skip based on diff content.
2. **Run independent checks in parallel** via the Bash tool's `run_in_background: true` and `Monitor` for completion. Sequential is the wrong default.
3. Cap checks with timeouts (`mvn test` 15 min, `pytest` 5 min, others 5 min) — kill and report timeout as ❌ if exceeded.
4. Report a structured ✅/❌ summary. Do NOT paste full logs; extract the FAILING line(s) only.
5. **Final line of the report MUST be a `/clear` readiness verdict.** See "/clear Handoff Verdict" section below — this is mandatory and non-negotiable. /prep is BOTH a commit-readiness gate AND a session-handoff gate; the latter is the more rigorous of the two and dominates the summary line.

**FAST-MODE OMISSIONS (hardcoded; NOT diff-dependent):**

- `mvn javadoc:javadoc`, `mvn site` — `--full` only (these aren't correctness gates)
- `mvn package` / `mvn install` — `--full` only (compile + test already prove the bulk of the build)
- `markdown-table-formatter` + `prettier --write` over the whole tree — SKIP unconditionally; rewriting hand-tuned plan files mid-prep is a foot-gun. Use `prettier --check` (no write) on the whole `.md` tree instead.

**SHELL-GATED (mechanical; deterministic test, no LLM judgment):**

- `mvn -Pspotbugs spotbugs:check` — run iff `git diff --name-only origin/main...HEAD -- 'src/**/*.java' 'pom.xml' | grep .` is non-empty. Otherwise skip with note "no Java code changes."
- `pip-audit` / `safety check` — run iff `git diff --name-only origin/main...HEAD -- '**/requirements*.txt' '**/pyproject.toml' | grep .` is non-empty.

**ALWAYS RUN (no skip ever, both modes):**

- All language formatters (`format_file.py` for Java; `ruff format --check` for Python if configured).
- All language linters (`mvn -Pcheckstyle validate`; `ruff check` if configured).
- All language compilers / type-checkers (`mvn compile`; `mypy` if configured).
- All language test suites (`mvn test`; `pytest`).
- Universal: stale-files, FAQ review, status+next-steps, CHANGELOG, GitHub Actions pin check.

**MANDATORY PARALLELISM:**
The agent must fan out independent checks concurrently:

```
parallel group A (Java):     mvn -Pcheckstyle validate  &  format_file.py --check
parallel group B (Python):   ruff check  &  pytest -q
parallel group C (universal): git status --porcelain  &  prettier --check '**/*.md'
parallel group D (tests):    mvn test  &  pytest tests/
```

Group D dominates wall time; A, B, C should complete while tests run. Sequential execution of independent checks is a bug.

## Quick Reference

| Check           | Java (Maven)                                        | Java (Gradle)                                   | Python                                          |
| --------------- | --------------------------------------------------- | ----------------------------------------------- | ----------------------------------------------- |
| Stale files     | `git status`                                        | `git status`                                    | `git status`                                    |
| Markdown        | `markdown-table-formatter` + `prettier --check`     | `markdown-table-formatter` + `prettier --check` | `markdown-table-formatter` + `prettier --check` |
| Format          | `format_file.py` (Senzing)                          | `format_file.py` (Senzing)                      | `ruff format --check` (if configured)           |
| Lint            | `mvn -Pcheckstyle validate`                         | `./gradlew checkstyleMain`                      | `ruff check` (if configured)                    |
| Type Check      | (compile catches it)                                | (compile catches it)                            | `mypy` (if configured)                          |
| Compile         | `mvn compile`                                       | `./gradlew compileJava`                         | (none — interpreted)                            |
| Static Analysis | `mvn -Pspotbugs spotbugs:check` (if profile exists) | `./gradlew spotbugsMain`                        | (Bandit if configured)                          |
| Tests           | `mvn test`                                          | `./gradlew test`                                | `pytest`                                        |
| Coverage        | `mvn -Pjacoco verify` (if profile exists)           | `./gradlew jacocoTestReport`                    | `pytest --cov` (if configured)                  |
| Package         | `mvn package` (`--full` only)                       | `./gradlew build -x test` (`--full` only)       | (none for libraries)                            |
| Docs            | `mvn javadoc:javadoc` (`--full` only)               | `./gradlew javadoc` (`--full` only)             | (n/a)                                           |
| Changelog       | CHANGELOG.md                                        | CHANGELOG.md                                    | CHANGELOG.md                                    |

**Note:** This repo (`java-coding-standards`) is itself a Python + Markdown project — the formatter tooling at `tooling/scripts/format_java.py` is the primary artifact. Adopter projects are typically Java; some carry a small Python ancillary script tree.

---

## Project Detection

- **Java (Maven)**: `pom.xml` in current directory or parent directory tree.
- **Java (Gradle)**: `build.gradle` or `build.gradle.kts` with the `java` plugin in current directory.
- **Python**: `pyproject.toml`, `setup.py`, or `requirements*.txt` in current directory or under `tooling/scripts/`.
- If none found, ask user.

**Multi-language projects:** This standards-repo itself combines Python (the formatter) + Markdown (docs). Most adopters combine Java (the consumer code) + Python (the formatter tooling pulled in via this submodule). Detect ALL languages and run checks for each section that applies.

---

## Universal Checks

### 1. Stale Files Check

Run `git status --porcelain` and flag these patterns if staged:

**Planning/Notes:**

- `plan*.md`, `PLAN*.md`, `*_plan.md`
- `TODO.md`, `NOTES.md`, `SCRATCH.md`
- `commit_message*.txt`

**Temporary/Backup:**

- `*.tmp`, `*.temp`, `*.bak`, `*.backup`, `*.orig`
- `*.swp`, `*.swo`, `*~`
- `.DS_Store`
- Files in `tmp/`, `temp/`, `.tmp/`, `target/`, `__pycache__/`

**Debug/Scratch Code:**

- `Debug*.java`, `Scratch*.java`, `*Test_scratch*.java`
- `debug_*.py`, `test_scratch_*.py`

If flagged files are staged, prompt user to remove them.

### 2. Markdown Formatting

Format all markdown files:

```bash
# Fix table alignment (MD060) — handles emoji/Unicode width correctly
npx markdown-table-formatter "**/*.md"

# Format with prettier
npx prettier --write "**/*.md" --ignore-path .prettierignore
```

If prettier is not installed globally, use `brew install prettier` (macOS) or `npm install -g prettier`.

Verify with:

```bash
npx prettier --check "**/*.md" --ignore-path .prettierignore
npx markdownlint-cli "**/*.md" --ignore node_modules
```

### 3. FAQ MCP Update

If the project has a FAQ MCP server (check for `docs/faqs/` at the root of the standards submodule OR `.claude/faqs/` in the project), review whether any FAQ entries need updating based on changes in this session. This is MANDATORY — do NOT skip.

**Detection:** Look for `docs/faqs/` directories (this submodule's shared FAQs) or `.claude/faqs/` (project-local FAQs). Both feed the same FAQ MCP server.

**Review process:**

1. Use `search_faqs(query)` to find FAQs potentially affected by this session's changes.
2. Read the affected FAQ markdown files directly.
3. Update or create FAQ entries for:
   - **New patterns or conventions** discovered during the session.
   - **Build/test/CI knowledge** gained (e.g., CI check behavior, suppression mechanisms, new build flags, new Maven profiles).
   - **Corrections to existing FAQs** found during work — fix inaccuracies.
   - **New tooling or commands** introduced.
   - **Architecture decisions** made that affect how others should work with the code.
   - **Performance findings** (profiling results, optimization patterns, what worked / what didn't).
4. Write changes directly to the FAQ markdown files.
5. Stage FAQ changes alongside code changes.

FAQs are the project's institutional memory. If you learned something non-obvious during this session that would help the next developer (or the next Claude session), it belongs in a FAQ. **Spec-shaped learnings belong in the standards submodule (`docs/faqs/`); project-local learnings belong in `.claude/faqs/` of the adopter project.**

### 4. Status + Next-Steps Handoff (MANDATORY)

After /prep completes, the user may `/clear` and resume in a fresh session. The next session needs enough context to pick up cleanly without re-deriving everything from git log + memory. **This is NOT optional.**

**What to capture:**

1. **Current status** — what is the state of in-flight work right now? In particular:
   - Any background processes still running (CI runs, formatter batches, monitors) with task IDs / log paths.
   - What's pending on the critical path (e.g., "CI rerun on PR #N waiting for spellcheck", "formatter batch over 1200 files in flight").
   - What was just landed in git (commit hashes + one-line summaries).
   - Open questions awaiting external systems (CI results, reviewer feedback).
   - Any uncommitted-but-deliberate working-tree state (with rationale).

2. **Next steps** — what should the next session do, in priority order? Be specific:
   - "When CI completes, verify spellcheck green and merge PR #N" — not "merge".
   - Include exact commands / file paths / config keys / commit hashes.
   - Surface the decision points (e.g., "if any LineLength remains after format, capture in fixture and add CSOFF or rename identifier").

3. **Anything the next session would not be able to recover from git + memory alone**:
   - Mental model of the current investigation (e.g., "we proved approach A worked at scale X but bottleneck B blocked it").
   - Why current choices were made over alternatives (rejected paths matter).
   - Known fragility: "do NOT re-run the bulk format without first reverting the X working-tree change".

**Where to write it:**

- **Project-level**: write to `.claude/STATUS.md` and `.claude/NEXT_STEPS.md` (or update if they exist) in the project repo. These are gitignored or committed depending on project convention.
- **Cross-session memory**: also update auto-memory `MEMORY.md` with a `/clear handoff` block summarizing the same — this survives /clear in the user's home directory and is what a fresh session sees first. Keep MEMORY.md `/clear handoff` entries terse (≤150 lines per entry).
- **Project memory file**: if the project has a `project_session_YYYYMMDD.md` pattern in memory (check `MEMORY.md` index), follow it.

**Quality bar:** if the next session reads only `MEMORY.md` + `STATUS.md` + `NEXT_STEPS.md` + recent git log, can they recover and continue? If no, the handoff is incomplete.

**Special-case check before /clear:** are any background tasks (Monitor, Bash run_in_background, cron, nohup processes) still running that the next session needs to know about? List them explicitly with task ID / PID / what they're watching / when they're expected to fire next.

### 4.1 /clear Handoff Verdict (MANDATORY — final line of /prep output)

The /prep agent MUST end its summary with one of two explicit verdicts. This is non-negotiable. The user will use this line to decide whether to `/clear` and resume in a fresh session.

**The verdict is BINARY: SAFE TO /clear, or NOT SAFE.** No middle ground, no qualifications buried in prose. If any handoff item is missing or stale, the verdict is NOT SAFE and the agent must say _what is missing_.

**The verdict is computed from this checklist** — every box must be checked for SAFE TO /clear:

- [ ] **STATUS.md** exists and reflects current branch HEAD + in-flight CI cycle state + background-task inventory.
- [ ] **NEXT_STEPS.md** exists with priority-ordered actionable items, including exact commands/paths/SHAs (no "validate the thing" — must be "run X against Y, expect Z").
- [ ] **FAQ MCP entries** updated for any non-obvious learning this session (architecture decisions, build/test/CI knowledge, corrections to existing FAQs, new tooling). FAQs MUST be written directly to the appropriate FAQ markdown file — surfacing-for-user-decision is NOT acceptable; if the agent identifies a FAQ-worthy learning, the agent writes the FAQ entry.
- [ ] **MEMORY.md /clear handoff block** written/updated. The block must be linked from `MEMORY.md` index and contain everything that would NOT be recoverable from `git log + STATUS.md + NEXT_STEPS.md + git working-tree state` alone (mental model, rejected paths, fragility warnings, container creds, cron/Monitor IDs).
- [ ] **All session commits pushed** OR explicitly listed as "deliberately held local" with reason in the handoff.
- [ ] **/prep gates green** (or every ❌ explicitly explained as "deliberately deferred" with reason).
- [ ] **Background tasks documented**: cron jobs (with IDs and what they fire), background `Monitor` / `run_in_background` tasks (with task IDs).
- [ ] **Working-tree state**: clean OR every dirty/untracked path is explicitly accounted for as "pre-existing this session" OR "deliberate WIP, see <handoff section>".

**Verdict format** (exact strings — downstream automation may parse these):

```
HANDOFF VERDICT: SAFE TO /clear
```

OR

```
HANDOFF VERDICT: NOT SAFE TO /clear
Missing:
  - <bullet for each unchecked checklist item, terse>
Action required before /clear:
  - <one-line action per missing item>
```

**The agent does NOT dismiss handoff items as out-of-scope.** "Already pushed, nothing to commit" does NOT exempt /prep from the handoff checklist — handoff is about session-state continuity, not commit-state. Even on a no-op session where nothing changed, /prep must verify the existing STATUS / NEXT_STEPS / MEMORY are still accurate (or update them) before declaring SAFE TO /clear.

**The agent does NOT fabricate "SAFE TO /clear" by surfacing missing items as "for user decision".** Surfacing-as-note means "I found a thing that should happen, you decide" — that is BLOCKING for the verdict, not a punt. If the agent identifies a FAQ-worthy learning, the agent writes the FAQ entry; if it identifies a stale STATUS section, the agent updates STATUS; etc. The verdict is SAFE only when nothing is left in the "user decides" bucket.

**Why this section exists:** in practice, /prep agents have closed sessions saying "Ready for commit ✅" while leaving FAQ updates "for user decision", forgetting MEMORY.md, and writing STATUS without NEXT*STEPS. That makes the next session start half-blind. The handoff verdict forces the agent to be explicit about whether the \_next* session can pick up cleanly, not just whether the _current_ commit is shippable.

### 5. CHANGELOG.md

Verify CHANGELOG.md exists and is updated with current changes.

**If CHANGELOG.md doesn't exist:** Create one with the standard format:

```markdown
# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- New features

### Changed

- Changes to existing functionality

### Removed

- Removed features

### Fixed

- Bug fixes
```

**If CHANGELOG.md exists:** Add entries under `## [Unreleased]` for all changes in the current session, or under the next release header if a release is in flight.

### 6. GitHub Actions Pin Check

If the project has `.github/workflows/` files, verify all third-party actions use **Dependabot-compatible hash pinning**:

```yaml
# ❌ WRONG — tag only, no hash
- uses: actions/checkout@v4

# ❌ WRONG — hash without tag comment (Dependabot can't update)
- uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11

# ✅ CORRECT — hash-pinned with tag comment for Dependabot
- uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11 # v4.1.1
```

Check with:

```bash
# Find workflow files
find .github/workflows -name '*.yml' -o -name '*.yaml' 2>/dev/null

# Flag unpinned actions (uses: org/action@vN without hash)
grep -n 'uses:.*@v[0-9]' .github/workflows/*.yml 2>/dev/null

# Flag hash-pinned without tag comment
grep -n 'uses:.*@[0-9a-f]\{40\}' .github/workflows/*.yml 2>/dev/null | grep -v '#'
```

If violations found, report them. Do NOT auto-fix — the correct hash must be looked up from the action's repository.

### 7. Supply-Chain Hash Pinning (MANDATORY, both modes)

Every dependency that the toolchain will fetch from a network MUST be pinned to an immutable version so the next build resolves to **byte-identical** content. A floating version range, missing lock file, or unpinned snapshot dep is a supply-chain attack surface — a malicious push to upstream silently rolls into the next build.

**Mechanical (no LLM judgment), fail-on-violation:**

**Java / Maven** — run when `pom.xml` exists:

```bash
# (a) All <version> declarations MUST be a fixed version. Reject SNAPSHOT
#     in release-track pom.xml and reject Maven version ranges like [1.0,2.0).
grep -nE '<version>[^<]*-SNAPSHOT</version>' pom.xml \
  && echo "VIOLATION: SNAPSHOT dependency in pom.xml"
grep -nE '<version>[^<]*[\[\(][^<]*[\]\)]</version>' pom.xml \
  && echo "VIOLATION: version range in pom.xml"
# (b) Optional but recommended: a `dependency:tree` check against a known
#     baseline to catch transitive drift.
```

**Java / Gradle** — run when `build.gradle` exists:

```bash
# Floating "latest.release" / "+" version specs are banned in release tracks.
grep -nE "['\"][^'\"]+:[^'\"]+:(latest\.release|\+)['\"]" build.gradle build.gradle.kts 2>/dev/null \
  && echo "VIOLATION: floating Gradle version"
```

**Python** — run when `requirements*.txt` or `pyproject.toml` exists:

```bash
# (a) requirements*.txt entries MUST be pinned to == versions (or use
#     pip-compile / uv-generated lock files).
grep -nE '^[a-zA-Z0-9_-]+(?!==)' requirements*.txt 2>/dev/null \
  | grep -vE '^#|^$|^-r ' \
  && echo "VIOLATION: unpinned Python requirement"
# (b) If pyproject.toml is the source-of-truth, dependencies should pin or
#     use compatible-release (~=) ranges with a committed lock file
#     (requirements-lock.txt, uv.lock, etc.).
```

**GitHub Actions**: covered in Section 6 above.

**Output**: each violation is a ❌ that blocks commit. Fix is a deterministic mechanical change (pin to the latest immutable version, generate a lock file, etc.) — NOT an LLM judgment call.

### 7.1 21-Day Dependency Cooldown (MANDATORY)

Best practice for supply-chain hardening: dependency updates must wait **≥21 days** between upstream publish and our adoption. The window gives the security community time to detect compromised releases before they reach our build.

**Enforcement is declarative via Dependabot's built-in `cooldown` config.** Dependabot will not propose a dep update unless the new version meets the cooldown threshold; it filters at PR-generation time, on GitHub's servers, with no per-/prep network calls needed.

**Cooldown applies to _version_ updates ONLY.** Per GitHub's spec ([dependabot cooldown docs](https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuration-options-for-the-dependabot.yml-file#cooldown--)): "the `cooldown` option is only available for _version_ updates, not _security_ updates". A Dependabot security advisory PR (GHSA / OSV ingestion) bypasses cooldown entirely, so HIGH/CRITICAL CVEs land within hours regardless of the cooldown window. Cooldown is the routine-bump safety net, not the security gate.

**The /prep check is one shell test:** verify `.github/dependabot.yml` exists and has `cooldown.default-days >= 21` for every package ecosystem the repo uses.

```bash
# Mechanical check — no network, no LLM judgment.
F=.github/dependabot.yml
if [ ! -f "$F" ]; then
  echo "❌ COOLDOWN: $F missing — Dependabot can't enforce the 21-day cooldown"
  exit 1
fi
# Verify cooldown.default-days >= 21 (yq is the right tool, falls back to grep if absent).
if command -v yq >/dev/null 2>&1; then
  days=$(yq '.updates[].cooldown.default-days // .cooldown.default-days // 0' "$F" | sort -n | head -1)
  [ "$days" -ge 21 ] || { echo "❌ COOLDOWN: dependabot.yml has cooldown.default-days=$days, must be ≥21"; exit 1; }
else
  grep -A1 'cooldown:' "$F" | grep -qE 'default-days:\s*(2[1-9]|[3-9][0-9]+)' \
    || { echo "❌ COOLDOWN: dependabot.yml has no cooldown.default-days ≥21"; exit 1; }
fi
```

**Reference dependabot.yml**:

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: maven
    directory: /
    schedule: { interval: weekly }
    cooldown: { default-days: 21 }
  - package-ecosystem: pip
    directory: /tooling/scripts
    schedule: { interval: weekly }
    cooldown: { default-days: 21 }
  - package-ecosystem: github-actions
    directory: /
    schedule: { interval: weekly }
    cooldown: { default-days: 21 }
```

**Manual dep bumps** (developer hand-edits pom.xml / requirements.txt directly, bypassing Dependabot): the cooldown intent still applies, but enforcement falls to discipline and code review. Don't hand-bump to a release < 21 days old without a documented `Cooldown-Override:` reason in the commit message; reviewers reject otherwise. /prep can grep the commit message for that override-or-explain pattern when a pom.xml / requirements.txt / workflow yml shows a hand-edited version bump.

---

## Java Checks

Run these in order. Stop on first failure.

### Java with Maven

| #   | Check              | Command                                                            | Notes                                                          |
| --- | ------------------ | ------------------------------------------------------------------ | -------------------------------------------------------------- |
| 1   | Format             | `python3 .java-coding-standards/tooling/scripts/format_file.py`    | Run, then `git status` — any modified files mean format drift  |
| 2   | Lint               | `mvn -Pcheckstyle validate`                                        | Must report BUILD SUCCESS; zero LineLength / style violations  |
| 3   | Compile            | `mvn compile`                                                      | Including test sources via `mvn test-compile`                  |
| 4   | Static Analysis    | `mvn -Pspotbugs spotbugs:check`                                    | Only if the `spotbugs` profile exists                          |
| 5   | Tests              | `mvn test`                                                         | 100% pass rate                                                 |
| 6   | Coverage           | `mvn -Pjacoco verify` then inspect `target/site/jacoco/index.html` | Only if `jacoco` profile exists; flag uncovered modified files |
| 7   | Doc Review         | Check README.md, CLAUDE.md, `docs/faqs/**`                         | Update if API/features changed                                 |
| 8   | Package (`--full`) | `mvn package`                                                      | Verify the JAR builds clean                                    |
| 9   | Javadoc (`--full`) | `mvn javadoc:javadoc`                                              | Must build without warnings                                    |

**Senzing project conventions:**

- Profile IDs `checkstyle` / `jacoco` / `spotbugs` / `release` align with `sz-sdk-java`. Bulk-mvn invocations like `mvn -Pcheckstyle validate` should always work in adopter projects.
- The Java formatter is `python3 .java-coding-standards/tooling/scripts/format_file.py`, NOT `mvn formatter:format`. The standards submodule's Python formatter is the canonical source.
- After a fresh adopter run, `format_file.py` should report `Formatter: N files processed, 0 modified.` That's the idempotency gate — if N > 0 modified, the working tree drifted from spec since the last run.

### Java with Gradle

| #   | Check              | Command                                                         | Notes                                                      |
| --- | ------------------ | --------------------------------------------------------------- | ---------------------------------------------------------- |
| 1   | Format             | `python3 .java-coding-standards/tooling/scripts/format_file.py` | Same as Maven — Senzing formatter is build-system-agnostic |
| 2   | Lint               | `./gradlew checkstyleMain checkstyleTest`                       | Or `./gradlew check`                                       |
| 3   | Compile            | `./gradlew compileJava compileTestJava`                         |                                                            |
| 4   | Static Analysis    | `./gradlew spotbugsMain`                                        | If the spotbugs plugin is wired                            |
| 5   | Tests              | `./gradlew test`                                                | 100% pass rate                                             |
| 6   | Coverage           | `./gradlew jacocoTestReport`                                    | If jacoco plugin is wired                                  |
| 7   | Doc Review         | Check README.md, CLAUDE.md                                      | Update if API/features changed                             |
| 8   | Build (`--full`)   | `./gradlew build`                                               | Full assembly                                              |
| 9   | Javadoc (`--full`) | `./gradlew javadoc`                                             | Must build without warnings                                |

### Java Patterns Required

- All code conforms to `.java-coding-standards/docs/java-coding-standards.md` (Allman braces, 80-char line limit, javadoc reflow, parameter alignment, etc.).
- `// CSOFF` / `// CSON` markers around deliberately-aligned multi-line output (log statements, SQL DDL, ASCII tables) — `/prep` does NOT auto-add or auto-remove these; they're a developer signal.
- Modifier order follows JLS conventional order; checkstyle enforces this independently.
- Tests use JUnit Jupiter 6+; parallel execution conventions follow each project's surefire config.
- Mock-frameworks: prefer real implementations (test fixtures, in-memory databases) over mocks unless the FAQ documents a specific reason mocks are correct here.

---

## Python Checks

The standards-repo itself is primarily Python (the formatter at `tooling/scripts/format_java.py` and its test suite). Adopter projects may also carry a small Python ancillary tree. Run these in order.

| #   | Check               | Command                                    | Notes                                                                         |
| --- | ------------------- | ------------------------------------------ | ----------------------------------------------------------------------------- |
| 1   | Format              | `ruff format --check tooling/scripts/`     | Only if `pyproject.toml` configures ruff or black; otherwise skip with a note |
| 2   | Lint                | `ruff check tooling/scripts/`              | Only if configured                                                            |
| 3   | Type Check          | `mypy tooling/scripts/`                    | Only if `mypy` config exists                                                  |
| 4   | Tests               | `pytest tests/ -q` from `tooling/scripts/` | All passing; report total count                                               |
| 5   | Coverage (`--full`) | `pytest --cov=tooling/scripts tests/`      | If `pytest-cov` is installed                                                  |
| 6   | Security (`--full`) | `pip-audit` or `safety check`              | Only if a lock file exists                                                    |

**This standards-repo's Python conventions:**

- Type hints used freely (`Final[...]`, `Callable[..., ...]`, `Node | None`, etc.) but no enforcing `mypy` strict-mode gate today. If you add one, document it in the FAQ.
- Test layout: `tooling/scripts/tests/` with `conftest.py` putting the parent directory on `sys.path`. Fixtures live under `tooling/scripts/tests/fixtures/<category>/<case>/{input,expected}.java` — exercised as golden tests by `tests/test_fixtures.py`.
- The formatter uses `tree-sitter-java` (pinned in `tooling/scripts/requirements.txt`); the parser is wrapped in `threading.local` so concurrent callers don't trip over each other.
- New fixture cases MUST include both `input.java` and `expected.java`; missing one causes `_collect_fixture_cases` to silently skip the case.

### Python Patterns Required

- Use `from __future__ import annotations` at the top of every module (already standard here).
- Prefer `pathlib.Path` over `os.path`.
- Use type hints on new functions; existing untyped code can stay until touched.
- No bare `except` clauses — catch a specific exception class.

---

## When to use `--full` mode

Default fast mode is right for **routine commits**. Use `--full` only when:

- Cutting a release tag (full audit makes sense).
- Bumping major dependencies (`pom.xml` / `requirements.txt` churn — re-run supply-chain checks).
- After a long-lived branch reintegrates (validate the whole tree, not just the diff).
- Investigating a flaky test (run examples, doc build, full pytest with verbose).

Otherwise, fast mode is enough. The full check would take 10–30 min and re-validate code that hasn't changed.

## Wall-time budgets per mode

The agent should NOT spend more than these on any single run. Exceed → kill the offending check and report it as a timeout failure (treat as a ❌ that requires user attention, do NOT just skip):

| Mode           | Universal | Per-language fmt+lint | Tests                 | Total target |
| -------------- | --------- | --------------------- | --------------------- | ------------ |
| fast (default) | <30s      | <90s each in parallel | <15min each, parallel | **2–5 min**  |
| full           | <60s      | <3min each            | <20min each           | <30min       |

Concretely for **this standards-repo** (Python tooling + Markdown docs):

- Fast mode wall: pytest runs the 580-ish formatter tests in ~2s and the perf gate adds ~1s. Universal checks (cspell, prettier, git status) add <30s. Total: typically <1 min.
- Full mode wall: add ~30s for cspell over the whole tree + ~1 min for any in-flight `npm audit` if package-lock.json is in scope. Total: typically <2 min.

For **adopter projects** (Java + this submodule's Python tooling):

- Fast mode wall: `mvn test` is usually 30s–5 min depending on project size and JDBC/test setup. `mvn -Pcheckstyle validate` is ~10–30s. Format check via `format_file.py` over the whole tree is <5s for typical sizes. With parallelism, total ~3–8 min.
- Full mode wall: add `mvn package` (~30s–2min) and `mvn javadoc:javadoc` (~30s–2min). Total: typically 5–15 min.

## Output Format

### Success (Java + Maven)

```
☕ Java project detected (Maven)

✅ stale files
✅ markdown
✅ FAQ MCP review
✅ status + next-steps handoff
✅ changelog
✅ supply-chain pinning
✅ GitHub Actions pinning
✅ cooldown config
✅ formatter (0 modified)
✅ checkstyle (BUILD SUCCESS)
✅ compile
✅ spotbugs (skipped — no Java changes)
✅ tests (520 passed)
✅ coverage
✅ doc review

Ready for commit!
```

### Success (Python — this standards-repo)

```
🐍 Python project detected (pytest)

✅ stale files
✅ markdown
✅ FAQ MCP review
✅ status + next-steps handoff
✅ changelog
✅ supply-chain pinning
✅ GitHub Actions pinning
✅ cooldown config
✅ pytest (579 passed)
✅ cspell
✅ doc review

Ready for commit!
```

### Success (Multi-language: Java + Python — typical adopter on this submodule)

```
☕ Java project detected (Maven)
🐍 Python project detected (pytest — submodule tooling)

--- Universal Checks ---
✅ stale files
✅ markdown
✅ FAQ MCP review
✅ status + next-steps handoff
✅ changelog
✅ supply-chain pinning
✅ GitHub Actions pinning
✅ cooldown config

--- Java Checks ---
✅ formatter (0 modified)
✅ checkstyle (BUILD SUCCESS)
✅ compile
✅ tests (340 passed)
✅ coverage
✅ doc review

--- Python Checks ---
✅ pytest (579 passed)

Ready for commit!
```

### Failure

```
✅ stale files
✅ markdown
✅ formatter (0 modified)
❌ checkstyle - LineLength violation in src/main/java/com/foo/Bar.java:42 (found 84)

Fix required before commit.
```

### Stale Files Warning

```
⚠️ stale files - Found:
   - PLAN.md
   - commit_message.txt
   Remove from staging? [y/n]
```

---

## Critical Rules

| Rule                                                                                                     | Applies To      |
| -------------------------------------------------------------------------------------------------------- | --------------- |
| 100% test pass rate                                                                                      | All             |
| Zero checkstyle / lint warnings                                                                          | All             |
| Update CHANGELOG.md                                                                                      | All             |
| Update FAQ MCP for non-obvious learnings                                                                 | All             |
| Update STATUS + NEXT_STEPS for /clear handoff                                                            | All             |
| **Final line MUST be a `HANDOFF VERDICT: SAFE TO /clear` or `NOT SAFE TO /clear` line** — see §4.1       | All             |
| FAQ MCP entries written directly (NOT "surfaced for user decision") when non-obvious learning identified | All             |
| MEMORY.md /clear handoff block written/updated, linked from MEMORY.md index                              | All             |
| All deps pinned (Maven `<version>` exact; Python `==` or compatible-release; GH Actions `@sha # vN`)     | All             |
| `.github/dependabot.yml` enforces `cooldown.default-days >= 21` for every ecosystem                      | All             |
| Run independent checks in PARALLEL, not sequentially                                                     | All             |
| ALL language fmt/lint/compile/test ALWAYS run — no LLM judgment about what's "relevant to the diff"      | All             |
| Fast-mode omissions are HARDCODED (doc/package/redundant-build) — not diff-dependent                     | All (fast mode) |
| Cap each check with a timeout; kill + report on overrun                                                  | All             |
| Never push to GitHub without approval                                                                    | All             |
| "Pre-existing failure" is NEVER valid                                                                    | All             |
| Environment failures are NOT acceptable                                                                  | All             |
| Cannot proceed without EXPLICIT approval                                                                 | All             |

### Test Failure Policy

- **"Pre-existing" is not an excuse.** If a test fails during your session, it must be fixed before committing. If you cannot fix it, investigate and document the root cause. Do NOT dismiss failures as pre-existing.
- **Environment failures are not acceptable.** If tests fail because the environment is not set up or not available, that is a blocking issue. Do NOT skip tests or mark them as passing when the environment prevented them from running.
- **Neither can be cause to move forward without EXPLICIT approval.** If tests fail for any reason, you MUST stop and get explicit user approval before proceeding. Do not assume the user wants to continue past failures.

---

## Appendix: Senzing Environment Variables

For adopter projects that call the Senzing engine via JNI (most `senzing-*-java` consumers do):

```bash
# Homebrew Senzing installation (macOS)
export DYLD_LIBRARY_PATH=/opt/homebrew/opt/senzing/runtime/er/lib
export SENZING_CONFIGPATH=/opt/homebrew/opt/senzing/runtime/er/etc
export SENZING_RESOURCEPATH=/opt/homebrew/opt/senzing/runtime/er/resources
export SENZING_SUPPORTPATH=/opt/homebrew/opt/senzing/runtime/data
export SENZING_TEMPLATE_DB=/opt/homebrew/opt/senzing/runtime/er/resources/templates/G2C.db
```

If `mvn test` fails on Senzing JNI engine init (typical symptom: `UnsatisfiedLinkError` or "could not find G2.dll/libG2.dylib"), the env-vars above are likely missing or wrong. Set them in the shell that runs `/prep`, or in `~/.zshenv` / `~/.bash_profile` for persistent setup.

The standards-repo itself does NOT need these — it's a pure Python + Markdown project with no Senzing-engine touchpoints.
