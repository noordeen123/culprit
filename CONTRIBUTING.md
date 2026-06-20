# Contributing to culprit

Thanks for your interest in improving culprit! Contributions of all kinds are
welcome - bug reports, feature ideas, docs, and code.

## Ground rules

- **culprit is read-only by design.** It must never modify the target repo's
  working tree or the PR/MR. Network `git fetch` of a PR ref is allowed; anything
  that writes to the checkout is not.
- **Repo-agnostic and language-agnostic.** No hardcoded paths, repo names, hosts,
  or organization specifics in the package. The engine should work on any git repo.
- **Dependency-light.** The core engine uses only the Python standard library plus
  `git`/`gh`. The `anthropic` SDK is an optional extra (`culprit[api]`) used solely
  by the Claude API reasoning adapter.

## Dev setup

```bash
git clone https://github.com/noordeen123/culprit.git
cd culprit
python -m pip install -e ".[dev]"
pytest -q
```

The test suite builds throwaway git repos in temp dirs, so you need `git` on PATH
(and a configured `user.name`/`user.email`, which CI sets globally).

## Architecture (where things live)

- `culprit/pr_context.py` - resolve a PR/branch into a normalized context (gh ->
  GitHub/GitLab REST -> local git fallback); host detection + deep-link templates.
- `culprit/classify.py` - bugfix-vs-feature scoring with evidence.
- `culprit/suspect.py` - blame the buggy lines -> ranked suspect set.
- `culprit/evolution.py` - `git log -L` line-evolution timeline.
- `culprit/blast_radius.py` - reverse-import map, covering tests, test-gap.
- `culprit/reasoning.py` - the only LLM step, behind a pluggable adapter.
- `culprit/report.py` / `htmlreport.py` / `templates/report.html` - structured
  result + the self-contained visual report.
- `culprit/serve.py` - the interactive local web UI.
- `culprit/cli.py` - the `rca` / `culprit` entrypoint.

## Pull requests

1. Branch from `main` (`fix/...` or `feat/...`).
2. Add or update tests under `tests/` - every behavior change should be covered.
3. Run `pytest -q` (CI runs it on Python 3.9 / 3.11 / 3.12).
4. Keep new code in the same style as the surrounding code; no new runtime deps in
   the core engine without discussion.
5. Open the PR with a clear description of the change and why.

## Releasing

The version is derived from the git tag by `setuptools-scm` - there is no version
string to edit anywhere in the code. To cut a release:

1. Update `CHANGELOG.md` (move items from `[Unreleased]` into a new version heading).
2. Create a GitHub release with tag `vX.Y.Z` targeting `main`.

The publish workflow builds straight from the tag, so the package version always
matches the tag. (A tag of `v0.2.0` produces `culprit 0.2.0`; commits between tags
build as `0.2.1.devN+g<hash>` locally.)

## Reporting bugs

Open an issue with: the command you ran, the repo/host/language, what you expected,
and what happened. A minimal reproducer (or a public repo + PR number) helps a lot.
