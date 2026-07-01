"""culprit MCP server: expose the RCA engine as native tool calls.

Install:  pip install culprit[mcp]
Run:      culprit-mcp          (stdio transport — for Claude Code, Cursor, Windsurf)

Add to ~/.claude.json (Claude Code) or mcp_config.json (Cursor):
    {
      "mcpServers": {
        "culprit": { "command": "culprit-mcp" }
      }
    }

Tools are in two tiers:
  Coarse  — analyze, classify_change, find_suspects, get_blast_radius, get_risk_score
  Fine    — get_evolution, get_intent, check_completeness, get_test_impact, from_trace
  Verify  — verify_fix  (check a proposed diff BEFORE committing)
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
    blast_radius, classify, completeness, config, evolution,
    intent as intent_mod, pr_context, risk as risk_mod,
    suspect, testimpact, verify_fix as verify_fix_mod,
)
from .cli import _run as _cli_run, _trunk, analyze as cli_analyze, analyze_trace

mcp = FastMCP("culprit")


def _ctx(repo: str, base: Optional[str] = None, head: Optional[str] = None,
         pr: Optional[int] = None) -> Dict[str, Any]:
    repo = os.path.abspath(repo)
    if pr:
        ctx = pr_context.from_pr(repo, pr)
        if ctx:
            return ctx
    resolved_base = base or config.repo_base(repo)
    return pr_context.from_local(repo, resolved_base, head)


# ---------------------------------------------------------------------------
# Coarse tools
# ---------------------------------------------------------------------------

@mcp.tool()
def analyze(repo: str, base: str = None, head: str = None, pr: int = None) -> dict:
    """Full RCA analysis in one call: classify, find suspects or blast radius, risk, test impact.

    Returns the complete structured result JSON. Use for a quick overview; use the
    individual tools for iterative investigation.
    """
    repo = os.path.abspath(repo)
    result = cli_analyze(repo, pr=pr, base=base, head=head)
    result["risk"] = risk_mod.score(result)
    return result


@mcp.tool()
def classify_change(repo: str, base: str = None, head: str = None) -> dict:
    """Classify whether a change is a bugfix or a feature, with evidence.

    Returns: {verdict: "bugfix"|"feature"|"unknown", evidence: [...], signals: {...}}
    """
    ctx = _ctx(repo, base, head)
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
        import re
        frames = trace_mod.parse(trace_text)
        resolved, _ = trace_mod.resolve_files(repo, frames)
        ctx = pr_context.from_trace(repo, resolved)
    else:
        ctx = _ctx(repo, base, head)
    return suspect.find_suspects(ctx, repo, trunk=_trunk(repo))


@mcp.tool()
def get_blast_radius(repo: str, base: str = None, head: str = None) -> dict:
    """Map what a feature change affects: who imports the changed modules, covering tests, high-risk areas.

    Returns: {dependents: {...}, covering_tests: [...], high_risk: [...], notes: [...]}
    """
    ctx = _ctx(repo, base, head)
    return blast_radius.analyze(ctx, repo)


@mcp.tool()
def get_risk_score(repo: str, base: str = None, head: str = None) -> dict:
    """QA risk score for a change: 0-100 with level (low/medium/high) and contributing factors.

    Combines test gap, fix completeness, hotspot recurrence, blast radius, and churn.

    Returns: {score: int, level: "low"|"medium"|"high", factors: [{name, detail, points}]}
    """
    ctx = _ctx(repo, base, head)
    result = _cli_run(ctx, repo)
    return risk_mod.score(result)


# ---------------------------------------------------------------------------
# Fine-grained tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_evolution(repo: str, file: str, start_line: int, end_line: int,
                  base: str = None) -> dict:
    """How a specific range of lines in a file evolved across commits.

    Shows each commit that touched those lines from creation to present,
    with the per-step diff. Useful for understanding exactly how a bug crept in.

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
    """What the author was trying to do when they made a specific commit.

    Returns the commit body, the PR it came from (title, body, url), and any
    linked issues (e.g. "Fixes #42"). Useful for understanding WHY a bug was introduced.

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
    ctx = _ctx(repo, base, head)
    return completeness.assess(ctx, repo, [])


@mcp.tool()
def get_test_impact(repo: str, base: str = None, head: str = None) -> dict:
    """Which existing tests should be run for this change.

    Walks the reverse-import graph from changed files to tests that cover them
    directly or transitively (up to 2 hops).

    Returns: {tests: [...], by_test: {test: [reasons]}, notes: [...]}
    """
    ctx = _ctx(repo, base, head)
    return testimpact.select(ctx, repo)


@mcp.tool()
def from_trace(repo: str, trace_text: str, head: str = None) -> dict:
    """RCA from a stack trace or crash log — no diff or PR needed.

    Parses the stack trace, blames the crashing lines in git history, and returns
    the suspect set. Works for Python, JavaScript, Java, and Go stack traces.

    Returns: {suspects: [...], changed_files: [...], notes: [...]}
    """
    repo = os.path.abspath(repo)
    result = analyze_trace(repo, trace_text, head=head)
    return {
        "suspects": (result.get("bugfix") or {}).get("suspects", []),
        "changed_files": result.get("trace", {}).get("frames", []),
        "skipped_frames": result.get("trace", {}).get("skipped", []),
        "notes": (result.get("bugfix") or {}).get("notes", []),
    }


# ---------------------------------------------------------------------------
# Fix verification
# ---------------------------------------------------------------------------

@mcp.tool()
def verify_fix(repo: str, proposed_diff: str, base: str = None) -> dict:
    """Check if a proposed fix is complete BEFORE committing.

    Pass the proposed change as a raw unified diff string. Returns whether the fix
    is complete, which other call sites it missed, and which tests to run to validate it.

    Recommended agent workflow:
        find_suspects  →  understand root cause
        (agent proposes fix)
        verify_fix     →  "partial": 2 untouched references found
        (agent patches those references)
        verify_fix     →  "complete"
        (agent commits)

    Returns: {verdict: "complete"|"partial"|"risky", symbols_fixed: [...],
              untouched_references: [...], tests_to_run: [...], adds_test: bool,
              risk_level: "low"|"medium"|"high", notes: [...]}
    """
    repo = os.path.abspath(repo)
    return verify_fix_mod.assess(repo, proposed_diff, base)


def main() -> None:
    mcp.run()
