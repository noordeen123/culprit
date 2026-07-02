"""culprit MCP server: expose the RCA engine as native tool calls.

Install:  pip install culprit[mcp]
Run:      culprit-mcp          (stdio transport — works with any MCP-compatible client)

Add to your client's MCP config (Claude Code, Cursor, Windsurf, VS Code, Codex CLI, …):
    {
      "mcpServers": {
        "culprit": { "command": "culprit-mcp" }
      }
    }

Tools are in two tiers:
  Coarse  — analyze, classify_change, find_suspects, get_blast_radius, get_risk_score
  Fine    — get_evolution, get_intent, check_completeness, get_test_impact, from_trace
  Verify  — verify_fix  (check completeness of a proposed diff pre-commit)
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    raise ImportError(
        "MCP server requires the 'mcp' package. "
        "Install with: pip install culprit[mcp]"
    )

from . import (
    blast_radius,
    classify,
    completeness,
    config,
    evolution,
    pr_context,
    suspect,
    testimpact,
)
from . import (
    intent as intent_mod,
)
from . import (
    risk as risk_mod,
)
from . import (
    verify_fix as verify_fix_mod,
)
from .cli import _run as _cli_run
from .cli import _trunk, analyze_trace
from .cli import analyze as cli_analyze

mcp = FastMCP(
    "culprit",
    instructions=(
        "RCA (root-cause analysis) engine for git repos. "
        "Recommended agent workflow:\n"
        "  1. analyze()           — full overview in one call (classify + suspects/blast-radius + risk + test impact)\n"
        "  2. find_suspects()     — drill into which commits introduced the bug\n"
        "  3. get_evolution()     — line-by-line history of the exact buggy lines\n"
        "  4. get_intent()        — what the author was trying to do in the suspect commit\n"
        "  5. check_completeness()— are there other call sites the fix missed?\n"
        "  6. verify_fix()        — check proposed diff pre-commit; iterate until verdict='complete'\n"
        "  7. get_risk_score()    — QA gate score (use with --fail-on in CI)\n\n"
        "For a stack trace with no fix in hand, start with from_trace() instead of analyze(). "
        "All tools are read-only — they never modify the repo or create commits."
    ),
)


def _resolve(repo: str, base: Optional[str] = None, head: Optional[str] = None,
             pr: Optional[int] = None) -> Dict[str, Any]:
    repo = os.path.abspath(repo)
    return pr_context.resolve(repo, pr=pr, base=base or config.repo_base(repo), head=head)


# ---------------------------------------------------------------------------
# Coarse tools
# ---------------------------------------------------------------------------

@mcp.tool()
def analyze(repo: str, base: str = None, head: str = None, pr: int = None) -> dict:
    """Full RCA in one call: classify → suspects (bugfix) or blast-radius (feature) → risk score → test impact.

    Returns the complete structured result. Use the individual tools to drill into specific signals.
    """
    repo = os.path.abspath(repo)
    return cli_analyze(repo, pr=pr, base=base or config.repo_base(repo), head=head)


@mcp.tool()
def classify_change(repo: str, base: str = None, head: str = None) -> dict:
    """Classify whether a change is a bugfix or a feature, with evidence.

    Returns: {verdict: "bugfix"|"feature"|"unknown", evidence: [...], signals: {...}}
    """
    ctx = _resolve(repo, base, head)
    return classify.classify(ctx)


@mcp.tool()
def find_suspects(repo: str, base: str = None, head: str = None,
                  trace_text: str = None) -> dict:
    """Find the commits most likely to have introduced a bug.

    Pass trace_text (a stack trace / crash log) to run RCA from a runtime error
    with no diff needed. Otherwise diffs base..head to find suspects.

    Returns: {suspects: [{hash, short, author, date, subject, pr_number, weight, lines}],
              origin_on_branch: bool, notes: [...]}
    """
    repo = os.path.abspath(repo)
    if trace_text:
        from . import trace as trace_mod
        frames = trace_mod.parse(trace_text)
        resolved, _ = trace_mod.resolve_files(repo, frames)
        ctx = pr_context.from_trace(repo, resolved)
    else:
        ctx = _resolve(repo, base, head)
    return suspect.find_suspects(ctx, repo, trunk=_trunk(repo))


@mcp.tool()
def get_blast_radius(repo: str, base: str = None, head: str = None) -> dict:
    """Map what a feature change affects: who imports the changed modules, covering tests, high-risk areas.

    Returns: {dependents: {...}, covering_tests: [...], high_risk: [...], notes: [...]}
    """
    ctx = _resolve(repo, base, head)
    return blast_radius.analyze(ctx, repo)


@mcp.tool()
def get_risk_score(repo: str, base: str = None, head: str = None, pr: int = None) -> dict:
    """QA risk score for a change: 0-100 with level (low/medium/high) and contributing factors.

    Combines test gap, fix completeness, hotspot recurrence, blast radius, and churn.

    Returns: {score: int, level: "low"|"medium"|"high", factors: [{name, detail, points}]}
    """
    ctx = _resolve(repo, base, head, pr)
    result = _cli_run(ctx, repo)
    return risk_mod.score(result)


# ---------------------------------------------------------------------------
# Fine-grained tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_evolution(repo: str, file: str, start_line: int, end_line: int,
                  base: str = None) -> dict:
    """``git log -L`` over a line range: every commit that touched those lines, oldest to newest, with per-step diffs.

    Returns: {steps: [{hash, short, author, date, subject, diff}], notes: [...]}
    """
    repo = os.path.abspath(repo)
    base_ref = base or config.repo_base(repo) or "HEAD"
    notes = []
    steps = evolution._log_L(repo, start_line, end_line, file, base_ref)
    if not steps:
        notes.append("no git log -L history found for {}:{}-{}".format(file, start_line, end_line))
    return {"steps": steps, "notes": notes}


@mcp.tool()
def get_intent(repo: str, commit_hash: str) -> dict:
    """Commit body + the PR it came from (title, body, url) + linked issues (Fixes/Closes/Resolves #N).

    Returns: {body: str, pr: {number, title, body, url} | null, linked_issues: [...]}
    """
    repo = os.path.abspath(repo)
    ctx: Dict[str, Any] = {"commits": [{"hash": commit_hash}]}
    commit = {"hash": commit_hash, "pr_number": None}
    return intent_mod.enrich(repo, ctx, commit)


@mcp.tool()
def check_completeness(repo: str, base: str = None, head: str = None) -> dict:
    """Is the fix complete? Find other references to changed symbols not touched by this fix.

    Returns: {symbols: [...], other_call_sites: {...}, untouched_count: int,
              adds_test: bool, is_revert: bool, notes: [...]}
    """
    ctx = _resolve(repo, base, head)
    return completeness.assess(ctx, repo, [])


@mcp.tool()
def get_test_impact(repo: str, base: str = None, head: str = None) -> dict:
    """Which existing tests should be run for this change.

    Walks the reverse-import graph from changed files to tests that cover them
    directly or transitively (up to 2 hops).

    Returns: {tests: [...], by_test: {test: [reasons]}, notes: [...]}
    """
    ctx = _resolve(repo, base, head)
    return testimpact.select(ctx, repo)


@mcp.tool()
def from_trace(repo: str, trace_text: str, head: str = None) -> dict:
    """RCA from a stack trace or crash log — no diff or PR needed.

    Parses the stack trace, blames the crashing lines in git history, and returns
    the suspect set. Works for Python, JavaScript, Java, and Go stack traces.

    Returns: {suspects: [...], frames: [{file, line, func}], skipped_frames: [...], notes: [...]}
    """
    repo = os.path.abspath(repo)
    result = analyze_trace(repo, trace_text, head=head)
    return {
        "suspects": (result.get("bugfix") or {}).get("suspects", []),
        "frames": result.get("trace", {}).get("frames", []),
        "skipped_frames": result.get("trace", {}).get("skipped", []),
        "notes": (result.get("bugfix") or {}).get("notes", []),
    }


# ---------------------------------------------------------------------------
# Fix verification
# ---------------------------------------------------------------------------

@mcp.tool()
def verify_fix(repo: str, proposed_diff: str, base: str = None) -> dict:
    """Check fix completeness against a raw unified diff before committing.

    Runs completeness + test-impact analysis on the proposed diff and returns a verdict.
    Iterate until verdict == "complete" before committing.

    Returns: {verdict: "complete"|"partial"|"risky", symbols_fixed: [...],
              untouched_references: [...], tests_to_run: [...], adds_test: bool,
              risk_level: "low"|"medium"|"high", notes: [...]}
    """
    repo = os.path.abspath(repo)
    return verify_fix_mod.assess(repo, proposed_diff, base)


def main() -> None:
    mcp.run()
