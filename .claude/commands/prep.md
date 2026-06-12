# Prepare for Commit

**TWO MODES:**
- **DEFAULT (fast)**: same correctness checks as `--full`, but parallelized and with hardcoded omissions (doc-build, examples, assembly, redundant builds). NO LLM JUDGMENT about what's relevant — the only "skips" are mechanical (hardcoded fast-mode-omits) or trivially testable (`cargo deny`/`audit` skip iff `git diff` shows no Cargo.toml/Cargo.lock changes — one-line shell test, not a decision the agent makes).
- **`--full` (thorough)**: adds doc build, examples, dep audit unconditionally, assembly. Use before a release tag.

**Both modes ALWAYS run, in every project language present:** stale-files, format-check, lint, type-check, compile, test, FAQ review, status+next-steps, changelog. Speed comes from PARALLELISM and from skipping things that aren't correctness gates (doc, examples, assembly), not from skipping language tests.

**MANDATORY: You MUST launch an Opus agent (`model: "opus"`) to perform the checks. This is NOT optional. The agent provides independent verification. If you skip the agent or run checks manually instead, you are violating this directive. "Nothing to commit" or "already pushed" does NOT exempt you from launching the agent — the agent validates the CURRENT STATE of the branch.**

**EXECUTION:** Pass this entire prompt as the agent's task, plus the **mode** (`fast` or `full`). The agent must:
1. Detect ALL languages present in the project (Cargo.toml → Rust; build.sbt → Scala; etc.). Run checks for **every** detected language; the agent does NOT decide which ones to skip based on diff content.
2. **Run independent checks in parallel** via the Bash tool's `run_in_background: true` and `Monitor` for completion. Sequential is the wrong default.
3. Cap checks with timeouts (`sbt test` 15 min, `cargo test` 15 min, others 5 min) — kill and report timeout as ❌ if exceeded.
4. Report a structured ✅/❌ summary. Do NOT paste full logs; extract the FAILING line(s) only.
5. **Final line of the report MUST be a `/clear` readiness verdict.** See "/clear Handoff Verdict" section below — this is mandatory and non-negotiable. /prep is BOTH a commit-readiness gate AND a session-handoff gate; the latter is the more rigorous of the two and dominates the summary line.

