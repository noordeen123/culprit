# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
