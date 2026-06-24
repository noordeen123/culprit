"""Turn the structured analysis into one explainable QA risk score.

This is the reframe that makes culprit a QA gate rather than a post-mortem: it
combines the signals the engine already computes - test gap, fix completeness,
hotspot recurrence, blast radius, churn - into a single 0-100 score with a
level (low/medium/high) and a list of the factors that contributed, so a CI job
can fail on `--fail-on high` and a reviewer can see *why*.

No ML, no history, no new dependencies - just a weighted sum over the existing
result dict, fully deterministic and explainable.
"""
from __future__ import annotations

from typing import Any, Dict, List

# Score bands. Tunable, but kept simple and stable so CI gates are predictable.
_MEDIUM = 30
_HIGH = 60
_LEVELS = ["low", "medium", "high"]


def _level(score: int) -> str:
    if score >= _HIGH:
        return "high"
    if score >= _MEDIUM:
        return "medium"
    return "low"


def level_at_least(level: str, threshold: str) -> bool:
    """True when `level` meets or exceeds `threshold` (for --fail-on)."""
    try:
        return _LEVELS.index(level) >= _LEVELS.index(threshold)
    except ValueError:
        return False


def score(result: Dict[str, Any]) -> Dict[str, Any]:
    """Return ``{score, level, factors}`` where each factor is ``{name, points, detail}``."""
    factors: List[Dict[str, Any]] = []

    def add(name: str, points: int, detail: str):
        if points > 0:
            factors.append({"name": name, "points": int(points), "detail": detail})

    target = result.get("target") or {}
    bugfix = result.get("bugfix") or {}
    feature = result.get("feature") or {}
    changed = target.get("changed_files") or []

    # --- coverage / test gap ----------------------------------------------
    # Real coverage (when supplied via --coverage) is ground truth and supersedes
    # the import heuristic, so we don't double-count the two.
    cov = result.get("coverage") or {}
    cp = bugfix.get("completeness") or {}
    # Only trust coverage as ground truth when it actually matched changed files;
    # a parse/path-mismatch failure must fall back to the heuristic, not lower risk.
    if cov and (cov.get("checked_files") or 0) > 0:
        unc = cov.get("files_with_uncovered") or 0
        if unc:
            add("uncovered changes", min(30, 8 * unc),
                "{} changed file(s) have uncovered lines (per coverage report)".format(unc))
    else:
        tg = bugfix.get("test_gap") or {}
        untested = tg.get("untested") or []
        if untested:
            add("test gap", min(30, 8 * len(untested)),
                "{} changed file(s) have no covering tests".format(len(untested)))
        if bugfix and cp.get("adds_test") is False and not untested:
            add("no test added", 10, "the fix does not add or update a test")
    untouched = cp.get("untouched_count") or 0
    if untouched:
        add("incomplete fix", min(20, 4 * untouched),
            "{} other reference(s) to the changed symbol(s) were not touched".format(untouched))
    if cp.get("is_revert"):
        add("revert", 5, "the change effectively reverts the introducing commit")

    rec = (bugfix.get("lifecycle") or {}).get("recurrence") or {}
    if rec.get("is_hotspot"):
        add("hotspot", 25, "touches a fragile hotspot ({} prior fixes to this file)".format(
            rec.get("fix_count")))

    # --- feature signals --------------------------------------------------
    deps = feature.get("total_dependents") or 0
    if deps:
        add("blast radius", min(25, deps),
            "{} module(s) import the changed code".format(deps))
    high_risk = feature.get("high_risk") or []
    if high_risk:
        add("high-risk modules", min(20, 7 * len(high_risk)),
            "{} touched file(s) live in shared/core areas".format(len(high_risk)))

    # --- churn (both paths) ----------------------------------------------
    n_files = len(changed)
    if n_files >= 10:
        add("large changeset", min(15, n_files // 5),
            "{} files changed".format(n_files))

    total = min(100, sum(f["points"] for f in factors))
    factors.sort(key=lambda f: f["points"], reverse=True)
    return {"score": total, "level": _level(total), "factors": factors}
