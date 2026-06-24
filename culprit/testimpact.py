"""Test impact analysis: which existing tests should run for this change?

Given the changed files, walk the **reverse-import graph** (who imports whom) up
to a few hops and collect the test files that reach the change - directly (a test
imports the changed module) or transitively (a test imports a module that imports
the changed module). That's the minimal set worth running for the diff, the
open-source, no-ML version of "predictive test selection".

Reuses ``blast_radius``'s reverse-import map and test/source conventions, so it is
language-agnostic and read-only.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import blast_radius
from .blast_radius import DEFAULT_SOURCE_GLOBS, DEFAULT_TEST_RE


def select(ctx: Dict[str, Any], repo: str, hops: int = 2,
           source_globs: Optional[List[str]] = None, max_seeds: int = 100) -> Dict[str, Any]:
    """Return ``{tests: [...], by_test: {test: [reasons]}, notes}``."""
    source_globs = source_globs or DEFAULT_SOURCE_GLOBS
    changed = [f for f in (ctx.get("changed_files") or []) if f]
    notes: List[str] = []
    tests: Dict[str, set] = {}

    def add_test(path: str, reason: str):
        tests.setdefault(path, set()).add(reason)

    # A changed test file is, trivially, a test to run.
    for f in changed:
        if DEFAULT_TEST_RE.search(f):
            add_test(f, "changed test file")

    seeds = [f for f in changed if not DEFAULT_TEST_RE.search(f)]
    if len(seeds) > max_seeds:
        notes.append("{} changed files; tracing impact for the first {}".format(len(seeds), max_seeds))
        seeds = seeds[:max_seeds]

    # BFS over the reverse-import graph; each item carries its origin changed file.
    visited = set(seeds)
    frontier = [(f, f, 0) for f in seeds]
    while frontier:
        path, origin, depth = frontier.pop(0)
        if depth >= hops:
            continue
        token = blast_radius._module_token(path)
        for imp in blast_radius._importers(repo, token, path, source_globs):
            if DEFAULT_TEST_RE.search(imp):
                hop = depth + 1
                reason = ("covers {}".format(origin) if hop == 1
                          else "covers {} (indirect, {} hops)".format(origin, hop))
                add_test(imp, reason)
            elif imp not in visited:
                visited.add(imp)
                frontier.append((imp, origin, depth + 1))

    return {
        "tests": sorted(tests),
        "by_test": {t: sorted(r) for t, r in tests.items()},
        "notes": notes,
    }
