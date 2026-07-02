"""RCA from a stack trace: parse the frames and locate the crashing lines.

Parses Python / JS / Node / Java / Go stack frames, resolves them to files tracked
in the repo, and hands the crashing ``(file, line)`` pairs to the normal bugfix
pipeline by synthesizing a diff whose removed ranges are those lines - so blame,
timeline, and risk run with no fix, PR, or test in hand.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Tuple

from . import _proc

# One regex per ecosystem. Java is tried before JS because both start with "at".
_PY = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+)(?:, in (?P<func>\S+))?')
_JAVA = re.compile(r'^\s*at (?P<func>[\w.$<>]+)\((?P<file>[^()\s:]+\.[A-Za-z]+):(?P<line>\d+)\)')
_JS = re.compile(r'^\s*at\s+(?:(?P<func>[^\s(]+)\s+)?\(?(?P<file>[^\s():]+):(?P<line>\d+):\d+\)?')
_GO = re.compile(r'^\s+(?P<file>/?[^\s:]+\.go):(?P<line>\d+)(?:\s|\+|$)')

_PATTERNS = [("python", _PY), ("java", _JAVA), ("js", _JS), ("go", _GO)]


def _parse_sentry(obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract frames from a Sentry event envelope (exception.values[].stacktrace.frames)."""
    frames: List[Dict[str, Any]] = []
    seen: set = set()
    for exc in obj.get("exception", {}).get("values", []):
        for fr in (exc.get("stacktrace") or {}).get("frames", []):
            filename = fr.get("filename") or fr.get("abs_path")
            lineno = fr.get("lineno")
            if not filename or not lineno:
                continue
            key = (filename, int(lineno))
            if key not in seen:
                seen.add(key)
                frames.append({"file": filename, "line": int(lineno),
                               "func": fr.get("function"), "lang": "python"})
    return frames


def parse(text: str) -> List[Dict[str, Any]]:
    """Return ordered, de-duplicated frames ``[{file, line, func, lang}]``."""
    # Try Sentry JSON event format before the regex path.
    try:
        obj = json.loads(text or "")
        frames = _parse_sentry(obj)
        if frames:
            return frames
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        pass

    frames = []
    seen: set = set()
    for line in (text or "").splitlines():
        for lang, rx in _PATTERNS:
            m = rx.match(line)
            if not m:
                continue
            gd = m.groupdict()
            key = (gd["file"], int(gd["line"]))
            if key not in seen:
                seen.add(key)
                frames.append({"file": gd["file"], "line": int(gd["line"]),
                               "func": gd.get("func"), "lang": lang})
            break
    return frames


def resolve_files(repo: str, frames: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Map frame file paths to repo-relative tracked files.

    Handles absolute paths, repo-relative paths, and (for Java) basenames.
    Returns ``(resolved, skipped)`` where resolved frames carry the tracked path.
    """
    out = _proc.git(["ls-files"], repo, check=False)
    tracked = [ln for ln in out.splitlines() if ln.strip()]
    by_base: Dict[str, List[str]] = {}
    for t in tracked:
        by_base.setdefault(os.path.basename(t), []).append(t)

    resolved: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for fr in frames:
        p = fr["file"].replace("\\", "/")
        while p.startswith("./"):           # strip leading ./ but preserve ../
            p = p[2:]
        cand = [t for t in tracked if p == t or p.endswith("/" + t)]
        if cand:
            match = max(cand, key=len)            # most specific suffix
        else:
            bl = by_base.get(os.path.basename(p), [])
            match = bl[0] if len(bl) == 1 else None  # basename only if unambiguous
        if match:
            resolved.append({**fr, "file": match})
        else:
            skipped.append(fr)
    return resolved, skipped