**FAST-MODE OMISSIONS (hardcoded; NOT diff-dependent):**
- `cargo doc`, `sbt doc`, `typedoc` — `--full` only (these aren't correctness gates)
- `cargo run --example` — `--full` only
- `sbt assembly` — `--full` only (build the fat JAR for release prep, not commits)
- `cargo build --all-targets` — SKIP unconditionally because `cargo test` already builds everything
- `markdown-table-formatter` + `prettier --write` over the whole tree — SKIP unconditionally; rewriting hand-tuned plan files mid-prep is a foot-gun. Use `prettier --check` (no write) on the whole `.md` tree instead.

**SHELL-GATED (mechanical; deterministic test, no LLM judgment):**
- `cargo deny check` — run iff `git diff --name-only origin/main...HEAD -- '**/Cargo.toml' '**/Cargo.lock' | grep .` is non-empty. Otherwise skip with note "no dep changes." Same gate for `cargo audit`.
- `npm audit` — run iff `git diff --name-only origin/main...HEAD -- '**/package.json' '**/package-lock.json' | grep .` is non-empty.

**ALWAYS RUN (no skip ever, both modes):**
- All language formatters (`cargo fmt --check`, `sbt scalafmtCheckAll`, `prettier --check`, `clang-format --dry-run`).
- All language linters (`cargo clippy --all-targets -- -D warnings`, etc.).
- All language compilers/type-checkers (`sbt compile`, `tsc --noEmit`, etc.).
- All language test suites (`cargo test`, `sbt test`, `npm test`, `ctest`).
- Universal: stale-files, FAQ review, status+next-steps, CHANGELOG, GitHub Actions pin check.

**MANDATORY PARALLELISM:**
The agent must fan out independent checks concurrently:
```
parallel group A (Rust):     cargo fmt --check  &  cargo clippy --all-targets -- -D warnings
parallel group B (Scala):    sbt scalafmtCheckAll  &  sbt compile
parallel group C (universal): git status --porcelain  &  prettier --check '**/*.md'
parallel group D (tests):    cargo test  &  sbt test
```
Group D dominates wall time; A, B, C should complete while tests run. Sequential execution of independent checks is a bug.

## Quick Reference

| Check | Rust | C++ | Scala (Gradle) | Scala (sbt) | TypeScript |
|-------|------|-----|----------------|-------------|------------|
| Stale files | `git status` | `git status` | `git status` | `git status` | `git status` |
| Markdown | `markdown-table-formatter` + `prettier` | `markdown-table-formatter` + `prettier` | `markdown-table-formatter` + `prettier` | `markdown-table-formatter` + `prettier` | `markdown-table-formatter` + `prettier` |
| Format | `cargo fmt` | `clang-format` | `./gradlew scalafmtAll` | `sbt scalafmtAll` | `prettier --check` |
| Lint | `cargo clippy` | `cppcheck` | (scalafmt) | (scalafmt) | `eslint` |
| Type Check | - | - | - | - | `tsc --noEmit` |
| Build | `cargo build` | `cmake --build` | `./gradlew build -x test` | `sbt compile` | `npm run build` |
| Assembly | - | - | - | `sbt assembly` | - |
| Licenses | `cargo deny` | manual check | manual check | manual check | `license-checker` |
| Security | `cargo audit` | - | - | - | `npm audit` |
| Memory | - | AddressSanitizer | - | - | - |
| Tests | `cargo test` | `ctest` | `./gradlew test` | `sbt test` | `npm test` |
| Examples | `cargo run --example` | run binaries | - | - | run scripts |
| Docs | `cargo doc` | `doxygen` | `./gradlew scaladoc` | `sbt doc` | `typedoc` |
| Changelog | CHANGELOG.md | CHANGELOG.md | CHANGELOG.md | CHANGELOG.md | CHANGELOG.md |

**Note:** Projects may use multiple languages (e.g., Rust + TypeScript for Electron apps). Run checks for ALL detected languages.

---

## Project Detection

- **Rust**: `Cargo.toml` in current directory
- **TypeScript**: tsconfig.json in current directory or subdirectory
- **Scala**: `build.gradle` with Scala plugin or `build.sbt` in current directory
- **C++**: `CMakeLists.txt` in current directory or build directory
- If none found, ask user

**Multi-language projects:** Many projects combine languages (e.g., Rust + TypeScript for Electron/Tauri apps, C++ + TypeScript for native bindings). Detect ALL languages and run checks for each section that applies.

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
- Files in `tmp/`, `temp/`, `.tmp/`

**Debug/Scratch Code:**
- `debug_*.rs`, `test_scratch*.rs`
- `debug_*.cpp`, `test_scratch*.cpp`
- `debug_*.scala`, `test_scratch*.scala`
- `debug_*.ts`, `test_scratch*.ts`, `debug_*.tsx`, `test_scratch*.tsx`

If flagged files are staged, prompt user to remove them.

### 2. Markdown Formatting

Format all markdown files:

```bash
# Fix table alignment (MD060) - handles emoji/Unicode width correctly
npx markdown-table-formatter "**/*.md"

# Format with prettier
npx prettier --write "**/*.md" --ignore-path .prettierignore
```

If prettier is not installed globally, use `brew install prettier` (macOS) or `npm install -g prettier`.

Verify with:
```bash
npx prettier --check "**/*.md" --ignore-path .prettierignore
npx markdownlint-cli "**/*.md" --ignore node_modules --ignore external
```

### 3. FAQ MCP Update

If the project has a FAQ MCP server (check for `.claude/faqs/` directory in the repo root OR in any `.claude/` directory), review whether any FAQ entries need updating based on changes in this session. This is MANDATORY — do NOT skip.

**Detection:** Look for `.claude/faqs/` directories. If found, the project has FAQ infrastructure.

**Review process:**
1. Use `search_faqs(query)` to find FAQs potentially affected by this session's changes
2. Read the affected FAQ markdown files directly from `.claude/faqs/`
3. Update or create FAQ entries for:
   - **New patterns or conventions** discovered during the session
   - **Build/test/CI knowledge** gained (e.g., CI check behavior, suppression mechanisms, new build flags)
   - **Corrections to existing FAQs** found during work — fix inaccuracies
   - **New tooling or commands** introduced
   - **Architecture decisions** made that affect how others should work with the code
   - **Performance findings** (profiling results, optimization patterns, what worked/didn't)
4. Write changes directly to the FAQ markdown files in `.claude/faqs/`
5. Stage FAQ changes alongside code changes

FAQs are the project's institutional memory. If you learned something non-obvious during this session that would help the next developer (or the next Claude session), it belongs in a FAQ.

### 4. Status + Next-Steps Handoff (MANDATORY)

After /prep completes, the user may `/clear` and resume in a fresh session. The next session needs enough context to pick up cleanly without re-deriving everything from git log + memory. **This is NOT optional.**

**What to capture:**

1. **Current status** — what is the state of in-flight work right now? In particular:
   - Any background processes still running (cluster jobs, monitors, daemons) with PIDs / log paths
   - What's pending on the critical path (e.g., "TG302 v4.1b retry running, ETA 9h, monitor task ID `bsur0k0ns`")
   - What was just landed in git (commit hashes + one-line summaries)
   - Open questions awaiting cluster results / external systems
   - Any uncommitted-but-deliberate working-tree state (with rationale)

2. **Next steps** — what should the next session do, in priority order? Be specific:
   - "When TG302 retry completes, validate group count vs Senzing-loader baseline" not "validate"
   - Include exact commands / file paths / config keys / commit hashes
   - Surface the decision points (e.g., "if group count drift > 0.1%, escalate to ___")

3. **Anything the next session would not be able to recover from git + memory alone**:
   - Mental model of the current investigation (e.g., "we proved boruvka algo works at K=4.3M but eventLog listener was the bottleneck")
   - Why current choices were made over alternatives (rejected paths matter)
   - Known fragility: "do NOT relaunch the chain without verifying X first"

**Where to write it:**

- **Project-level**: write to `.claude/STATUS.md` and `.claude/NEXT_STEPS.md` (or update if they exist) in the project repo. These are gitignored or committed depending on project convention.
- **Cross-session memory**: also update auto-memory `MEMORY.md` with a `/clear handoff` block summarizing the same — this survives /clear in the user's home directory and is what a fresh session sees first. Keep MEMORY.md `/clear handoff` entries terse (≤150 lines per entry).
- **Project memory file**: if the project has a `project_session_YYYYMMDD.md` pattern in memory (check `MEMORY.md` index), follow it.

**Quality bar:** if the next session reads only `MEMORY.md` + `STATUS.md` + `NEXT_STEPS.md` + recent git log, can they recover and continue? If no, the handoff is incomplete.

**Special-case check before /clear:** are any background tasks (Monitor, Bash run_in_background, cron, nohup processes) still running that the next session needs to know about? List them explicitly with task ID / PID / what they're watching / when they're expected to fire next.

### 4.1 /clear Handoff Verdict (MANDATORY — final line of /prep output)

The /prep agent MUST end its summary with one of two explicit verdicts. This is non-negotiable. The user will use this line to decide whether to `/clear` and resume in a fresh session.

**The verdict is BINARY: SAFE TO /clear, or NOT SAFE.** No middle ground, no qualifications buried in prose. If any handoff item is missing or stale, the verdict is NOT SAFE and the agent must say *what is missing*.

**The verdict is computed from this checklist** — every box must be checked for SAFE TO /clear:

- [ ] **STATUS.md** exists and reflects current branch HEAD + in-flight CI cycle state + container/cron/background-task inventory
- [ ] **NEXT_STEPS.md** exists with priority-ordered actionable items, including exact commands/paths/SHAs (no "validate the thing" — must be "run X against Y, expect Z")
- [ ] **FAQ MCP entries** updated for any non-obvious learning this session (architecture decisions, build/test/CI knowledge, corrections to existing FAQs, new tooling). FAQs MUST be written directly to `.claude/faqs/<category>/<title>.md` — surfacing-for-user-decision is NOT acceptable; if the agent identifies a FAQ-worthy learning, the agent writes the FAQ entry.
- [ ] **MEMORY.md /clear handoff block** written/updated. The block must be linked from `MEMORY.md` index and contain everything that would NOT be recoverable from `git log + STATUS.md + NEXT_STEPS.md + git working-tree state` alone (mental model, rejected paths, fragility warnings, container creds, cron/Monitor IDs).
- [ ] **All session commits pushed** OR explicitly listed as "deliberately held local" with reason in the handoff
- [ ] **/prep gates green** (or every ❌ explicitly explained as "deliberately deferred" with reason)
- [ ] **Background tasks documented**: cron jobs (with IDs and what they fire), local docker containers (with names + ports + creds if synthetic), background `Monitor` / `run_in_background` tasks (with task IDs)
- [ ] **Working-tree state**: clean OR every dirty/untracked path is explicitly accounted for as "pre-existing this session" OR "deliberate WIP, see <handoff section>"

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

**The agent does NOT dismiss handoff items as out-of-scope.** "Already pushed, nothing to commit" does NOT exempt /prep from the handoff checklist — handoff is about session-state continuity, not commit-state. Even on a no-op session where nothing changed, /prep must verify the existing STATUS/NEXT_STEPS/MEMORY are still accurate (or update them) before declaring SAFE TO /clear.

**The agent does NOT fabricate "SAFE TO /clear" by surfacing missing items as "for user decision".** Surfacing-as-note means "I found a thing that should happen, you decide" — that is BLOCKING for the verdict, not a punt. If the agent identifies a FAQ-worthy learning, the agent writes the FAQ entry; if it identifies a stale STATUS section, the agent updates STATUS; etc. The verdict is SAFE only when nothing is left in the "user decides" bucket.

**Why this section exists:** in practice, /prep agents have closed sessions saying "Ready for commit ✅" while leaving FAQ updates "for user decision", forgetting MEMORY.md, and writing STATUS without NEXT_STEPS. That makes the next session start half-blind. The handoff verdict forces the agent to be explicit about whether the *next* session can pick up cleanly, not just whether the *current* commit is shippable.

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

**If CHANGELOG.md exists:** Add entries under `## [Unreleased]` for all changes in the current session.

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

Every dependency that the toolchain will fetch from a network MUST be hash-pinned so the next build resolves to **byte-identical** content. An unpinned `branch = "main"` git dep, missing lock file, or floating version range is a supply-chain attack surface — a malicious push to upstream silently rolls into the next `cargo build` / `npm install` / `sbt update`.

**Mechanical (no LLM judgment), fail-on-violation:**

**Rust** — run when `Cargo.toml` exists:
```bash
# (a) git deps must use rev = "<sha>". branch = / tag = / no-rev are violations.
grep -nE '^\s*[a-zA-Z_-]+\s*=\s*\{.*\bgit\s*=' Cargo.toml | grep -v '\brev\s*=' && echo "VIOLATION: unpinned git dep"
# (b) Cargo.lock must be committed (NOT in any .gitignore).
[ -f Cargo.lock ] || echo "VIOLATION: Cargo.lock missing"
git ls-files Cargo.lock | grep -q Cargo.lock || echo "VIOLATION: Cargo.lock not tracked"
git check-ignore Cargo.lock 2>/dev/null && echo "VIOLATION: Cargo.lock is gitignored"
# (c) optional but recommended: cargo deny's `bans` section to forbid yanked crates;
#     `cargo audit` already runs in fast mode when Cargo.lock changes.
```

**npm/TypeScript** — run when `package.json` exists:
```bash
# (a) package-lock.json (or yarn.lock / pnpm-lock.yaml) MUST be committed. The lock
#     file's `integrity: sha512-...` field per dep is what makes installs hash-verified.
[ -f package-lock.json -o -f yarn.lock -o -f pnpm-lock.yaml ] || echo "VIOLATION: no lock file"
git ls-files package-lock.json yarn.lock pnpm-lock.yaml 2>/dev/null | grep -qE 'lock' || \
  echo "VIOLATION: lock file present but not tracked"
git check-ignore package-lock.json 2>/dev/null && echo "VIOLATION: lock file gitignored"
# (b) installs MUST be `npm ci` (uses lock exactly), never `npm install` in CI/build
#     scripts. Audit any build/Makefile/script for `npm install` and recommend `npm ci`.
```

**Scala/sbt**:
sbt+Maven Central does not support hash-pinning natively — there's no equivalent of Cargo.lock that's standard practice. Closest gate available:
- All `libraryDependencies` MUST pin a specific version (no `latest.release`, no `+`, no `[1.0,2.0)` ranges).
- Verify with: `grep -nE 'libraryDependencies.*\b(latest\.release|\+\b|\[)' build.sbt project/plugins.sbt 2>/dev/null && echo "VIOLATION: floating Scala dep version"`
- Document the limitation: Scala/Maven supply-chain hardening requires either an in-house artifact mirror with checksums or a tool like `sbt-coursier` strict mode (out of scope for this gate).

**GitHub Actions**: covered in Section 6 above.

**Output**: each violation is a ❌ that blocks commit. Fix is a deterministic mechanical change (look up the upstream commit SHA, run `npm install` to generate the lock, etc.) — NOT an LLM judgment call.

### 7.1 21-Day Dependency Cooldown (MANDATORY)

Best practice for supply-chain hardening: dependency updates must wait **≥21 days** between upstream publish and our adoption. The window gives the security community time to detect compromised releases before they reach our build (xz, nx, ua-parser-js, npm typosquats — most were detected within days but live for hours-to-weeks before takedown).

**Enforcement is declarative via Dependabot's built-in `cooldown` config.** Dependabot will not propose a dep update unless the new version meets the cooldown threshold; it filters at PR-generation time, on GitHub's servers, with no per-/prep network calls needed.

**Cooldown applies to *version* updates ONLY.** Per GitHub's spec ([dependabot cooldown docs](https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuration-options-for-the-dependabot.yml-file#cooldown--)): "the `cooldown` option is only available for *version* updates, not *security* updates". A Dependabot security advisory PR (GHSA / RUSTSEC ingestion) bypasses cooldown entirely, so HIGH/CRITICAL CVEs land within hours regardless of the cooldown window. Cooldown is the routine-bump safety net, not the security gate. This is *why* the declarative dependabot config is sufficient — security is handled out-of-band by GHSA, the 21-day cooldown is just for routine version churn.

**Asymmetry for git submodules.** GHSA only links advisories to *published packages* (cargo crate, npm package, image digest). A raw `gitsubmodule` ecosystem entry HAS cooldown but cannot benefit from the security-bypass — there's no package identity for GHSA to match. For pure-git submodules, cooldown is enforced in-house (see `.github/workflows/submodule-updates.yml` if the project has one) and the only way to bypass for a security fix is the explicit `Cooldown-Override:` commit-footer mechanism described below or the workflow's `allow_fresh_deps` / `cooldown_override_submodules` dispatch inputs. If a submodule is ALSO a published package (e.g., a Rust crate vendored as both a Cargo.toml dep and a submodule), the security flow goes through the cargo ecosystem's GHSA path normally — the submodule cooldown doesn't matter for that case.

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
  - package-ecosystem: cargo
    directory: /
    schedule: { interval: weekly }
    cooldown: { default-days: 21 }
  - package-ecosystem: npm
    directory: /
    schedule: { interval: weekly }
    cooldown: { default-days: 21 }
  - package-ecosystem: github-actions
    directory: /
    schedule: { interval: weekly }
    cooldown: { default-days: 21 }
  - package-ecosystem: maven    # if applicable (sbt+Maven)
    directory: /
    schedule: { interval: weekly }
    cooldown: { default-days: 21 }
```

**Manual dep bumps** (developer hand-edits Cargo.toml / package.json directly, bypassing Dependabot): the cooldown intent still applies, but enforcement falls to discipline and code review. Don't hand-bump to a release < 21 days old without a documented `Cooldown-Override:` reason in the commit message; reviewers reject otherwise. /prep can grep the commit message for that override-or-explain pattern when a Cargo.toml/package.json/workflow yml shows a hand-edited version bump:

```bash
# If the diff shows a manual version bump in dep manifests, require the commit message
# to either claim cooldown-clean ("Dependency bumped is ≥21 days old") OR document an
# explicit override ("Cooldown-Override: <pkg>@<ver> — <CVE/rationale>").
# This is a guardrail, not a hard block — manual bumps are usually intentional.
```

**Why this is simpler than what was here before**: an earlier draft of this section had a curl+jq pipeline querying crates.io / registry.npmjs.org / api.github.com per dep on every /prep run. That was overengineered: Dependabot's server-side cooldown filter does the same job declaratively, doesn't fail on network-restricted dev boxes, and doesn't add per-commit network latency. Revoked — Dependabot config is the canonical enforcement.

---

## Rust Checks

Run these in order. Stop on first failure.

| # | Check | Command | Notes |
|---|-------|---------|-------|
| 1 | Format | `cargo fmt -- --check` | Auto-fix with `cargo fmt` |
| 2 | Clippy | `cargo clippy --all-targets --all-features -- -D warnings` | Zero warnings required |
| 3 | Build | `cargo build --all-targets` | Include tests/examples |
| 4 | Deny | `cargo deny check` | License validation |
| 5 | Audit | `cargo audit` | Security vulnerabilities |
| 6 | Tests | `cargo test` | 100% pass rate |
| 7 | Coverage | Check modified files have tests | New public functions need tests |
| 8 | Doc Review | Check README.md, CLAUDE.md | Update if API/features changed |
| 9 | Examples | `cargo run --example <name>` | All must pass |
| 10 | Docs | `cargo doc --no-deps` | Must build without warnings |

### Allowed Licenses
Apache-2.0, MIT, BSD, Unicode-3.0, Zlib only. **NO GPL/LGPL.**

---

## Scala Checks

Run these in order. Stop on first failure.

### Scala with Gradle

| # | Check | Command | Notes |
|---|-------|---------|-------|
| 1 | Format | `./gradlew checkScalafmtAll` | Auto-fix with `./gradlew scalafmtAll` |
| 2 | Build | `./gradlew build -x test` | Compile all modules |
| 3 | Tests | `./gradlew test` | 100% pass rate |
| 4 | Coverage | Check modified files have tests | New public functions need tests |
| 5 | Doc Review | Check README.md, CLAUDE.md | Update if API/features changed |

### Scala with sbt

| # | Check | Command | Notes |
|---|-------|---------|-------|
| 1 | Format | `sbt scalafmtCheckAll` | Auto-fix with `sbt scalafmtAll` |
| 2 | Compile | `sbt compile` | Must compile with zero errors |
| 3 | Assembly | `sbt assembly` | For fat JAR projects (if configured) |
| 4 | Tests | `sbt test` | 100% pass rate required |
| 5 | Coverage | Check modified files have tests | New public functions need tests |
| 6 | Doc Review | Check README.md, CLAUDE.md | Update if API/features changed |

**Note:** For Spark projects on Java 21+, ensure `JAVA_HOME` points to Java 11-21 (not Java 25).

### When Build/Test Not Available Locally

If builds fail due to environment issues (e.g., private repos, missing credentials):

| # | Check | Method | Notes |
|---|-------|--------|-------|
| 1 | Format | `sbt scalafmtCheckAll` or `./gradlew checkScalafmtAll` | Usually works without dependencies |
| 2 | Syntax | Review changed files for compilation errors | Check imports, types, method signatures |
| 3 | API Consistency | Verify trait/interface changes match implementations | Check method signatures align |
| 4 | Type Safety | Review Option/null handling, type parameters | Look for potential runtime errors |
| 5 | Logic Review | Trace through changed code paths | Verify behavior is correct |
| 6 | CI/CD | Push to branch and monitor GitHub Actions | Let CI handle build/test |

### Scala Build Tool Detection

- **Gradle**: Look for `build.gradle` with Scala plugin, use `./gradlew` commands
- **SBT**: Look for `build.sbt`, use `sbt` commands
- **Maven**: Look for `pom.xml` with Scala plugin, use `mvn` commands

### Scala Patterns Required
- Use `Option` instead of null checks
- Prefer immutable collections
- Use pattern matching over if/else chains
- Avoid mutable state where possible
- Use case classes for data transfer objects

### Scala Patterns Required
- Use `Option` instead of null checks
- Prefer immutable collections
- Use pattern matching over if/else chains
- Avoid mutable state where possible
- Use case classes for data transfer objects

---

## C++ Checks

Run these in order. Stop on first failure.

| # | Check | Command | Notes |
|---|-------|---------|-------|
| 1 | Format | `clang-format --dry-run --Werror` | Auto-fix with `-i` |
| 2 | Static Analysis | `cppcheck` | Zero warnings |
| 3 | Code Quality | Manual review | See C++20 patterns below |
| 4 | Build | `cmake --build . --target all` | C++20 standard required |
| 5 | License | Check CMakeLists.txt | No GPL/LGPL |
| 6 | Memory | Run with AddressSanitizer | Fix memory errors FIRST |
| 7 | Tests | `ctest --output-on-failure` | 100% pass rate |
| 8 | Examples | Run example binaries | All must pass |
| 9 | Docs | `doxygen` | If configured |

### C++20 Patterns Required
- `auto` for type simplification
- Range-based for loops
- `std::string_view` for read-only strings
- `std::format` (not `+` concatenation)
- Views and ranges where applicable
- Structured bindings
- No `cmn::ustring` - use `std::string` + `StringHelpers.h`

### C++ Resource Rules
- No heap/CPU increases without explicit permission
- Use googletest framework
- Build with libasan for memory debugging

---

## TypeScript Checks

Run these in order. Stop on first failure.

| # | Check | Command | Notes |
|---|-------|---------|-------|
| 1 | Format | `npx prettier --check .` | Auto-fix with `npx prettier --write .` |
| 2 | Lint | `npx eslint .` | Zero warnings required |
| 3 | Type Check | `npx tsc --noEmit` | Full type safety required |
| 4 | Build | `npm run build` | Must complete without errors |
| 5 | Security | `npm audit` | No high/critical vulnerabilities |
| 6 | Tests | `npm test` | 100% pass rate |
| 7 | Coverage | Check modified files have tests | New exported functions need tests |
| 8 | Doc Review | Check README.md, CLAUDE.md | Update if API/features changed |

### TypeScript Build Tools

Detect build system from package.json scripts:
- **esbuild**: Fast bundling, common for Electron apps
- **tsc**: Direct TypeScript compilation
- **webpack/vite/rollup**: Full bundlers with config files
- **tsup**: Zero-config TypeScript bundling

### TypeScript Patterns Required
- Strict mode enabled in tsconfig.json
- No "any" types without explicit justification
- Use type-only imports where possible (import type { ... })
- Prefer "interface" over "type" for object shapes
- Use "const" assertions for literal types
- Avoid non-null assertions (!) - handle nulls properly
- Use discriminated unions over type guards where applicable

### Electron/Native Projects

For TypeScript projects with native components (Electron, Tauri, NAPI-RS):
- Run TypeScript checks for renderer/main processes
- Also run native language checks (Rust, C++) for native code
- Verify type definitions match native bindings
- Test IPC/FFI boundaries

---

## When to use `--full` mode

Default fast mode is right for **routine commits**. Use `--full` only when:

- Cutting a release tag (full audit makes sense)
- Bumping major dependencies (`Cargo.lock` / `package.json` churn — re-run `cargo deny` + `cargo audit`)
- After a long-lived branch reintegrates (validate the whole tree, not just the diff)
- Investigating a flaky test (run examples, doc build, full clippy with all features)

Otherwise, fast mode is enough. The full check would take 10–30 min and re-validate code that hasn't changed.

## Wall-time budgets per mode

The agent should NOT spend more than these on any single run. Exceed → kill the offending check and report it as a timeout failure (treat as a ❌ that requires user attention, do NOT just skip):

| Mode | Universal | Per-language fmt+lint | Tests | Total target |
|---|---|---|---|---|
| fast (default) | <30s | <90s each in parallel | <15min each, parallel | **2–5 min** |
| full | <60s | <3min each | <20min each | <30min |

Concretely for THIS repo (Rust + Scala on the spark_er project):
- fast mode wall: roughly `max(cargo test wall, sbt test wall)` + ~30s overhead. Both are gated by Senzing JNI engine init (~30s warmup). With parallelism, ~8–12 min if tests are required; <2 min if no source touches.
- full mode wall: add 3–5 min for `cargo deny` + `cargo audit` + `cargo doc`.

## Output Format

### Success (Rust)
```
🦀 Rust project detected

✅ stale files
✅ markdown
✅ FAQ MCP review
✅ status + next-steps handoff
✅ changelog
✅ supply-chain pinning
✅ fmt
✅ clippy
✅ build
✅ deny
✅ audit
✅ tests (60 passed)
✅ coverage
✅ doc review
✅ examples
✅ docs

Ready for commit!
```

### Success (Scala)
```
🔷 Scala project detected (Gradle)

✅ stale files
✅ markdown
✅ FAQ MCP review
✅ status + next-steps handoff
✅ changelog
✅ supply-chain pinning
✅ scalafmt
✅ build
✅ tests (120 passed)
✅ coverage
✅ doc review

Ready for commit!
```

### Success (TypeScript)
```
🟦 TypeScript project detected (esbuild)

✅ stale files
✅ markdown
✅ FAQ MCP review
✅ status + next-steps handoff
✅ changelog
✅ supply-chain pinning
✅ prettier
✅ eslint
✅ tsc --noEmit
✅ build
✅ npm audit
✅ tests (45 passed)
✅ coverage
✅ doc review

Ready for commit!
```

### Success (Multi-language: Rust + TypeScript)
```
🦀 Rust project detected
🟦 TypeScript project detected (esbuild)

--- Universal Checks ---
✅ stale files
✅ markdown
✅ FAQ MCP review
✅ status + next-steps handoff
✅ changelog
✅ supply-chain pinning

--- Rust Checks ---
✅ fmt
✅ clippy
✅ build
✅ deny
✅ audit
✅ tests (60 passed)
✅ coverage
✅ doc review
✅ examples
✅ docs

--- TypeScript Checks ---
✅ prettier
✅ eslint
✅ tsc --noEmit
✅ build
✅ npm audit
✅ tests (25 passed)
✅ coverage
✅ doc review

Ready for commit!
```

### Failure
```
✅ stale files
✅ markdown
✅ fmt
❌ clippy - [error details]

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

| Rule | Applies To |
|------|------------|
| 100% test pass rate | All |
| Zero clippy/lint warnings | All |
| Fix memory errors FIRST | All (blocking) |
| No GPL/LGPL licenses | All |
| Update CHANGELOG.md | All |
| Update FAQ MCP for non-obvious learnings | All |
| Update STATUS + NEXT_STEPS for /clear handoff | All |
| **Final line MUST be a `HANDOFF VERDICT: SAFE TO /clear` or `NOT SAFE TO /clear` line** — see §4.1 | All |
| FAQ MCP entries written directly (NOT "surfaced for user decision") when non-obvious learning identified | All |
| MEMORY.md /clear handoff block written/updated, linked from MEMORY.md index | All |
| All deps hash-pinned (Cargo.lock + git rev= / package-lock.json / GH Actions sha) | All |
| Run independent checks in PARALLEL, not sequentially | All |
| ALL language fmt/lint/compile/test ALWAYS run — no LLM judgment about what's "relevant to the diff" | All |
| Fast-mode omissions are HARDCODED (doc/examples/assembly/redundant-build) — not diff-dependent | All (fast mode) |
| `cargo deny`/`cargo audit`/`npm audit` skip is SHELL-TESTED (`git diff` over Cargo.toml/lock or package.json) — mechanical, not LLM | All (fast mode) |
| Cap each check with a timeout; kill + report on overrun | All |
| Never push to GitHub without approval | All |
| "Pre-existing failure" is NEVER valid | All |
| Environment failures are NOT acceptable | All |
| Cannot proceed without EXPLICIT approval | All |

### Test Failure Policy

- **"Pre-existing" is not an excuse.** If a test fails during your session, it must be fixed before committing. If you cannot fix it, investigate and document the root cause. Do NOT dismiss failures as pre-existing.
- **Environment failures are not acceptable.** If tests fail because the environment is not set up or not available, that is a blocking issue. Do NOT skip tests or mark them as passing when the environment prevented them from running.
- **Neither can be cause to move forward without EXPLICIT approval.** If tests fail for any reason, you MUST stop and get explicit user approval before proceeding. Do not assume the user wants to continue past failures.

---

## Appendix: Environment Variables

For Senzing projects only:

```bash
# Homebrew Senzing installation (macOS)
export DYLD_LIBRARY_PATH=/opt/homebrew/opt/senzing/runtime/er/lib
export SENZING_CONFIGPATH=/opt/homebrew/opt/senzing/runtime/er/etc
export SENZING_RESOURCEPATH=/opt/homebrew/opt/senzing/runtime/er/resources
export SENZING_SUPPORTPATH=/opt/homebrew/opt/senzing/runtime/data
export SENZING_TEMPLATE_DB=/opt/homebrew/opt/senzing/runtime/er/resources/templates/G2C.db
```
