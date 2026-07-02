"""Fix verification: check if a proposed diff fully addresses the root cause.

Takes a not-yet-committed unified diff and checks completeness (other untouched call
sites), test coverage, and risk level, returning a verdict so the caller can iterate
before committing.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import completeness, testimpact
from .suspect import _DIFF_GIT


def _changed_files_from_diff(diff: str) -> List[str]:
    seen: Dict[str, None] = {}
    for line in (diff or "").splitlines():
        m = _DIFF_GIT.match(line)
        if m:
            seen.setdefault(m.group(2), None)
    return list(seen)


def assess(repo: str, proposed_diff: str, base: Optional[str] = None) -> Dict[str, Any]:
    """Return a fix-verification result for a proposed (not-yet-committed) diff.

    Args:
        repo: path to the git repository
        proposed_diff: raw unified diff of the proposed change
        base: optional base ref (unused currently, reserved for future blast-radius use)

    Returns dict with:
        verdict            "complete" | "partial" | "risky"
        symbols_fixed      symbol names the fix touches
        untouched_references  other files referencing those symbols the fix missed
        tests_to_run       existing test files that cover the changed code
        adds_test          whether the fix itself includes a test file
        risk_level         "low" | "medium" | "high"
        notes              advisory strings
    """
    changed_files = _changed_files_from_diff(proposed_diff)
    ctx: Dict[str, Any] = {
        "diff": proposed_diff,
        "changed_files": changed_files,
        "title": "",
        "commits": [],
    }

    comp = completeness.assess(ctx, repo, [])
    impact = testimpact.select(ctx, repo)

    symbols: List[str] = comp.get("symbols", [])
    other_call_sites: Dict[str, List[str]] = comp.get("other_call_sites", {})
    untouched_count: int = comp.get("untouched_count", 0)
    adds_test: bool = comp.get("adds_test", False)
    is_revert: bool = comp.get("is_revert", False)

    # Flatten untouched references, preserving per-symbol order.
    seen_refs: set = set()
    untouched_refs: List[str] = []
    for refs in other_call_sites.values():
        for r in refs:
            if r not in seen_refs:
                seen_refs.add(r)
                untouched_refs.append(r)

    tests_to_run: List[str] = impact.get("tests", [])
    notes: List[str] = comp.get("notes", []) + impact.get("notes", [])

    has_coverage = bool(tests_to_run) or adds_test

    if untouched_count > 2 or (untouched_count > 0 and not has_coverage):
        risk_level = "high"
    elif untouched_count > 0 or not has_coverage:
        risk_level = "medium"
    else:
        risk_level = "low"

    if untouched_count == 0 and has_coverage:
        verdict = "complete"
    elif risk_level == "high":
        verdict = "risky"
    else:
        verdict = "partial"

    if is_revert:
        notes.append("fix appears to be a revert of the introducing commit")

    return {
        "verdict": verdict,
        "symbols_fixed": symbols,
        "untouched_references": untouched_refs,
        "tests_to_run": tests_to_run,
        "adds_test": adds_test,
        "risk_level": risk_level,
        "notes": notes,
    }
