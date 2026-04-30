# Contributing

Welcome to the project!

We encourage contribution in a manner consistent with the [Code of Conduct].
The following will guide you through the process.

There are a number of ways you can contribute:

1. [Asking questions]
1. [Requesting features]
1. [Reporting bugs]
1. [Contributing code or documentation]

## License Agreements

If your contribution modifies the git repository, the following agreements must be established.

_Note:_ License agreements are only needed for adding, modifying, and deleting artifacts kept within the repository.
In simple terms, license agreements are needed before pull requests can be accepted.
A license agreement is not needed for submitting feature request, bug reporting, or other project management.

### Individual Contributor License Agreement

In order to contribute to this repository, an
[Individual Contributor License Agreement (ICLA)]
must be completed, submitted and accepted.

### Corporate Contributor License Agreement

If the contribution to this repository is on behalf of a company, a
[Corporate Contributor License Agreement (CCLA)]
must also be completed, submitted and accepted.

### Project License Agreement

The license agreement for this repository is stated in the
[LICENSE] file.

## Questions

Please do not use the GitHub issue tracker to submit questions.

TODO: Instead, use ???

1. ??? Slack ???
1. ??? stackoverflow.com ???

## Feature Requests

All feature requests are "GitHub issues".
To request a feature, create a
[GitHub issue]
in this repository.

When creating an issue, there will be a choice to create a "Bug report" or a "Feature request".
Choose "Feature request".

## Bug Reporting

All bug reports are "GitHub issues".
Before reporting on a bug, check to see if it has [already been reported].
To report a bug, create a [GitHub issue] in this repository.

When creating an issue, there will be a choice to create a "Bug report" or a "Feature request".
Choose "Bug report".

## Contributing code or documentation

To contribute code or documentation to the repository, you must have
[License Agreements] in place.
This needs to be complete before a [Pull Request] can be accepted.

### Setting up a development environment

#### Set Environment variables

These variables may be modified, but do not need to be modified.
The variables are used throughout the installation procedure.

```console
export GIT_ACCOUNT=senzing-garage
export GIT_REPOSITORY=java-coding-standards
```

Synthesize environment variables.

```console
export GIT_ACCOUNT_DIR=~/${GIT_ACCOUNT}.git
export GIT_REPOSITORY_DIR="${GIT_ACCOUNT_DIR}/${GIT_REPOSITORY}"
export GIT_REPOSITORY_URL="git@github.com:${GIT_ACCOUNT}/${GIT_REPOSITORY}.git"
```

#### Clone repository

Get repository.

```console
mkdir --parents ${GIT_ACCOUNT_DIR}
cd  ${GIT_ACCOUNT_DIR}
git clone ${GIT_REPOSITORY_URL}
cd ${GIT_REPOSITORY_DIR}
```

### Coding conventions

TODO:

### Testing

The Python format scripts under `tooling/scripts/` (the five
`fix_*.py` scripts plus the `format_file.py` orchestrator and the
shared `_cli.py` helper) ship with a pytest suite at
`tooling/scripts/tests/`. The suite is **required** — the
`pytest.yaml` GitHub Actions workflow runs on every push and pull
request, and PRs cannot merge to `main` while it is failing.

#### Running tests locally

From the standards-repo root:

```bash
pip install -r tooling/scripts/tests/requirements.txt
pytest tooling/scripts/tests/ --verbose
```

Or via uv (no virtualenv setup needed):

```bash
uv run --with pytest pytest tooling/scripts/tests/ --verbose
```

#### Test structure

The suite combines two layers:

- **Fixture-driven integration tests** (one per `fix_*.py` script
  plus one for `format_file.py`). Each fixture is a directory
  under `tooling/scripts/tests/fixtures/<script>/` containing
  `input.java` (the source to be transformed) and `expected.java`
  (the desired output). The test parametrizes over directories,
  so adding a new test case is just dropping in a new directory —
  no Python code change.
- **Helper unit tests** in `test_helpers.py` exercise individual
  pure functions like `find_wrap_opener_indent`,
  `is_control_flow_or_special`, `_cli._excluded`, and friends.
  When a fixture-driven test fails, helper unit tests narrow the
  diagnosis to a specific function.
- **Idempotency cross-cutting test** (`test_idempotency.py`)
  verifies, for every fixture across every script, that running
  the script against `expected.java` produces no further change,
  and that running the script twice on `input.java` produces the
  same output as a single pass. This catches non-converging
  transformations and inter-script interference.

#### Adding a new fixture

1. Pick the relevant `tooling/scripts/tests/fixtures/<script>/`
   directory.
2. Create a numbered subdirectory describing the case (e.g.
   `12_wrapped_for_with_string_arg/`). The numeric prefix keeps
   test ordering stable; the descriptive name surfaces in pytest
   output.
3. Author `input.java` (the deliberately non-compliant source) and
   `expected.java` (the desired output) by hand. The
   `BASELINE_EXCLUDES` in `_cli.py` protects the entire fixtures
   tree from auto-format hooks (`runonsave`, `PostToolUse`) that
   would otherwise silently rewrite your inputs.
4. Run `pytest tooling/scripts/tests/ -v` and confirm the new
   case passes.

If the script's actual output differs from your hand-authored
`expected.java`, decide whether the script needs a fix or your
expectation was wrong, then update accordingly. The idempotency
test will catch any expected.java that isn't a fixed point.

#### When the format scripts evolve

When you change one of the `fix_*.py` scripts, the existing
fixture corpus exercises the script against ~50 real cases. Two
likely scenarios:

- **Tightening a rule**: existing fixtures stay valid; add new
  fixtures for the cases the tightened rule handles.
- **Refactoring without behavior change**: the test suite must
  continue to pass with no fixture updates. If it doesn't, either
  the refactor changed behavior or a fixture was overly tied to
  implementation details.

For helper-function-level changes, prefer adding a new test case
in `test_helpers.py` over a new fixture — fixture tests are
slower and harder to diagnose at function granularity.

### Pull Requests

Code in the main branch is modified via GitHub pull request.
Follow GitHub's [Creating a pull request from a branch] or
[Creating a pull request from a fork] instructions.

Accepting pull requests will be at the discretion of Senzing, Inc. and the repository owner(s).

[already been reported]: https://github.com/search?q=+is%3Aissue+user%3Asenzing
[Asking questions]: #questions
[Code of Conduct]: CODE_OF_CONDUCT.md
[Contributing code or documentation]: #contributing-code-or-documentation
[Corporate Contributor License Agreement (CCLA)]: .github/senzing-corporate-contributor-license-agreement.pdf
[Creating a pull request from a branch]: https://help.github.com/articles/creating-a-pull-request/
[Creating a pull request from a fork]: https://help.github.com/articles/creating-a-pull-request-from-a-fork/
[GitHub issue]: https://help.github.com/articles/creating-an-issue/
[Individual Contributor License Agreement (ICLA)]: .github/senzing-individual-contributor-license-agreement.pdf
[LICENSE]: LICENSE
[License Agreements]: #license-agreements
[Pull Request]: #pull-requests
[Reporting bugs]: #bug-reporting
[Requesting features]: #feature-requests
