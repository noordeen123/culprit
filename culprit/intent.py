"""Intent enrichment: what the author was *trying* to do when the bug went in.

The suspect set tells us which commit last touched the buggy lines. This module
adds the missing half - the *intent* behind that commit: its full message body,
the pull request that introduced it (title + description), and any issue it was
meant to close — so the report can contrast what the change was supposed to do
against what it actually did.

Read-only and offline-safe: the PR lookup is best-effort and returns None when
there's no network / gh / forge access; the commit body and linked issues come
from local git alone.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from . import _proc, pr_context

# "Fixes #12", "closes: #3", "Resolved #99" - the issue(s) a change addressed.
_LINKED = re.compile(r"(?i)\b(?:clos(?:e|ed|es)|fix(?:es|ed)?|resolv(?:e|ed|es))\b[:\s]+#(\d+)")


def _linked_issues(*texts: Optional[str]) -> List[int]:
    """Issue numbers referenced by 'Fixes/Closes/Resolves #N' across the texts."""
    seen: List[int] = []
    for text in texts:
        if not text:
            continue
        for m in _LINKED.finditer(text):
            n = int(m.group(1))
            if n not in seen:
                seen.append(n)
    return seen


def _commit_body(repo: str, sha: str) -> Optional[str]:
    """The introducing commit's message body (everything after the subject line)."""
    try:
        out = _proc.git(["show", "-s", "--format=%b", sha], repo, check=False)
    except _proc.ProcError:
        return None
    out = (out or "").strip()
    return out or None


def enrich(repo: str, ctx: Dict[str, Any], commit: Dict[str, Any]) -> Dict[str, Any]:
    """Return ``{body, pr, linked_issues, notes}`` for a suspect/origin commit.

    Costs at most one PR-metadata lookup (only when the commit carries a
    ``pr_number``). Everything degrades to None/[] rather than raising.
    """
    sha = commit.get("hash")
    notes: List[str] = []
    body = _commit_body(repo, sha) if sha else None

    pr_number = commit.get("pr_number")
    pr = pr_context.pr_meta(repo, pr_number) if pr_number else None
    if pr_number and pr is None:
        notes.append("introducing PR #{} metadata unavailable (offline or no access)".format(pr_number))

    pr_body = pr.get("body") if pr else None
    return {
        "body": body,
        "pr": pr,
        "linked_issues": _linked_issues(commit.get("subject"), body, pr_body),
        "notes": notes,
    }


def enrich_origin(repo: str, ctx: Dict[str, Any], timeline: Optional[Dict[str, Any]]) -> None:
    """Enrich the earliest ``origin`` step in the timeline in place.

    Bounded to a single origin (one PR lookup): that's the "when the feature was
    introduced" end of the story; the prime suspect is the "when it broke" end.
    """
    for rng in (timeline or {}).get("ranges", []):
        for step in rng.get("steps", []):
            if step.get("role") == "origin":
                step["intent"] = enrich(repo, ctx, step)
                return
