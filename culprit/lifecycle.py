"""The bug's lifespan: which releases shipped it, how far it spread, recurrence.

Turns the prime suspect into a sense of blast *over time*: the released versions
that carried the bug (``git tag --contains``), how many commits/authors passed
between introduction and fix, and whether this file is a repeat offender (a
hotspot that keeps getting bug-fixed). All read-only git queries.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from . import _proc
from .classify import _BUG_PREFIX

_MAX_RELEASES = 12

# Regex to skip test files when scanning for hotspot recurrence.
_TEST_FILE = re.compile(r'\.(test|spec|cy)\b|[\\/](tests?|__tests__)[\\/]', re.IGNORECASE)


def _tags_containing(repo: str, sha: str) -> List[str]:
    """Release tags whose history includes ``sha`` (version-sorted)."""
    try:
        out = _proc.git(["tag", "--contains", sha, "--sort=v:refname"], repo, check=False)
    except _proc.ProcError:
        return []
    return [t for t in out.splitlines() if t.strip()]


def _recurrence_for_file(repo: str, base: str, path: str) -> Dict[str, Any]:
    subjects = _proc.git(["log", "--format=%s", str(base), "--", path], repo, check=False).splitlines()
    total = len([s for s in subjects if s.strip()])
    fixes = len([s for s in subjects if _BUG_PREFIX.search(s)])
    return {"file": path, "fix_count": fixes, "total_commits": total, "is_hotspot": fixes >= 3}


def build(repo: str, ctx: Dict[str, Any], suspects: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return ``{releases, releases_truncated, total_releases, commits_span, authors_span, recurrence, notes}``."""
    notes: List[str] = []
    if not suspects:
        return {"releases": [], "releases_truncated": False, "total_releases": 0,
                "commits_span": None, "authors_span": None, "recurrence": None,
                "notes": ["no suspect to trace"]}

    suspect = suspects[0]
    sha = suspect.get("hash")
    head = ctx.get("head_sha")
    files = suspect.get("files") or []
    file = files[0] if files else None

    # Releases that shipped the bug: tags that contain the suspect but not the fix.
    releases: List[str] = []
    releases_truncated = False
    total_releases = 0
    if sha:
        bug_tags = _tags_containing(repo, sha)
        fix_tags = set(_tags_containing(repo, head)) if head else set()
        all_bug_releases = [t for t in bug_tags if t not in fix_tags]
        total_releases = len(all_bug_releases)
        if not bug_tags and not fix_tags:
            notes.append("repo has no release tags reachable from the suspect")
        if total_releases > _MAX_RELEASES:
            releases = all_bug_releases[:_MAX_RELEASES]
            releases_truncated = True
        else:
            releases = all_bug_releases

    # How far the bug spread before the fix.
    commits_span = None
    authors_span = None
    if sha and head:
        cnt = _proc.git(["rev-list", "--count", "{}..{}".format(sha, head)], repo, check=False).strip()
        commits_span = int(cnt) if cnt.isdigit() else None
        log_args = ["log", "--format=%an", "{}..{}".format(sha, head)]
        if file:
            log_args += ["--", file]
        authors = _proc.git(log_args, repo, check=False).splitlines()
        authors_span = len({a for a in authors if a.strip()}) or None

    # Recurrence: how many prior commits to the fixed files were themselves bug-fixes.
    # Use the files actually changed in the diff (ctx["changed_files"]) — those contain
    # the buggy code regardless of which file the prime suspect happened to touch.
    # Fall back to the prime suspect's file if the diff file list is unavailable.
    recurrence = None
    base = ctx.get("base_sha") or ctx.get("base_ref")
    if base:
        fix_files = [f for f in (ctx.get("changed_files") or []) if not _TEST_FILE.search(f)]
        check_files = fix_files[:10] or ([file] if file else [])
        best: Dict[str, Any] = {}
        for path in check_files:
            r = _recurrence_for_file(repo, base, path)
            if not best or r["fix_count"] > best["fix_count"]:
                best = r
        if best:
            recurrence = best

    return {
        "releases": releases,
        "releases_truncated": releases_truncated,
        "total_releases": total_releases,
        "commits_span": commits_span,
        "authors_span": authors_span,
        "recurrence": recurrence,
        "notes": notes,
    }
