"""Feature path: what can this change break?

For each changed source file, find who imports it (reverse-import map), which
tests cover those modules, and which touched files live in shared/core areas
(high blast radius). Heuristic but grounded - the reasoning layer ranks risk
and recommends the test surface from this structured map.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from . import _proc

DEFAULT_SOURCE_GLOBS = [
    "*.js", "*.jsx", "*.ts", "*.tsx", "*.mjs", "*.cjs", "*.vue", "*.svelte",
    "*.py", "*.go", "*.rb", "*.java", "*.kt", "*.scala", "*.cs", "*.php",
    "*.rs", "*.c", "*.h", "*.cc", "*.cpp", "*.hpp", "*.m", "*.swift",
]
# Test-file conventions across ecosystems: JS spec/test, Python test_*/*_test,
# Go *_test.go, Java/Kotlin/C# *Test/*Tests, Ruby *_spec, plus test dirs.
DEFAULT_TEST_RE = re.compile(
    r"(\.spec\.|\.test\.|_test\.|_spec\.|/__tests__/|(^|/)cypress/|(^|/)tests?/"
    r"|(^|/)test_[^/]*\.(py|rb)$|Tests?\.(java|kt|cs|scala|swift)$|_test\.go$)", re.I)
HIGH_RISK_RE = re.compile(r"(^|/)(shared|common|core|lib|utils?|helpers?|base|hooks|store)(/|$)", re.I)

_INDEX_RE = re.compile(r"(^|/)(index|__init__|mod)\.[^/]+$")


def _module_token(path: str) -> str:
    """The identifier other files most likely import this module by."""
    if _INDEX_RE.search(path):
        # package entry files (index.js / __init__.py / mod.go) are imported by dir name
        return os.path.basename(os.path.dirname(path)) or os.path.basename(path)
    return os.path.splitext(os.path.basename(path))[0]


def _importers(repo: str, token: str, exclude: str, source_globs: List[str]) -> List[str]:
    if not token:
        return []
    tok = re.escape(token)
    # An import-ish line that references the token as a delimited path segment.
    # Covers JS/TS (`import x from '.../token'`, `require('...token...')`), Python
    # (`from a.token import x`, `import a.token`), Java (`import a.b.Token;`),
    # Go/Ruby/C (`".../token"`, `<token.h>`). Uses POSIX classes only - git grep -E
    # has no \w / \b, so token boundaries are spelled [^A-Za-z0-9_].
    pat = r"(import|require|include|from|use).*[^A-Za-z0-9_]{}([^A-Za-z0-9_]|$)".format(tok)
    args = ["grep", "-l", "-I", "-E", "-e", pat, "--"] + source_globs
    out = _proc.git(args, repo, check=False)
    return [f for f in out.splitlines() if f.strip() and f != exclude]


def test_gap(changed_files: List[str], repo: str,
             source_globs: Optional[List[str]] = None, max_files: int = 60) -> Dict[str, Any]:
    """For a bugfix: which changed (non-test) files have no covering tests.

    A regression usually slips through because the touched code isn't tested.
    Reuses the reverse-import map to find test files that import each module.
    """
    source_globs = source_globs or DEFAULT_SOURCE_GLOBS
    files = [f for f in changed_files if f]
    notes: List[str] = []
    if len(files) > max_files:
        notes.append("{} files; checked the first {}".format(len(files), max_files))
        files = files[:max_files]
    covering = set()
    untested: List[str] = []
    for path in files:
        if DEFAULT_TEST_RE.search(path):
            continue  # the changed file is itself a test
        token = _module_token(path)
        tests = [i for i in _importers(repo, token, path, source_globs) if DEFAULT_TEST_RE.search(i)]
        if tests:
            covering.update(tests)
        else:
            untested.append(path)
    return {"untested": untested, "covering_tests": sorted(covering), "notes": notes}


def analyze(ctx: Dict[str, Any], repo: str,
            source_globs: Optional[List[str]] = None,
            max_dependents: int = 50, max_files: int = 200) -> Dict[str, Any]:
    source_globs = source_globs or DEFAULT_SOURCE_GLOBS
    changed = [f for f in ctx.get("changed_files", []) if f]
    notes: List[str] = []
    if len(changed) > max_files:
        notes.append("changeset has {} files; mapping dependents for the first {} "
                     "(narrow the base or analyze one commit)".format(len(changed), max_files))
        changed = changed[:max_files]

    dependents: Dict[str, List[str]] = {}
    covering_tests = set()
    high_risk: List[str] = []

    for path in changed:
        if DEFAULT_TEST_RE.search(path):
            covering_tests.add(path)  # the change itself touches a test
        if HIGH_RISK_RE.search(path):
            high_risk.append(path)

        token = _module_token(path)
        imps = _importers(repo, token, path, source_globs)[:max_dependents]
        if imps:
            dependents[path] = imps
        for imp in imps:
            if DEFAULT_TEST_RE.search(imp):
                covering_tests.add(imp)

    # A changed file with many dependents is also high-risk even outside shared/.
    for path, imps in dependents.items():
        if len(imps) >= 10 and path not in high_risk:
            high_risk.append(path)

    ranked = sorted(dependents.items(), key=lambda kv: len(kv[1]), reverse=True)
    return {
        "changed_files": changed,
        "dependents": dict(ranked),
        "dependent_counts": {p: len(v) for p, v in ranked},
        "covering_tests": sorted(covering_tests),
        "high_risk": high_risk,
        "total_dependents": sum(len(v) for v in dependents.values()),
        "notes": notes,
    }
