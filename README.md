# culprit

[![CI](https://github.com/noordeen123/culprit/actions/workflows/ci.yml/badge.svg)](https://github.com/noordeen123/culprit/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/culprit.svg)](https://pypi.org/project/culprit/)
[![Python versions](https://img.shields.io/pypi/pyversions/culprit.svg)](https://pypi.org/project/culprit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Root-cause analysis for a pull request or branch. Read-only — never modifies your repo or PR.

Given a PR or branch, culprit classifies it as a bugfix or feature:

- **Bugfix** — blames the lines the fix removed at base revision to rank introducing commits (the suspect set), surfaces the author's original intent (introducing PR + linked issue), determines which releases shipped the bug, flags hotspot files, and checks fix completeness (untouched call sites, missing test, revert).
- **Feature** — maps the blast radius: reverse-import dependents, covering tests, high-risk shared modules.

## Example

`rca --html report.html` on a bugfix — a one-line formula silently broken by a `perf`
commit, shipped across three releases. QA risk score, introducing commit intent,
line-evolution timeline (created → broke (red) → fix (green)), test impact, co-change
gaps, reviewer suggestions.

![culprit RCA report](docs/report.png)

Single self-contained HTML file. No server, no CDN. Opens offline, attaches to CI.

## Architecture

The deterministic git work (diff parsing, `git blame`/`git log -L`, suspect set,
reverse-import map) emits structured JSON. The LLM narrative is isolated behind a
`ReasoningAdapter` — `HarnessAdapter` for Claude Code (no key needed), `ClaudeAPIAdapter`
for standalone use (`claude-opus-4-8` default, `--fast` for `claude-sonnet-4-6`).

```text
  PR / branch ---.
  stack trace ---+--> pr_context --> ctx  (diff, changed files, commits, host links)
                          |
                          v
                    classify   (bugfix vs feature, with evidence)
                   /                                  \
          bugfix  v                                    v  feature
   suspect   (blame the lines the fix removed)     blast_radius
     -> evolution  (how the line evolved)           (importers, covering tests,
     -> intent / lifecycle / completeness            high-risk modules)
     -> test_gap
                   \                                  /
                    v                                v
                  report.build --> QA risk score
                          |
            + test_impact . coupling . owners . coverage
                          |
                          v
   reasoning (optional LLM "why") --> output:
      JSON | HTML report | markdown | --select-tests | --fail-on (CI exit code)
```

Full module map and data shapes: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Install

```bash
uvx culprit                          # runs from PyPI on demand, no install step
uvx --from "culprit[api]" rca        # include the Claude API reasoning layer

pip install culprit                  # permanent install
pip install "culprit[api]"           # + anthropic SDK
pipx install culprit                 # isolated CLI
pip install -e ".[dev]" && pytest    # from source
```

PR metadata uses the GitHub CLI when available (`brew install gh && gh auth login`).
For public repos, `rca --pr N` falls back to the unauthenticated REST API (GitHub and
GitLab) — set `GITHUB_TOKEN` / `GITLAB_TOKEN` to raise rate limits. Without either,
culprit uses local git only (no PR title/labels).

**Hosts:** deep links work for GitHub, GitLab, Bitbucket, and Gitea. For self-hosted
forges set `host = "gitlab"` in `.culprit.toml` or `CULPRIT_HOST`.

**Languages:** suspect/timeline are language-agnostic (`git blame`/`log -L`). Blast
radius detects imports across JS/TS, Python, Go, Java/Kotlin, Ruby, C/C++, C#, PHP,
Rust, Scala, Swift.

## Usage

```bash
rca                          # current branch vs configured base (or HEAD~1)
rca --last                   # latest commit only
rca --pr 16786               # specific PR (uses the PR's own base)
rca --repo /path --base main
rca --mode api --fast        # Claude API reasoning, sonnet model
rca --json                   # structured JSON output only
rca --html report.html --open
rca --trace crash.txt        # RCA from a stack trace, no fix/PR needed
rca --verify-fix patch.diff  # check a diff for completeness before committing
rca --select-tests           # print tests to run for this change (CI-pipeable)
rca --pr 16889 --bisect "pytest tests/test_x.py::test_y"
rca --pr 16889 --fail-on high   # exit non-zero when QA risk >= high
rca serve --repo /path          # local web UI with base picker (http://127.0.0.1:8722)
```

## CI

culprit signals risk via exit code only — no PR comments, no writes. Copy
[`examples/github-actions/culprit-pr.yml`](examples/github-actions/culprit-pr.yml)
into `.github/workflows/`:

```yaml
- uses: actions/checkout@v4
  with: { fetch-depth: 0 }
- uses: actions/setup-python@v5
  with: { python-version: "3.12" }
- run: pip install "culprit>=0.3.0"
- env: { GH_TOKEN: "${{ github.token }}" }
  run: rca --pr ${{ github.event.pull_request.number }} --html culprit-report.html --no-save --fail-on high
- if: always()
  uses: actions/upload-artifact@v4
  with: { name: culprit-report, path: culprit-report.html }
```

## MCP server

culprit ships an MCP server that works with any MCP-compatible client over stdio:
Claude Code, Cursor, Windsurf, VS Code, Codex CLI, Zed, Continue.dev, Cline, Amazon Q,
Goose, or any agent built on the MCP SDK. Requires Python 3.10+ and
[uv](https://docs.astral.sh/uv/) (`brew install uv`).

**Claude Code:**

```bash
claude mcp add culprit -- uvx --from "culprit[mcp]" culprit-mcp
```

**Other clients** — add to your client's MCP config (`mcpServers` key; file location
varies by client):

```json
{
  "mcpServers": {
    "culprit": {
      "command": "uvx",
      "args": ["--from", "culprit[mcp]", "culprit-mcp"]
    }
  }
}
```

**Tools (11):**

| Tool | Description |
|---|---|
| `analyze` | Full RCA in one call — classify + suspects/blast-radius + risk + test impact |
| `find_suspects` | Rank commits by likelihood of introducing the bug |
| `get_evolution` | Per-commit line history via `git log -L` for the buggy range |
| `get_intent` | Introducing commit: message body, linked PR, referenced issues |
| `check_completeness` | Call sites the fix didn't touch |
| `verify_fix` | Check a proposed diff before committing — `complete`/`partial`/`risky` |
| `get_risk_score` | QA gate score (0–100, low/medium/high) with contributing factors |
| `get_blast_radius` | Feature change impact: dependents, covering tests, high-risk files |
| `get_test_impact` | Minimal test set to run for this change |
| `classify_change` | Bugfix vs feature with evidence |
| `from_trace` | RCA from a stack trace — no diff or PR required |

For a skill-based alternative (agent runs the CLI and writes the narrative), copy
[`examples/claude-code-skill/SKILL.md`](examples/claude-code-skill/SKILL.md) into
`.claude/skills/rca/` and fill in `<REPO_PATH>` / `<BASE_BRANCH>`.

## vs `git bisect`

| | `git bisect` | culprit |
|---|---|---|
| Input | A reliable failing test | The fix diff (or a stack trace) |
| Method | Checks out commits and runs the test | Blames the fix's lines + `git log -L` |
| Speed | Minutes (~log₂N test runs) | Instant |
| Output | First bad commit | Suspect set, line evolution, intent, lifecycle, completeness, risk score |
| Confidence | Proof | Strong heuristic |

`--bisect "<cmd>"` runs a real bisect as an optional confirmation layer — in a throwaway
`git worktree` so your checkout is never touched. When the first failing commit matches
the blamed suspect, the HTML report stamps it **confirmed by git bisect**. `--good` /
`--bad` override the search bounds.

## HTML report

`--html PATH` produces a single self-contained file (no CDN, opens offline). For a
bugfix it renders a line-evolution timeline: for each line the fix touched, every commit
that ever changed those lines from creation through the breaking commit (red) to the fix
(green), each node expandable to its diff. Also includes: TL;DR banner, lifecycle strip
(releases that shipped the bug), introducing PR intent card, fix-completeness callout,
deep links on every commit/PR/file, weight bars on suspects, per-file filter, and a
copy-as-markdown button.

```bash
rca --pr 16889 --html rca.html --open
rca --pr 16889 --html rca.html --narrative-file why.md   # embed a pre-written narrative
```

## Configuration

Base branch resolution order: `--base` flag → `CULPRIT_BASE` env → `.culprit.toml` → `HEAD~1`.

```toml
# .culprit.toml
base = "origin/main"
```

`--last` forces the latest-commit view regardless of config.

## Tests

```bash
pip install -e ".[dev]" && pytest
```
