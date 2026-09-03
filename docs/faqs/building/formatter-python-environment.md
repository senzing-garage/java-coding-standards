# Formatter Python Environment and Grammar Pins

## Overview

`format_java.py` is calibrated against an exact `tree-sitter` +
`tree-sitter-java` pair. The emitter dispatches on grammar node
names and depends on the specific node-name set the pinned
grammar produces, so running the formatter or its test suite
against a different binding validates behavior the formatter was
never calibrated for.

The pins live in exactly two places and must agree:

- `tooling/scripts/requirements.txt` — the pip pins (`==`).
- `GRAMMAR_VERSION` in `tooling/scripts/format_java.py` — the
  same versions as in-source constants, used for runtime
  diagnostics.

## Always run the suite from a pinned environment

A system interpreter almost never has the pinned versions. Create
a virtualenv and install from the requirements file:

```bash
python3 -m venv /path/to/virtualenv
/path/to/virtualenv/bin/python -m pip install \
    -r tooling/scripts/requirements.txt
/path/to/virtualenv/bin/python -m pytest tooling/scripts/tests -q
```

Invoke that interpreter explicitly for every run. A bare
`python3 -m pytest` picks up whatever `tree-sitter` happens to be
installed globally.

## The three-way pin check

`TestGrammarVersionPins` enforces the pins from three directions:

1. `test_grammar_version_dict_keys` — `GRAMMAR_VERSION` names
   exactly the two expected packages.
2. `test_grammar_version_values_match_requirements` — the
   in-source constants match `requirements.txt`.
3. `test_installed_versions_match_pins` — the **installed**
   packages match the pins.

Checks 1 and 2 compare two files to each other and never consult
the environment. That is the gap check 3 closes: without it, a
stale virtualenv validates the entire suite against an
uncalibrated binding. This is not hypothetical — a release review
once ran a fully green suite with `tree-sitter` 0.25.2 installed
against a 0.26.0 pin, and the mismatch was invisible.

## Reading the failure

A failure in `test_installed_versions_match_pins` means **the
environment is wrong, not the code**. Fix it with:

```bash
pip install -r tooling/scripts/requirements.txt
```

Do not "fix" it by editing `GRAMMAR_VERSION` or the requirements
pin to match whatever is installed — that silently recalibrates
the formatter's contract to a grammar that was never validated.

Conversely, a failure in
`test_grammar_version_values_match_requirements` means the two
files drifted, which is a code change.

## Bumping a pin

Dependabot can only edit `requirements.txt`, so its bump PRs
always arrive red on check 2. Resolving one is a three-step
change in a single commit:

1. Bump the version in `requirements.txt` (Dependabot did this).
2. Bump the matching entry in `GRAMMAR_VERSION`.
3. Re-install the environment and re-run the full suite.

A `tree-sitter-java` bump additionally requires a calibration
run, because the emitter assumes the node-name set of the pinned
grammar. Treat a grammar bump as a behavior change and trial it
against consumer sources before tagging — see the consumer trial
checklist.

## See also

- [Consumer trial checklist](consumer-trial-checklist.md)
- [Java formatting standards](java-formatting-standards.md)
