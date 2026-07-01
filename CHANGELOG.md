# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Self-suspect guard.** Suspects are checked against the target branch
  (`merge-base --is-ancestor`): each carries `in_base`, and `bugfix.origin_on_branch`
  flags when the prime suspect is a commit on the current branch (part of the change
  being analyzed) rather than the bug's true origin. The report Summary, markdown, and
  a stderr note say so and point at `--base <trunk>` instead of naming a false origin.
- **Report Summary + collapsible timeline.** The HTML report opens with a pinned
  Summary (verdict, when-it-broke, risk, do-next) and collapses earlier line-evolution
  history by default, so a small change no longer renders a wall of steps.
- **Claude Code skill template** at `examples/claude-code-skill/SKILL.md` - run the
  deterministic engine and let an agent write the narrative (no API key).
- **QA risk score + CI gate.** Every report now carries a single explainable risk
  score (0-100, low/medium/high) combining test gap, fix completeness, hotspot
  recurrence, blast radius, and churn. `--fail-on {low,medium,high}` exits non-zero
  so culprit can act as a read-only CI quality gate; a GitHub Actions template ships
  in `examples/github-actions/culprit-pr.yml`. The HTML report shows a risk banner.
- **Test impact analysis.** `--select-tests` prints the existing tests that reach the
  changed code (direct + transitive via the reverse-import graph), CI-pipeable; the
  structured result gains `test_impact`. `--coverage <lcov|cobertura>` adds ground-truth
  precision, reporting exactly which changed lines are uncovered (sharpening the risk score).
- **RCA from a stack trace.** `--trace PATH` (or `-` for stdin) parses a Python/JS/
  Java/Go stack trace, resolves the frames to repo files, and runs the full RCA
  (suspect + line evolution + risk) on the crashing lines - no fix, PR, or test needed.
- **Predictive signals.** Change-coupling detection surfaces files that historically
  change together with the ones you touched but are missing from the change ("did you
  forget X?"); reviewer suggestions come from `CODEOWNERS` + git authorship.

- The bug's life story for a bugfix: the introducing commit's **intent** (its
  message body + the PR/issue it came from), a **lifecycle** view (which releases
  shipped the bug, commits/authors spanned, recurring-hotspot detection via
  `git tag --contains` / `git log`), and a **fix-completeness** check (other
  untouched references to the changed symbols, whether a test was added, revert
  detection). The HTML report and narrative are restructured into an
  Introduced -> Lived -> Broke -> Why -> Fixed -> Prevent story.

### Changed

- Version is now derived from the git tag via `setuptools-scm` - no version string
  is hardcoded in `pyproject.toml` / `culprit/__init__.py` anymore.

## [0.1.2] - 2026-06-20

### Added

- Optional `git bisect` confirmation: `--bisect "<cmd>"` (with `--good`/`--bad`)
  runs a real bisect in a throwaway git worktree (read-only) and stamps the
  report when the first failing commit matches the blamed suspect.

### Fixed

- Treat a non-comparable bisect result (`agrees_with_suspect=None`) as "not
  comparable" instead of "differs", in both the CLI message and the HTML report.

## [0.1.1] - 2026-06-20

### Changed

- Richer PyPI metadata: Trove classifiers (Python 3.9-3.12, topics, audience) and
  an SPDX `license = "MIT"` expression with bundled `LICENSE`.

### Added

- Project docs: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, issue and
  pull-request templates, and README status badges.

## [0.1.0] - 2026-06-20

Initial release.

### Added

- **Classification** - detect whether a change is a bugfix or a feature, with
  evidence (branch prefix, labels, commit/title prefixes).
- **Bugfix RCA** - ranked **suspect set** (commits that last touched the lines a
  fix changed, via `git blame` / `git log -L`) plus a **line-evolution timeline**
  (origin -> ... -> the commit that broke it -> the fix).
- **Feature blast radius** - reverse-import dependents, covering tests, and
  high-risk shared/core modules; **test-gap** detection.
- **Frontends** - a CLI (`rca` / `culprit`), a **self-contained visual HTML
  report** (timeline, deep links, bug-age banner, test-gap callout, blast-radius
  graph), and an interactive **`serve`** mode with a base-branch picker.
- **Pluggable reasoning** - the "why it broke" narrative is behind an adapter
  (Claude Code harness or the Claude API); the tool works fully with no API key.
- **Multi-host** - PR/MR metadata via GitHub and GitLab REST (no auth needed for
  public repos); deep links for GitHub, GitLab, Bitbucket, and Gitea.
- **Multi-language** import detection (JS/TS, Python, Go, Java/Kotlin, Ruby,
  C/C++, C#, PHP, Rust, Scala, Swift).
- Configurable base branch and host via `.culprit.toml` / `CULPRIT_BASE` /
  `CULPRIT_HOST`.

[Unreleased]: https://github.com/noordeen123/culprit/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/noordeen123/culprit/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/noordeen123/culprit/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/noordeen123/culprit/releases/tag/v0.1.0
