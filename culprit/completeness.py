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
from typing import Any, Dict, List, Optional

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

# Names that must never be treated as a "symbol" even when the repo defines one:
# language builtins, ubiquitous container/str methods, and common test/log noise.
# The repo-defined check (_is_defined) is the real filter; this list only catches
# project methods that happen to share a builtin-like name (e.g. `def get`).
_NON_SYMBOLS = frozenset({
    "get", "set", "any", "all", "len", "print", "str", "int", "float", "bool",
    "list", "dict", "tuple", "open", "range", "enumerate", "zip", "map", "filter",
    "sorted", "reversed", "min", "max", "sum", "abs", "round", "isinstance",
    "issubclass", "hasattr", "getattr", "setattr", "format", "join", "split",
    "strip", "rstrip", "lstrip", "replace", "startswith", "endswith", "append",
    "extend", "insert", "pop", "keys", "values", "items", "setdefault", "update",
    "add", "remove", "super", "repr", "type", "vars", "dir", "next", "iter",
    "callable",
    "require", "assert", "expect", "describe", "it", "test", "console", "log",
    "printf", "println", "new",
})

_MAX_SYMBOLS = 5
_MAX_REFS = 20
# A symbol referenced across more than this many files is core infrastructure,
# not a helper the fix might have half-updated - flagging dozens of call sites is
# noise, so we skip it (and note it) rather than cry wolf.
_COMMON_REFS = 20


def _is_source(path: str, source_globs: List[str]) -> bool:
    """A code file (not markdown/config/test) - the only place symbols make sense."""
    base = os.path.basename(path)
    return (any(fnmatch.fnmatch(base, g) for g in source_globs)
            and not DEFAULT_TEST_RE.search(path))


def _symbols_from_diff(diff: str, source_globs: List[str]) -> List[str]:
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
            cur_source = _is_source(dm.group(1), source_globs)
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
    return headings + [c for c in called if c not in headings]


def _refs(repo: str, token: str, source_globs: List[str]) -> List[str]:
    """Files referencing ``token`` as a whole word (any usage, not just imports).

    Same POSIX-safe ``git grep -E`` style as ``blast_radius._importers`` (git grep
    has no \\w / \\b, so word boundaries are spelled ``[^A-Za-z0-9_]``), but matches
    the bare symbol anywhere rather than only in an import statement.
    """
    if not token:
        return []
    tok = re.escape(token)
    pat = r"(^|[^A-Za-z0-9_]){}([^A-Za-z0-9_]|$)".format(tok)
    args = ["grep", "-l", "-I", "-E", "-e", pat, "--"] + source_globs
    out = _proc.git(args, repo, check=False)
    return [f for f in out.splitlines() if f.strip()]


def _is_defined(repo: str, token: str, source_globs: List[str]) -> bool:
    """True if the repo defines ``token`` in a source file.

    Two definition shapes, both POSIX-safe ``git grep -E`` (git grep has no \\b,
    so boundaries are spelled out), same style as ``_refs``:

    1. Keyword-led: ``def``/``class``/``func``/``struct``/... ``token`` - Python,
       JS, Go, Rust, Ruby, TypeScript.
    2. Brace-language signature whose body opens on the same line:
       ``int token(args) {``, ``public void token() {``, ``bool token() const {``
       - Java, C#, C/C++, and object-method shorthand, none of which carry a
       leading def keyword. The arg list and the run up to ``{`` both exclude
       ``)`` and ``{``, so an ordinary call like ``if (token()) {`` cannot pass
       for a definition (its inner ``)`` stops the match short of the brace).

    Restricting symbols to names the repo actually defines drops builtins and
    library calls the fix merely *uses* (``isinstance``, ``ArgumentParser``, ...).
    """
    if not token:
        return False
    tok = re.escape(token)
    keyword = (r"(def|class|function|func|fn|interface|struct|type|sub)"
               r"[[:space:]]+{}([^A-Za-z0-9_]|$)".format(tok))
    signature = tok + r"[[:space:]]*\([^{}();]*\)[A-Za-z_[:space:]]*\{"
    args = ["grep", "-l", "-I", "-E", "-e", keyword, "-e", signature, "--"] + source_globs
    out = _proc.git(args, repo, check=False)
    return bool(out.strip())


def _diff_lines(diff: str, sign: str) -> set:
    """Stripped content of added (`+`) or removed (`-`) lines in a unified diff."""
    out = set()
    for line in (diff or "").splitlines():
        if line.startswith(sign) and not line.startswith(sign * 3):
            s = line[1:].strip()
            if s:
                out.add(s)
    return out


def assess(ctx: Dict[str, Any], repo: str, suspects: List[Dict[str, Any]],
           source_globs: Optional[List[str]] = None) -> Dict[str, Any]:
    """Return ``{symbols, other_call_sites, untouched_count, skipped_symbols,
    adds_test, is_revert, notes}``.

    ``skipped_symbols`` are symbols too widely referenced to enumerate; their call
    sites were deliberately not checked, so a caller must not read a zero
    ``untouched_count`` as proof of completeness when this list is non-empty.
    """
    globs = source_globs or DEFAULT_SOURCE_GLOBS
    diff = ctx.get("diff") or ""
    changed = set(ctx.get("changed_files") or [])
    notes: List[str] = []

    # Other references to the changed symbols that the fix did not touch.
    # Keep only names the repo actually defines and that aren't builtins/methods,
    # so "other call sites" reflects real project symbols, not `get`/`isinstance`.
    symbols: List[str] = []
    for cand in _symbols_from_diff(diff, globs):
        if cand.lower() in _NON_SYMBOLS or not _is_defined(repo, cand, globs):
            continue
        symbols.append(cand)
        if len(symbols) >= _MAX_SYMBOLS:  # stop grepping once the budget is full
            break
    other_call_sites: Dict[str, List[str]] = {}
    untouched = set()
    common_symbols: List[str] = []
    for sym in symbols:
        refs = _refs(repo, sym, globs)
        outside = [f for f in refs if f not in changed and not DEFAULT_TEST_RE.search(f)]
        if len(outside) > _COMMON_REFS:
            common_symbols.append(sym)   # ubiquitous: not a fix-completeness signal
            continue
        if outside:
            other_call_sites[sym] = outside[:_MAX_REFS]
            untouched.update(outside[:_MAX_REFS])
    if common_symbols:
        notes.append("skipped {} widely-referenced symbol(s) ({}); used across the "
                     "codebase, not a fix-completeness signal".format(
                         len(common_symbols), ", ".join(common_symbols)))

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
        # Symbols too widely referenced to enumerate: their call sites were NOT
        # checked, so a zero untouched_count here does not prove completeness.
        "skipped_symbols": common_symbols,
        "adds_test": adds_test,
        "is_revert": is_revert,
        "notes": notes,
    }
