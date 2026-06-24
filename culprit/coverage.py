"""Optional coverage precision: which *changed lines* are actually uncovered.

The default test-gap is an import heuristic ("this file has no test that imports
it"). Given an lcov or Cobertura report via ``--coverage``, this parses the per-line
coverage, maps it to the lines this change added, and reports exactly which changed
lines no test exercises - feeding the risk score.

Aggregate coverage is suite-level, so it tells us *whether* a line is covered, not
*which test* covers it; this refines the gap, not per-test selection.
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Set

_DIFF_GIT = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_NEW_PATH = re.compile(r"^\+\+\+ (?:b/)?(.+)$")
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _parse_lcov(text: str) -> Dict[str, Dict[str, Set[int]]]:
    cov: Dict[str, Dict[str, Set[int]]] = {}
    cur = None
    for line in text.splitlines():
        if line.startswith("SF:"):
            cur = cov.setdefault(line[3:].strip(), {"lines": set(), "covered": set()})
        elif line.startswith("DA:") and cur is not None:
            try:
                ln, hits = line[3:].split(",")[:2]
                n = int(ln)
            except ValueError:
                continue
            cur["lines"].add(n)
            if hits.strip() not in ("0", ""):
                cur["covered"].add(n)
        elif line.startswith("end_of_record"):
            cur = None
    return cov


def _parse_cobertura(text: str) -> Dict[str, Dict[str, Set[int]]]:
    cov: Dict[str, Dict[str, Set[int]]] = {}
    # Refuse DTDs / entity declarations (billion-laughs / external-entity attacks)
    # before handing the document to ElementTree. No external dependency needed.
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise ValueError("refusing to parse XML with a DTD or entity declaration")
    root = ET.fromstring(text)
    for cls in root.iter("class"):
        fn = cls.get("filename")
        if not fn:
            continue
        entry = cov.setdefault(fn, {"lines": set(), "covered": set()})
        for ln in cls.iter("line"):
            try:
                n = int(ln.get("number"))
            except (TypeError, ValueError):
                continue
            entry["lines"].add(n)
            if (ln.get("hits") or "0").strip() not in ("0", ""):
                entry["covered"].add(n)
    return cov


def parse(path: str) -> Dict[str, Dict[str, Set[int]]]:
    """Parse an lcov or Cobertura file -> ``{file: {lines, covered}}`` (best-effort)."""
    with open(os.path.expanduser(path), encoding="utf-8") as fh:
        text = fh.read()
    stripped = text.lstrip()
    if stripped.startswith("<?xml") or stripped.startswith("<coverage"):
        return _parse_cobertura(text)
    return _parse_lcov(text)


def _added_lines(diff: str) -> Dict[str, Set[int]]:
    """New-side line numbers added by the diff, per (new) file path."""
    out: Dict[str, Set[int]] = {}
    path = None
    new_lineno = 0
    for line in (diff or "").splitlines():
        m = _DIFF_GIT.match(line)
        if m:
            path = m.group(2)
            continue
        m = _NEW_PATH.match(line)
        if m:
            if m.group(1) != "/dev/null":
                path = m.group(1)
            continue
        m = _HUNK.match(line)
        if m:
            new_lineno = int(m.group(1))
            continue
        if path is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            out.setdefault(path, set()).add(new_lineno)
            new_lineno += 1
        elif line.startswith("-") and not line.startswith("---"):
            pass
        else:
            new_lineno += 1
    return out


def _match(cov: Dict[str, Any], path: str):
    """Find the coverage entry for a repo path (exact, then suffix, then basename)."""
    if path in cov:
        return cov[path]
    cands = [f for f in cov if f == path or f.endswith("/" + path) or path.endswith("/" + f)]
    if cands:
        return cov[max(cands, key=len)]
    base = os.path.basename(path)
    by_base = [f for f in cov if os.path.basename(f) == base]
    return cov[by_base[0]] if len(by_base) == 1 else None


def analyze(diff: str, cov: Dict[str, Dict[str, Set[int]]]) -> Dict[str, Any]:
    """Return ``{uncovered: {file: [lines]}, files_with_uncovered, checked_files, notes}``."""
    added = _added_lines(diff)
    uncovered: Dict[str, List[int]] = {}
    checked = 0
    notes: List[str] = []
    for path, lines in added.items():
        entry = _match(cov, path)
        if entry is None:
            continue
        checked += 1
        miss = sorted(ln for ln in lines if ln in entry["lines"] and ln not in entry["covered"])
        if miss:
            uncovered[path] = miss
    if added and checked == 0:
        notes.append("coverage report did not match any changed files (path mismatch?)")
    return {"uncovered": uncovered, "files_with_uncovered": len(uncovered),
            "checked_files": checked, "notes": notes}
