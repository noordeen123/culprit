# culprit

[![CI](https://github.com/noordeen123/culprit/actions/workflows/ci.yml/badge.svg)](https://github.com/noordeen123/culprit/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/culprit.svg)](https://pypi.org/project/culprit/)
[![Python versions](https://img.shields.io/pypi/pyversions/culprit.svg)](https://pypi.org/project/culprit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Root-cause analysis for a pull request or branch.

`culprit` looks at a PR (or the current branch), decides whether it's a **bugfix**
or a **feature**, then:

- **Bugfix** -> finds the commit that *introduced* the bug. It blames the lines the
  fix removed/changed at the base revision and ranks the commits that last touched
  them (the **suspect set**), then explains why it broke and whether the fix is
  complete.
- **Feature** -> maps the **blast radius**: who imports the changed modules, which
  tests cover them, and which touched files live in high-risk shared/core areas.

It is **read-only** - it never modifies your repo or the PR.

## Example

The visual report (`rca --html report.html`) for a bugfix - a one-line formula
that was silently broken five months before it was fixed. The **line-evolution
timeline** walks every commit that touched those lines: created -> reformatted ->
**the commit that broke it (red)** -> **the fix (green)**.

![culprit RCA report](docs/report.png)

A self-contained HTML file (no server, no CDN) with deep links, a bug-age banner,
a test-gap callout, and expandable per-step diffs.

## Why the split design

The deterministic git work (diff parsing, `git blame` / `git log -L`, the
suspect set, the reverse-import map) lives in a plain Python engine that emits
**structured JSON**. The only LLM step - the "why it broke" narrative - is
isolated behind a `ReasoningAdapter`:

- **HarnessAdapter** - used by the Claude Code skill. Returns the structured
  result + a markdown skeleton; the agent writes the narrative. No API key.
- **ClaudeAPIAdapter** - used standalone. Calls the Claude API
  (`claude-opus-4-8` by default, `--fast` -> `claude-sonnet-4-6`).

Same engine, two frontends.

## Install

```bash
pip install culprit            # engine + CLI (rca / culprit)
pip install "culprit[api]"     # + Claude API reasoning layer (anthropic SDK)
```

Or with [pipx](https://pipx.pypa.io) for an isolated CLI: `pipx install culprit`.
From source: `pip install -e ".[dev]"` then `pytest`.

PR metadata uses the GitHub CLI when available: `brew install gh && gh auth login`.
For **public repos you don't even need `gh`** - `rca --pr N` falls back to the
unauthenticated REST API (**GitHub and GitLab**) for metadata plus a read-only
`git fetch` of the PR/MR head (set `GITHUB_TOKEN` / `GITLAB_TOKEN` to raise rate
limits). With neither, culprit uses local git (base vs head) - fully offline,
minus PR title/labels.

### Any host, any language

- **Hosts:** deep links (commit / PR / file) are generated for **GitHub, GitLab,
  Bitbucket, and Gitea**; the suspect-set + line-evolution timeline work on *any*
  git repo regardless of host. For a self-hosted forge the URL can't disambiguate,
  so set `host = "gitlab"` (or `github`/`bitbucket`/`gitea`) in `.culprit.toml`, or
  `CULPRIT_HOST`.
- **Languages:** suspect/timeline are language-agnostic (pure `git blame`/`log -L`).
  Blast-radius + test-gap detect imports across JS/TS, Python, Go, Java/Kotlin,
  Ruby, C/C++, C#, PHP, Rust, Scala, Swift (quoted *and* bare/dotted import forms).

## Usage

```bash
rca                      # current branch vs the configured base (or latest commit)
rca --last               # just the latest commit ("the change I just made")
rca --pr 16786           # a specific GitHub PR (uses the PR's own base)
rca --repo /path --base main
rca --mode api --fast    # standalone reasoning via the Claude API
rca --json               # structured result only
rca --html report.html --open   # self-contained visual report (timeline UI)
rca --pr 16889 --bisect "pytest tests/test_x.py::test_y"   # confirm the suspect via git bisect
```

## culprit vs `git bisect`

Same goal - find the commit that introduced a bug - but opposite method:

| | `git bisect` | culprit |
|---|---|---|
| Method | *Dynamic* - checks out commits and **runs a test** at each | *Static* - blames the fix's lines + `git log -L` |
| Needs a failing test? | **Required** | No |
| Runs your code? | Yes (serial checkouts) | No |
| Speed | Minutes (~log2(N) runs) | Instant |
| Answers | "first commit where the test fails" | suspect + **how the line evolved** + *why* + bug age + test gap + blast radius |
| Confidence | Proof (if the test is reliable) | Strong heuristic |

culprit is **not** a reimplementation of bisect - it reasons statically from the
patch and gives you the *story*, no test required. But when you *do* have a repro,
`--bisect "<cmd>"` runs a real bisect (in a **throwaway git worktree**, so your
checkout and `HEAD` are never touched) and stamps **"✓ confirmed by git bisect"**
when the first failing commit matches the blamed suspect. The command must exit
non-zero when the bug is present; `--good <ref>` / `--bad <ref>` override the
search bounds (defaults: the suspect's parent and the base).

### Visual HTML report

`--html PATH` writes a **single self-contained HTML file** (inline CSS/JS, data
embedded, no CDN - opens offline, shareable, CI-attachable). For a bugfix it
renders a **line-evolution timeline**: for each line the fix touched, every commit
that ever changed those lines, from creation -> ... -> **the commit that broke it
(red)** -> **the fix (green)**, each step expandable to its diff.

```bash
rca --pr 16889 --html rca.html --open                 # narrative via --mode api if key set
rca --pr 16889 --html rca.html --narrative-file why.md # embed a pre-written narrative
```

The timeline needs no API key. The "Analysis" prose comes from `--narrative-file`
(e.g. written by the Claude Code `/rca` skill) or from `--mode api`.

The report also includes: a **TL;DR banner** naming the prime suspect and how long
the bug lived before the fix; **GitHub deep links** on every commit / PR / file
(derived from `origin`); **weight bars** ranking the suspects; **expand/collapse-all**
and a **per-file filter** for the timeline; and a one-click **copy-as-markdown** to
paste into the PR.

### Choosing the base branch

The base differs per repo (`main`, `master`, `develop`, a long-lived release
branch, ...). Resolution order:
`--base <ref>` -> `CULPRIT_BASE` env -> `.culprit.toml` (`base = "..."`) -> the latest
commit. The static HTML report is generated for one base (shown in the footer with a
regenerate hint). For an **interactive base picker**, use `serve` mode:

```bash
rca serve --repo /path/to/repo     # opens http://127.0.0.1:8722
```

It launches a local web app (stdlib only - no extra deps) with a form: enter a
PR/branch, **pick the base from a dropdown** (pre-filled from `.culprit.toml`,
the repo's default branch, then all local/remote branches), choose
classification + reasoning, and run a fresh analysis that renders the same visual
report. The base picker repopulates when you point it at a different repo. Binds
to localhost only.

### Base branch

In local mode (no PR), culprit needs a base to diff against. Resolution order:

1. `--base <ref>` on the CLI
2. `CULPRIT_BASE` environment variable
3. `base = "..."` in a `.culprit.toml` at the repo root
4. otherwise the latest commit (`HEAD~1`)

So pin your repo's real base once and forget it:

```toml
# .culprit.toml
base = "origin/main"   # whatever your repo is actually cut from
```

`--last` always forces the latest-commit view regardless of config.

## Tests

```bash
pip install -e ".[dev]" && pytest
```
