"""Fix completeness: does the fix address the root cause, or just one symptom?

A fix that patches one call site of a broken helper but misses three others is a
partial fix. This module extracts the symbols the fix changed (the enclosing
functions from the hunk headers, plus called names on the changed lines), finds
other places in the tree that reference them but weren't touched, and flags
whether the change ships a test or merely reverts the introducing commit.

All heuristic and read-only - it reuses the POSIX-safe ``git grep`` style and the
source/test conventions from ``blast_radius``.
"""
from __future__ import annotations

import fnmatch
import os
import re
from typing import Any, Dict, List

from . import _proc
from .blast_radius import DEFAULT_SOURCE_GLOBS, DEFAULT_TEST_RE

# Identify which file a hunk belongs to, so symbol extraction skips
# markdown/config noise and only looks at source files.
_DIFF_FILE = re.compile(r"^diff --git a/(.+?) b/")
# git puts the enclosing function/section heading after the second @@ on a hunk.
_HUNK_HEADING = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@\s*(.*)$")
# A definition or signature - `def name(`, `class name`, or `name(`. This keeps
# prose (a docstring used as the hunk heading) from masquerading as a symbol.
_SIG = re.compile(
    r"\b(?:def|class|function|func|fn|interface|struct|type|sub)\s+([A-Za-z_][A-Za-z0-9_]{2,})"
    r"|([A-Za-z_][A-Za-z0-9_]{2,})\s*\(")
# Just the `def name` / `class name` form - used on context lines, where a bare
# `name(` would be an ordinary call rather than the enclosing definition.
_DEF = re.compile(
    r"\b(?:def|class|function|func|fn|interface|struct|type|sub)\s+([A-Za-z_][A-Za-z0-9_]{2,})")
# A call-ish use: `name(` on a changed line.
_CALL = re.compile(r"([A-Za-z_][A-Za-z0-9_]{2,})\s*\(")
_REVERT = re.compile(r"(?i)^\s*revert\b")
# Common keywords across languages - never treat these as a "symbol".
_KEYWORDS = {
    "def", "function", "func", "class", "return", "const", "let", "var", "public",
    "private", "protected", "static", "void", "async", "await", "export", "import",
    "from", "self", "this", "new", "type", "interface", "struct", "enum", "if",
    "else", "for", "while", "switch", "case", "true", "false", "null", "none",
}

_MAX_SYMBOLS = 5
_MAX_REFS = 20


def _is_source(path: str) -> bool:
    """A code file (not markdown/config/test) - the only place symbols make sense."""
    base = os.path.basename(path)
    return (any(fnmatch.fnmatch(base, g) for g in DEFAULT_SOURCE_GLOBS)
            and not DEFAULT_TEST_RE.search(path))


def _symbols_from_diff(diff: str) -> List[str]:
    """Best-effort: the function/symbol names the fix changed, source files only.

    Prefers the enclosing-function names from hunk headings (so "other call sites"
    means other callers of the function the fix lives in); falls back to names
    that are *called* on the changed lines. Hunks in non-source files (CHANGELOG,
    config, docs) are skipped so their prose doesn't masquerade as symbols.
    """
    headings: List[str] = []
    called: List[str] = []
    cur_source = False
    for line in (diff or "").splitlines():
        dm = _DIFF_FILE.match(line)
        if dm:
            cur_source = _is_source(dm.group(1))
            continue
        if not cur_source:
            continue
        m = _HUNK_HEADING.match(line)
        if m:
            for sm in _SIG.finditer(m.group(1)):
                name = sm.group(1) or sm.group(2)
                if name and name not in _KEYWORDS and name not in headings:
                    headings.append(name)
            continue
        if line[:1] == " ":
            # context line: the enclosing definition (the def/class the fix lives in)
            for dm2 in _DEF.finditer(line):
                name = dm2.group(1)
                if name and name not in _KEYWORDS and name not in headings:
                    headings.append(name)
        elif line[:1] in ("+", "-") and line[:3] not in ("+++", "---"):
            for cm in _CALL.finditer(line[1:]):
                name = cm.group(1)
                if name not in _KEYWORDS and name not in called:
                    called.append(name)
    out = headings + [c for c in called if c not in headings]
    return out[:_MAX_SYMBOLS]


def _refs(repo: str, token: str) -> List[str]:
    """Files referencing ``token`` as a whole word (any usage, not just imports).

    Same POSIX-safe ``git grep -E`` style as ``blast_radius._importers`` (git grep
    has no \\w / \\b, so word boundaries are spelled ``[^A-Za-z0-9_]``), but matches
    the bare symbol anywhere rather than only in an import statement.
    """
    if not token:
        return []
    tok = re.escape(token)
    pat = r"(^|[^A-Za-z0-9_]){}([^A-Za-z0-9_]|$)".format(tok)
    args = ["grep", "-l", "-I", "-E", "-e", pat, "--"] + DEFAULT_SOURCE_GLOBS
    out = _proc.git(args, repo, check=False)
    return [f for f in out.splitlines() if f.strip()]


def _diff_lines(diff: str, sign: str) -> set:
    """Stripped content of added (`+`) or removed (`-`) lines in a unified diff."""
    out = set()
    for line in (diff or "").splitlines():
        if line.startswith(sign) and not line.startswith(sign * 3):
            s = line[1:].strip()
            if s:
                out.add(s)
    return out


def assess(ctx: Dict[str, Any], repo: str, suspects: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return ``{symbols, other_call_sites, untouched_count, adds_test, is_revert, notes}``."""
    diff = ctx.get("diff") or ""
    changed = set(ctx.get("changed_files") or [])
    notes: List[str] = []

    # Other references to the changed symbols that the fix did not touch.
    symbols = _symbols_from_diff(diff)
    other_call_sites: Dict[str, List[str]] = {}
    untouched = set()
    for sym in symbols:
        refs = _refs(repo, sym)
        outside = [f for f in refs if f not in changed and not DEFAULT_TEST_RE.search(f)][:_MAX_REFS]
        if outside:
            other_call_sites[sym] = outside
            untouched.update(outside)

    # Did the fix ship a test?
    adds_test = any(DEFAULT_TEST_RE.search(f) for f in changed)

    # Is the fix effectively a revert of the introducing change?
    is_revert = bool(_REVERT.match(ctx.get("title") or ""))
    if not is_revert:
        for c in ctx.get("commits", []):
            if _REVERT.match(c.get("subject") or ""):
                is_revert = True
                break
    if not is_revert and suspects:
        ssha = suspects[0].get("hash")
        if ssha:
            sus_diff = _proc.git(["show", "--format=", ssha], repo, check=False)
            sus_removed = _diff_lines(sus_diff, "-")
            fix_added = _diff_lines(diff, "+")
            if fix_added and sus_removed:
                common = fix_added & sus_removed
                if len(common) >= max(1, (len(fix_added) + 1) // 2):
                    is_revert = True
                    notes.append("the fix restores lines the suspect commit removed")

    return {
        "symbols": symbols,
        "other_call_sites": other_call_sites,
        "untouched_count": len(untouched),
        "adds_test": adds_test,
        "is_revert": is_revert,
        "notes": notes,
    }
