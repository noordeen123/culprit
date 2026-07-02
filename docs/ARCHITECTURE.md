# Architecture

culprit is a **repo-agnostic, read-only analysis engine** with thin frontends. The engine
is plain Python (standard library + `git`/`gh` via subprocess); it consumes one normalized
context and emits one structured JSON result. The only optional, non-deterministic step is
the LLM narrative, which is isolated behind an adapter so the engine works with no API key.

Three principles hold everywhere:

- **Read-only.** Nothing ever writes to the target repo or PR. `git status --porcelain` is
  unchanged after any run. Even `git bisect` runs in a throwaway `git worktree`.
- **Repo-agnostic.** No hardcoded paths, hosts, or org names. Everything is derived from the
  repo passed in (`--repo`) and its `origin` remote.
- **Structured first, prose last.** Every module writes a slice of a JSON result; the
  human/LLM narrative is generated from that result, never the other way around.

## Data flow

```text
  PR / branch ---.
  stack trace ---+--> pr_context  -->  ctx  -->  classify  -->  (bugfix | feature) path
                                        |                              |
                                        |                              v
                                        |                      report.build + risk
                                        |                              |
                                        |              + test_impact / coupling / owners / coverage
                                        |                              |
                                        '------------------------------+--> reasoning --> output
```

`ctx` (the normalized context) is the single input every analysis module consumes, so no
module cares whether the target came from `gh`, the REST API, local git, or a stack trace.
Its key fields: `source`, `kind`, `title`, `head_ref`/`base_ref`, `head_sha`/`base_sha`,
`labels`, `commits`, `changed_files`, `diff`, and host deep-link templates (`links`).

The `result` (the structured output) is `ctx`-derived plus: `classification`, `bugfix`
*or* `feature`, `risk`, `test_impact`, `coupling`, `owners`, and (optional) `coverage` /
`trace`.

## Module map

### Plumbing

| Module | Job |
|---|---|
| `_proc.py` | Read-only `git` / `gh` subprocess helpers (the only place processes are spawned). |
| `config.py` | Resolve base branch / host from `.culprit.toml` and env (`CULPRIT_BASE`, `CULPRIT_HOST`). |
| `pr_context.py` | Resolve a PR/branch into `ctx`: `gh` -> GitHub/GitLab REST -> local git. Host detection + deep-link templates. `pr_meta` (arbitrary PR), `from_trace` (frames -> synthetic diff). |

### Classification

| Module | Job |
|---|---|
| `classify.py` | Score branch prefix, labels, title, and commit subjects -> bugfix / feature / unknown, with evidence. |

### Bugfix path

| Module | Job |
|---|---|
| `suspect.py` | Parse the fix's hunks; `git blame` the removed lines at the base -> ranked **suspect set**. |
| `evolution.py` | `git log -L` over the buggy lines -> the **line-evolution timeline** (origin -> ... -> suspect -> fix). |
| `intent.py` | The introducing commit's message body, its PR (title/description), and linked issues - *what they were trying to do*. |
| `lifecycle.py` | `git tag --contains` -> which releases shipped the bug; commits/authors spanned; recurring-**hotspot** detection. |
| `completeness.py` | Other un-patched references to the changed symbols, whether a test was added, revert detection. |
| `bisect.py` | Optional: a real `git bisect` in a throwaway worktree to *confirm* the blamed suspect. |

### Feature path

| Module | Job |
|---|---|
| `blast_radius.py` | Reverse-import map (who imports the changed modules), covering tests, high-risk shared/core modules, and `test_gap`. |

### QA layer (any path)

| Module | Job |
|---|---|
| `risk.py` | Combine the signals above into one explainable 0-100 **QA risk score** (the CI gate input). |
| `testimpact.py` | Walk the reverse-import graph -> the existing **tests to run** for this change. |
| `coverage.py` | Optional: parse lcov/Cobertura -> exactly which changed lines are **uncovered** (ground-truth gap). |
| `coupling.py` | Mine `git log` for files that **change together** -> "you touched A & B, did you forget C?". |
| `owners.py` | Suggest **reviewers** from `CODEOWNERS` + git authorship. |

### Symptom input

| Module | Job |
|---|---|
| `trace.py` | Parse Python / JS / Java / Go **stack traces** and resolve frames to repo files (RCA from a crash, no fix needed). |

### Fix verification

| Module | Job |
|---|---|
| `verify_fix.py` | Given a proposed diff (not yet committed), check completeness via `completeness` + `testimpact` and return `verdict: complete\|partial\|risky` with the untouched call sites and tests to run. Used by the `verify_fix` MCP tool. |

### Reasoning, assembly, output

| Module | Job |
|---|---|
| `reasoning.py` | The only LLM step, behind `ReasoningAdapter`: `HarnessAdapter` (Claude Code writes it) or `ClaudeAPIAdapter`. |
| `report.py` | Assemble the JSON `result` (+ attach the risk score) and a markdown skeleton the narrative fills. |
| `htmlreport.py` | Render the self-contained HTML report (template + injected JSON, no CDN). |
| `templates/report.html` | The zero-build vanilla-JS report UI (risk banner, timeline, all QA sections). |
| `serve.py` | Interactive local web UI with a base-branch picker (credentials in-process only). |
| `mcp_server.py` | MCP server (`culprit-mcp`): exposes all 11 analysis tools over stdio to any MCP-compatible client (Claude Code, Cursor, Windsurf, VS Code, Codex CLI, and more). |
| `cli.py` | The `rca` / `culprit` entrypoint — orchestrates the above and chooses the output. |

## Orchestration (`cli.py`)

`analyze()` resolves a PR/branch and calls `_run(ctx, repo, force, coverage_path)`;
`analyze_trace()` builds `ctx` from a stack trace and calls the same `_run`. `_run` is the
single pipeline: classify -> bugfix/feature analysis -> `report.build` (which computes the
risk score) -> attach `test_impact` / `coupling` / `owners` / `coverage`.

`main()` then picks an output mode from the flags: `--json`, `--html`, `--select-tests`,
default markdown, and `--fail-on <level>` which sets the process **exit code** from the risk
level (the read-only CI gate - it never writes to the PR).

## Cost & safety guards

git operations are read-only and bounded (caps on files blamed, timeline ranges/steps,
co-change commit window, call-site greps). Network calls (`pr_meta`, REST) are best-effort,
budgeted, and degrade to `None`/`[]` offline. `git grep` patterns are POSIX-only (no `\w`/
`\b`) so detection is language-agnostic across ecosystems.
