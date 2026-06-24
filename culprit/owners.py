"""Suggest reviewers for a change: CODEOWNERS rules + git authorship.

Combines the owners declared in a ``CODEOWNERS`` file for the changed paths with the
people who have historically authored the changed (and suspect) files. Read-only.
"""
from __future__ import annotations

import fnmatch
import os
from collections import Counter
from typing import Any, Dict, List, Optional

from . import _proc

# GitHub's lookup order: the first file found wins (.github/ -> root -> docs/).
_CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")


def _load_rules(repo: str) -> List[tuple]:
    for rel in _CODEOWNERS_PATHS:
        p = os.path.join(repo, rel)
        if os.path.isfile(p):
            rules = []
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    owners = [o for o in parts[1:] if o.startswith("@") or "@" in o]
                    if owners:
                        rules.append((parts[0], owners))
            return rules
    return []


def _matches(pattern: str, path: str) -> bool:
    pat = pattern[1:] if pattern.startswith("/") else pattern
    if pat == "*":
        return True
    if pat.endswith("/"):
        return path == pat[:-1] or path.startswith(pat)
    return (path == pat or path.startswith(pat + "/")
            or fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(os.path.basename(path), pat))


def _codeowners(repo: str, changed: List[str]) -> List[str]:
    rules = _load_rules(repo)
    found: List[str] = []
    for path in changed:
        # CODEOWNERS semantics: the last matching rule wins.
        for pattern, owners in reversed(rules):
            if _matches(pattern, path):
                for o in owners:
                    if o not in found:
                        found.append(o)
                break
    return found


def suggest(repo: str, changed_files: List[str], suspects: Optional[List[Dict[str, Any]]] = None,
            max_files: int = 40, top: int = 5) -> Dict[str, Any]:
    """Return ``{codeowners, authors, notes}`` - reviewer suggestions for the change."""
    changed = [f for f in (changed_files or []) if f]
    notes: List[str] = []

    code_owners = _codeowners(repo, changed)

    authors: Counter = Counter()
    files = changed[:max_files]
    if len(changed) > max_files:
        notes.append("{} files; counted authorship on the first {}".format(len(changed), max_files))
    for path in files:
        out = _proc.git(["log", "--format=%an", "--", path], repo, check=False)
        for name in out.splitlines():
            if name.strip():
                authors[name.strip()] += 1
    # Fold in the prime suspect's author (they wrote the line that broke).
    for s in (suspects or [])[:1]:
        if s.get("author"):
            authors[s["author"]] += 1

    ranked = [{"name": n, "commits": c} for n, c in authors.most_common(top)]
    return {"codeowners": code_owners, "authors": ranked, "notes": notes}
