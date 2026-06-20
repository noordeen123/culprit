"""Bugfix path: find the commit(s) that introduced the bug.

The insight: in a *fix* diff, the lines the fix removed or changed (the ``-``
lines) are the buggy lines. Blame those lines at the base revision and the
commit that last touched them is the prime suspect. For pure-addition fixes
(a guard added, nothing removed) we blame the surrounding context instead.

Produces a ranked suspect set; the reasoning layer turns it into the "why".
"""
from __future__ import annotations

import datetime
import re
from typing import Any, Dict, List, Optional, Tuple

from . import _proc

MAX_FILES = 150  # safety cap on how many changed files to blame in one run

_DIFF_GIT = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_OLD_PATH = re.compile(r"^--- (?:a/)?(.+)$")
_NEW_PATH = re.compile(r"^\+\+\+ (?:b/)?(.+)$")
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _parse_hunks(diff: str) -> List[Dict[str, Any]]:
    """Return [{old_path, removed_ranges, context_ranges}] per file.

    ``removed_ranges`` are (start, end) line ranges in the OLD file covering
    runs of removed lines. ``context_ranges`` cover the old-side hunk extent,
    used as a fallback for pure-addition hunks.
    """
    files: Dict[str, Dict[str, Any]] = {}
    old_path: Optional[str] = None
    old_lineno = 0
    run_start: Optional[int] = None
    cur: Optional[Dict[str, Any]] = None

    def close_run(end_inclusive: int):
        nonlocal run_start
        if run_start is not None and cur is not None:
            cur["removed_ranges"].append((run_start, end_inclusive))
            run_start = None

    for line in diff.splitlines():
        m = _DIFF_GIT.match(line)
        if m:
            close_run(old_lineno - 1)
            old_path = m.group(1)
            cur = files.setdefault(old_path, {"old_path": old_path,
                                              "removed_ranges": [], "context_ranges": []})
            continue
        m = _OLD_PATH.match(line)
        if m and cur is not None:
            if m.group(1) != "/dev/null":
                cur["old_path"] = m.group(1)
                old_path = m.group(1)
            continue
        if _NEW_PATH.match(line):
            continue
        m = _HUNK.match(line)
        if m:
            close_run(old_lineno - 1)
            old_start = int(m.group(1))
            old_count = int(m.group(2) or "1")
            old_lineno = old_start
            if cur is not None and old_count > 0:
                cur["context_ranges"].append((old_start, old_start + old_count - 1))
            continue
        if cur is None:
            continue
        if line.startswith("-") and not line.startswith("---"):
            if run_start is None:
                run_start = old_lineno
            old_lineno += 1
        elif line.startswith("+") and not line.startswith("+++"):
            # added line: belongs to new file only, doesn't advance old_lineno
            pass
        else:
            # context line (or other): a removed run ends here
            close_run(old_lineno - 1)
            old_lineno += 1

    close_run(old_lineno - 1)
    # Keep files that actually changed something we can blame.
    return [f for f in files.values() if f["removed_ranges"] or f["context_ranges"]]


def _blame_lines(repo: str, rev: str, path: str, start: int, end: int) -> List[Dict[str, str]]:
    """Return per-line blame info for path@rev over [start, end]."""
    try:
        out = _proc.git(
            ["blame", "--line-porcelain", "-L", "{},{}".format(start, end), rev, "--", path],
            repo,
        )
    except _proc.ProcError:
        return []
    lines: List[Dict[str, str]] = []
    cur: Dict[str, str] = {}
    for raw in out.splitlines():
        m = re.match(r"^([0-9a-f]{7,40}) \d+ \d+", raw)
        if m:
            if cur:
                lines.append(cur)
            cur = {"sha": m.group(1)}
        elif raw.startswith("author "):
            cur["author"] = raw[len("author "):]
        elif raw.startswith("author-time "):
            cur["author_time"] = raw[len("author-time "):]
        elif raw.startswith("summary "):
            cur["summary"] = raw[len("summary "):]
    if cur:
        lines.append(cur)
    return lines


def _iso(epoch: Optional[str]) -> Optional[str]:
    if not epoch:
        return None
    try:
        return datetime.datetime.utcfromtimestamp(int(epoch)).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return None


def _pr_for_commit(repo: str, sha: str, upto: str) -> Optional[int]:
    """Best-effort: find the 'Merge pull request #N' that brought sha in."""
    try:
        out = _proc.git(
            ["log", "--merges", "--ancestry-path", "--reverse", "--pretty=%s",
             "{}..{}".format(sha, upto)],
            repo, check=False,
        )
    except _proc.ProcError:
        return None
    for subj in out.splitlines():
        m = re.search(r"Merge pull request #(\d+)", subj)
        if m:
            return int(m.group(1))
    return None


def find_suspects(ctx: Dict[str, Any], repo: str, max_suspects: int = 5) -> Dict[str, Any]:
    """Blame the buggy lines at base and rank the introducing commits."""
    base = ctx.get("base_sha") or ctx.get("base_ref")
    head = ctx.get("head_sha") or ctx.get("head_ref") or "HEAD"
    notes: List[str] = []
    if not base or _proc.git(["rev-parse", "--verify", str(base)], repo, check=False).strip() == "":
        return {"suspects": [], "notes": ["base revision not resolvable locally; "
                                          "fetch the base branch to enable suspect blame"]}

    # Aggregate blame across all buggy line ranges. Cap the work so a huge
    # changeset (e.g. a branch far ahead of a stale base) can't blow up.
    agg: Dict[str, Dict[str, Any]] = {}
    blamed_lines = 0
    parsed = _parse_hunks(ctx.get("diff") or "")
    if len(parsed) > MAX_FILES:
        notes.append("changeset has {} files; blaming only the first {} "
                     "(narrow the base or analyze one commit)".format(len(parsed), MAX_FILES))
        parsed = parsed[:MAX_FILES]
    for f in parsed:
        path = f["old_path"]
        ranges = f["removed_ranges"] or f["context_ranges"]
        if not f["removed_ranges"] and f["context_ranges"]:
            notes.append("{}: pure-addition fix; blaming surrounding context".format(path))
        for (start, end) in ranges:
            for ln in _blame_lines(repo, str(base), path, start, end):
                sha = ln.get("sha")
                if not sha:
                    continue
                blamed_lines += 1
                entry = agg.setdefault(sha, {
                    "hash": sha,
                    "author": ln.get("author"),
                    "date": _iso(ln.get("author_time")),
                    "subject": ln.get("summary"),
                    "lines": 0,
                    "files": set(),
                })
                entry["lines"] += 1
                entry["files"].add(path)

    suspects = sorted(agg.values(), key=lambda e: e["lines"], reverse=True)[:max_suspects]
    for s in suspects:
        s["files"] = sorted(s["files"])
        s["pr_number"] = _pr_for_commit(repo, s["hash"], str(head))
        s["short"] = s["hash"][:10]
        s["weight"] = round(s["lines"] / blamed_lines, 2) if blamed_lines else 0.0

    return {"suspects": suspects, "blamed_lines": blamed_lines, "notes": notes}
