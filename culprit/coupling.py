"""Change coupling: files that historically change together.

Mines ``git log --name-only`` for which files tend to be committed together. For the
files in this change it surfaces their strongest co-change partners and the
missed-change signal: a file that usually changes alongside the ones you touched but
isn't in this change - a likely forgotten edit.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List

from . import _proc

_SOH = "\x01"


def cochange(repo: str, changed_files: List[str], max_commits: int = 500,
             min_support: int = 3, min_confidence: float = 0.4,
             max_commit_size: int = 50, top: int = 5) -> Dict[str, Any]:
    """Return ``{coupled, missed, notes}`` from the repo's commit history."""
    changed = [f for f in (changed_files or []) if f]
    if not changed:
        return {"coupled": {}, "missed": [], "notes": ["no files to analyze"]}

    out = _proc.git(["log", "-n", str(max_commits), "--no-merges", "--name-only",
                     "--pretty=format:" + _SOH + "%H"], repo, check=False)
    commits: List[set] = []
    cur = None
    for line in out.splitlines():
        if line.startswith(_SOH):
            if cur is not None:
                commits.append(cur)
            cur = set()
        elif line.strip() and cur is not None:
            cur.add(line.strip())
    if cur:
        commits.append(cur)

    file_count: Counter = Counter()
    pair: Dict[str, Counter] = defaultdict(Counter)
    for cs in commits:
        # Skip sweeping commits (big refactors/formatting) - they couple everything.
        # Count file_count on the SAME sample as pairs, so confidence isn't deflated.
        if len(cs) > max_commit_size:
            continue
        for f in cs:
            file_count[f] += 1
        files = list(cs)
        for f in files:
            for g in files:
                if g != f:
                    pair[f][g] += 1

    changed_set = set(changed)
    coupled: Dict[str, List[Dict[str, Any]]] = {}
    missed_acc: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"support": 0, "confidence": 0.0, "with": set()})

    for f in changed:
        fc = file_count.get(f, 0)
        if fc < min_support:
            continue
        partners: List[Dict[str, Any]] = []
        for g, cnt in pair[f].most_common():
            conf = cnt / fc
            if cnt >= min_support and conf >= min_confidence:
                partners.append({"file": g, "support": cnt, "confidence": round(conf, 2)})
                if g not in changed_set:
                    acc = missed_acc[g]
                    acc["support"] = max(acc["support"], cnt)
                    acc["confidence"] = max(acc["confidence"], round(conf, 2))
                    acc["with"].add(f)
        if partners:
            coupled[f] = partners[:top]

    missed = [{"file": g, "confidence": v["confidence"], "support": v["support"],
               "with": sorted(v["with"])} for g, v in missed_acc.items()]
    missed.sort(key=lambda m: (m["confidence"], m["support"]), reverse=True)
    return {"coupled": coupled, "missed": missed[:top], "notes": []}
