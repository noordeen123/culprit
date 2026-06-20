"""Classify a change as a bugfix or a feature, with evidence.

Deterministic scoring over branch name, PR labels, and commit/title prefixes.
The verdict is advisory: the Claude Code harness (or the API reasoning layer)
makes the final call, but the score + evidence give it grounded signal instead
of guessing.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

_BUG_BRANCH = re.compile(r"^(bug|bugfix|fix|hotfix|patch)[/\-_]", re.I)
_FEAT_BRANCH = re.compile(r"^(feat|feature|enhancement|chore|refactor)[/\-_]", re.I)

# Leading [\W_]* tolerates real-world prefixes like "- fix:", "🚀 feat:", ": fixes".
_BUG_PREFIX = re.compile(r"^[\W_]*(bug\s*)?fix(es|ed)?\b|^[\W_]*hotfix\b|^[\W_]*patch\b", re.I)
_FEAT_PREFIX = re.compile(r"^[\W_]*(feat|feature|add|implement|introduce|chore|refactor)\b", re.I)

_BUG_LABELS = {"bug", "bugfix", "regression", "defect", "hotfix"}
_FEAT_LABELS = {"feature", "enhancement", "feat", "improvement"}


def _add(evidence: List[str], score: int, delta: int, msg: str) -> int:
    evidence.append(msg)
    return score + delta


def classify(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Return {verdict, confidence, evidence, score} from a pr_context dict."""
    score = 0  # positive → bugfix, negative → feature
    evidence: List[str] = []

    branch = ctx.get("head_ref") or ""
    if _BUG_BRANCH.match(branch):
        score = _add(evidence, score, 2, "branch '{}' uses a fix/bug prefix".format(branch))
    elif _FEAT_BRANCH.match(branch):
        score = _add(evidence, score, -2, "branch '{}' uses a feat/feature prefix".format(branch))

    labels = [str(l).lower() for l in (ctx.get("labels") or [])]
    for lab in labels:
        if lab in _BUG_LABELS:
            score = _add(evidence, score, 3, "PR label '{}' indicates a bug".format(lab))
        elif lab in _FEAT_LABELS:
            score = _add(evidence, score, -3, "PR label '{}' indicates a feature".format(lab))

    title = ctx.get("title") or ""
    if title:
        if _BUG_PREFIX.search(title):
            score = _add(evidence, score, 2, "PR title '{}' reads like a fix".format(title))
        elif _FEAT_PREFIX.search(title):
            score = _add(evidence, score, -2, "PR title '{}' reads like a feature".format(title))

    bug_commits = 0
    feat_commits = 0
    for c in ctx.get("commits", []):
        subj = c.get("subject") or ""
        if _BUG_PREFIX.search(subj):
            bug_commits += 1
        elif _FEAT_PREFIX.search(subj):
            feat_commits += 1
    if bug_commits or feat_commits:
        if bug_commits > feat_commits:
            score = _add(evidence, score, 1,
                         "{} of {} commit subjects look like fixes".format(
                             bug_commits, len(ctx.get("commits", []))))
        elif feat_commits > bug_commits:
            score = _add(evidence, score, -1,
                         "{} of {} commit subjects look like features".format(
                             feat_commits, len(ctx.get("commits", []))))

    if score > 0:
        verdict = "bugfix"
    elif score < 0:
        verdict = "feature"
    else:
        verdict = "unknown"

    # Confidence scales with the margin; capped at a readable 0.95.
    confidence = min(0.95, 0.5 + 0.1 * abs(score)) if verdict != "unknown" else 0.0

    return {
        "verdict": verdict,
        "confidence": round(confidence, 2),
        "score": score,
        "evidence": evidence,
    }
