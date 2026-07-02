# Contributing to culprit

Thanks for your interest in improving culprit! Contributions of all kinds are
welcome — bug reports, feature ideas, docs, and code.

## Ground rules

- **culprit is read-only by design.** It must never modify the target repo's
  working tree or the PR/MR. Network `git fetch` of a PR ref is allowed; anything
  that writes to the checkout is not.
- **Repo-agnostic and language-agnostic.** No hardcoded paths, repo names, hosts,
  or organization specifics in the package. The engine should work on any git repo.
- **Dependency-light.** The core engine uses only the Python standard library plus
  `git`/`gh`. Optional extras: `culprit[api]` adds the Anthropic SDK for standalone
  reasoning; `culprit[mcp]` adds the MCP server (requires Python 3.10+).

## Dev setup

```bash
git clone https://github.com/noordeen123/culprit.git
cd culprit
python -m pip install -e ".[dev]"
pytest -q
```

To also run the MCP server tests (requires Python 3.10+):

```bash
pip install -e ".[mcp,dev]"
pytest -q tests/test_mcp_server.py
```

The test suite builds throwaway git repos in temp dirs, so you need `git` on PATH
(and a configured `user.name`/`user.email`, which CI sets globally).

## Architecture (where things live)

### Plumbing
- `culprit/_proc.py` — read-only `git`/`gh` subprocess helpers; the only place processes are spawned.
- `culprit/config.py` — resolve base branch and host from `.culprit.toml` / env vars.
- `culprit/pr_context.py` — resolve a PR/branch into a normalized `ctx`: `gh` → GitHub/GitLab REST → local git. Host detection + deep-link templates. Also `from_trace` (frames → synthetic diff).

### Classification
- `culprit/classify.py` — bugfix-vs-feature scoring from branch prefix, labels, title, and commit subjects.

### Bugfix path
- `culprit/suspect.py` — parse the fix's hunks; `git blame` the removed lines at base → ranked suspect set.
- `culprit/evolution.py` — `git log -L` over the buggy lines → line-evolution timeline.
- `culprit/intent.py` — the introducing commit's message body, its PR (title/body), and linked issues.
- `culprit/lifecycle.py` — `git tag --contains` → releases that shipped the bug; hotspot detection.
- `culprit/completeness.py` — other un-patched references to changed symbols; adds-test and revert detection.
- `culprit/bisect.py` — optional `git bisect` in a throwaway worktree to confirm the blamed suspect.

### Feature path
- `culprit/blast_radius.py` — reverse-import map, covering tests, test-gap, high-risk module detection.

### QA layer (any path)
- `culprit/risk.py` — combine signals into a 0-100 QA risk score (the CI gate input).
- `culprit/testimpact.py` — reverse-import graph walk → the tests that cover the changed files.
- `culprit/coverage.py` — optional: parse lcov/Cobertura → which changed lines are uncovered.
- `culprit/coupling.py` — `git log` mining for files that co-change; "did you forget X?" signal.
- `culprit/owners.py` — reviewer suggestions from `CODEOWNERS` + git authorship.

### Symptom input
- `culprit/trace.py` — parse Python/JS/Java/Go stack traces; resolve frames to repo files.

### Fix verification
- `culprit/verify_fix.py` — check a not-yet-committed diff for completeness and test coverage.

### Assembly and output
- `culprit/reasoning.py` — the only LLM step, behind `ReasoningAdapter` (harness or Claude API).
- `culprit/report.py` — assemble the JSON result and the markdown skeleton.
- `culprit/htmlreport.py` — render the self-contained HTML report.
- `culprit/templates/report.html` — zero-build vanilla-JS report UI.
- `culprit/serve.py` — interactive local web UI with a base-branch picker.
- `culprit/mcp_server.py` — MCP server (`culprit-mcp`): 11 tools over stdio for any MCP-compatible client.
- `culprit/cli.py` — the `rca`/`culprit` entrypoint; orchestrates the above.

## Pull requests

1. Branch from `main` (`fix/...` or `feat/...`).
2. Add or update tests under `tests/` — every behavior change should be covered.
3. Run `pytest -q` (CI runs on Python 3.9/3.11/3.12; MCP tests run separately on 3.11).
4. Keep new code in the same style as the surrounding code; no new runtime deps in
   the core engine without discussion.
5. Open the PR with a clear description of the change and why.

## Releasing

The version is derived from the git tag by `setuptools-scm` — there is no version
string to edit anywhere in the code. To cut a release:

1. Update `CHANGELOG.md` (move items from `[Unreleased]` into a new version heading).
2. Create a GitHub release with tag `vX.Y.Z` targeting `main`.

The publish workflow builds straight from the tag, so the package version always
matches the tag. (A tag of `v0.4.0` produces `culprit 0.4.0`; commits between tags
build as `0.4.1.devN+g<hash>` locally.)

## Reporting bugs

Open an issue with: the command you ran, the repo/host/language, what you expected,
and what happened. A minimal reproducer (or a public repo + PR number) helps a lot.
