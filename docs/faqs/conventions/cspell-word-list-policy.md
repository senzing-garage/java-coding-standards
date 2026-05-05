# CSpell Word List Policy

The `.vscode/cspell.json` `words` array is **not** an "unknown-word silencer" — adding a made-up word there to make the spell checker stop complaining defeats the purpose of running cspell at all. cspell's job is to catch typos and invented jargon **before** they ship; whitelisting an invented word once normalizes it for future readers and every subsequent contributor, and the signal-to-noise of the check degrades on every evasion.

## Rule

There are two ways a word can be wrong:

- **Flagged by cspell** — clear signal, easy to spot. cspell prints `Unknown word (X)` and CI fails until you act on it.
- **Accepted by cspell but means something other than the intended sense** — silent failure, harder to spot. cspell only checks spelling, not meaning.

The rule below applies to **both** classes. Reaching for the word list is the right answer in only one narrow case (item 3); otherwise the answer is to reword or rename.

When cspell flags a word, or when you notice a word that isn't pulling its weight in the prose, **ask in order**:

1. **Is the word a real English word _with the intended meaning_?** Look it up in [Merriam-Webster](https://www.merriam-webster.com/) or [Wiktionary](https://en.wiktionary.org/). cspell verifies spelling against an English dictionary plus optional software/coding dictionaries (the project's config also loads `npm`, `software-tools`, `softwareTerms`, etc.). Some "informal coding compounds" are silently accepted by those extra dictionaries — `setup` (noun coinage; verb form is `set up`, two words), `cleanup`, `lookup`, `breakdown`, `teardown` — but their accepted-by-cspell status doesn't make them the right word for the prose. Other compounds are flagged in some contexts and accepted in others — `rollup` is flagged in `.py` source but accepted in `.md` (because the npm bundler product "Rollup" is in the markdown-context dictionaries); the dictionary's verdict is unstable and not the authority. The author's responsibility is meaning; cspell's job is the spelling-only safety net.
2. If the word is **not** a real word, or is a real word with the **wrong meaning**: **reword the prose** or **rename the symbol** so the offending term goes away. Use real words for the intended sense ("summary line", "tally", "report", "configuration step"). Rename variables / classes / methods / files to match.
3. Only **after** ruling out (1) and (2), if the flagged word is a legitimate proper noun (project name, library name, brand, protocol, or domain-of-art technical term that genuinely appears in industry usage — e.g. `argparse`, `spotbugs`, `jacoco`, `pytest`, `Allman`, `Senzing`, `Maven`, `Eclipse`), add it to the `words` array; keep the list alphabetized.

## Examples

| Word                       | cspell verdict                                                                                                           | Meaning verdict                                                                                                                                                          | Action                                                                                                                                                  |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `rollup`                   | Flagged in `.py`; accepted in `.md` only because the npm bundler "Rollup" leaks in via the markdown-context dictionaries | Means "a hand-rolled cigarette" (Merriam-Webster lists `roll-up` with a hyphen; the unhyphenated coinage is the npm product name) — wrong for our "summary line" context | **Reword.** Even on the `.md` path where cspell happens to pass it, the meaning is wrong. Whitelisting would mask the real problem (semantic mismatch). |
| `setup` (as a noun)        | Accepted (in the project's coding dictionaries)                                                                          | Verb form is `set up` (two words); noun coinage reads informally                                                                                                         | Reword to "set-up" or "configuration"; cspell silently passes it but prose clarity suffers                                                              |
| `argparse`                 | Flagged                                                                                                                  | Real Python module name                                                                                                                                                  | Add to `words` (already in the list)                                                                                                                    |
| `Senzing`                  | Flagged                                                                                                                  | Real proper noun                                                                                                                                                         | Add to `words` (already in the list)                                                                                                                    |
| `keepends`                 | Flagged                                                                                                                  | Real Python `str.splitlines()` parameter name                                                                                                                            | Add to `words` (already in the list)                                                                                                                    |
| `splitlines`               | Flagged                                                                                                                  | Real Python standard-library method name                                                                                                                                 | Add to `words` (already in the list)                                                                                                                    |
| `MyAnno`, `AlphaException` | Accepted                                                                                                                 | Synthetic placeholders                                                                                                                                                   | Don't whitelist; cspell tolerates camelCase identifiers                                                                                                 |

## Why not just whitelist everything?

Two reasons:

1. **Cumulative cost.** Each whitelisted entry erodes cspell's primary value of catching genuine misspellings — every addition is one more word that, if misspelled later, will be matched against the whitelist and slip through silently. Keeping the list short keeps the check sharp.
2. **Reader cost.** Future readers — human and LLM-driven — encounter the word and must derive the intended meaning from context. Real words for the intended sense don't have that tax.

Reword first; whitelist only as a last resort, and only for words that are unambiguously proper nouns or domain-specific terms with clear industry usage.

## Always state the justification when adding a word

A `.vscode/cspell.json` edit that adds a word **must** ship with a one-line justification — what the word is, and why **rewording the prose** and **renaming the symbol** were both ruled out. State this at the moment the edit is proposed (in a PR description, commit message, or the "I'm about to add X to cspell.json because Y" message that precedes the edit). The reviewer or user who accepts the edit needs the rationale in hand; an unjustified add forces them to either reverse-engineer why it was needed or accept on faith.

Concrete shape — for the `splitlines` addition that triggered this section, the justification is: "`splitlines` is the documented name of Python's `str.splitlines()` standard-library method ([docs](https://docs.python.org/3/library/stdtypes.html#str.splitlines)); the FAQ this commit adds references it by name when explaining the `keepends` parameter (which is already in the word list); neither rewording nor renaming applies because it's a real API identifier, not a symbol we control."

## Authority

This rule applies project-wide, including in CHANGELOG entries, code comments, identifier names, README prose, and FAQ content. The standards repo's super-linter run blocks PRs that fail cspell, so a misuse will be caught at PR time — but the policy above is meant to prevent the misuse upstream of CI.

## Quick fix recipe

When a PR review or CI fails on a cspell finding:

```bash
# See the offending word(s):
npx cspell '**/*.{md,py,java,xml}' --no-progress
# For each finding, decide: reword, rename, or whitelist.
# If reword/rename: edit the source. If whitelist: add to
# .vscode/cspell.json under "words", alphabetized.
# Re-run cspell to confirm:
npx cspell '**/*.{md,py,java,xml}' --no-progress
```
