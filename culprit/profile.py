"""Per-repo project profile: the engine's file-detection config.

``.culprit/profile.json`` has a machine-written ``detected`` block (regenerated
by ``culprit init``) and a human ``overrides`` block (never touched by the tool);
overrides win per-key at read time. Absent / malformed / too-new -> the engine
falls back to the hardcoded defaults, so a profile is always optional.

Stdlib only (json / os / re / fnmatch + _proc.git), Python 3.9+.
"""
from __future__ import annotations

import fnmatch
import json
import os
from typing import Any, Dict, List, Optional

from . import _proc
from .blast_radius import DEFAULT_SOURCE_GLOBS

PROFILE_PATH = os.path.join(".culprit", "profile.json")
VERSION = 1

_MIN_EXT_FILES = 5
_STALE_COMMITS = 200
# Extensions that are never import-graph source, even when frequent.
_NON_SOURCE_EXTS = {"md", "txt", "json", "yml", "yaml", "lock", "cfg", "ini",
                    "toml", "rst", "csv"}
# Test-file conventions to record (basename globs) and test dirs (path components).
_TEST_GLOBS = ["test_*.py", "*_test.py", "*_test.go", "*.spec.js", "*.spec.ts",
               "*.test.js", "*.test.ts", "*_spec.rb"]
_TEST_DIRS = ["tests/", "__tests__/", "cypress/"]


def _tracked_files(repo: str) -> List[str]:
    try:
        out = _proc.git(["ls-files"], repo, check=False)
    except _proc.ProcError:
        return []
    return [f for f in out.splitlines() if f.strip()]


def _detect_source_globs(files: List[str]) -> List[str]:
    """A ``*.<ext>`` glob for every extension on >= _MIN_EXT_FILES tracked files.

    Uniform threshold on all extensions (default-language or not): a lone
    vendored file cannot pull in its whole language, and a genuine language
    shows up. Denylisted data/config extensions never count. Empty result ->
    fall back to the full default set (never emit an empty glob list).
    """
    counts: Dict[str, int] = {}
    for f in files:
        ext = os.path.splitext(f)[1].lstrip(".").lower()
        if ext:
            counts[ext] = counts.get(ext, 0) + 1
    globs = sorted("*." + ext for ext, n in counts.items()
                   if n >= _MIN_EXT_FILES and ext not in _NON_SOURCE_EXTS)
    return globs or list(DEFAULT_SOURCE_GLOBS)


def _detect_test_globs(files: List[str]) -> List[str]:
    found: List[str] = []
    for conv in _TEST_GLOBS:
        if any(fnmatch.fnmatch(os.path.basename(f), conv) for f in files):
            found.append(conv)
    for d in _TEST_DIRS:
        name = d.rstrip("/")
        if any(name in f.split("/")[:-1] for f in files):
            found.append(d)
    return found


def detect(repo: str) -> Dict[str, Any]:
    """Build the ``detected`` block from the repo's tracked files."""
    files = _tracked_files(repo)
    try:
        head = _proc.git(["rev-parse", "HEAD"], repo, check=False).strip()
    except _proc.ProcError:
        head = ""
    return {"generated_head": head,
            "source_globs": _detect_source_globs(files),
            "test_globs": _detect_test_globs(files)}


def _is_str_list(v: Any) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _valid_block(block: Any) -> bool:
    """A profile block (detected/overrides) must be an object with well-typed fields.

    The profile is hand-editable, so a wrong-shaped block (e.g. a string where an
    object is expected, or a bare string instead of a glob list) must fail the
    whole load rather than crash an accessor or feed garbage globs downstream.
    """
    if not isinstance(block, dict):
        return False
    if "source_globs" in block and not _is_str_list(block["source_globs"]):
        return False
    if "test_globs" in block and not _is_str_list(block["test_globs"]):
        return False
    if "generated_head" in block and not isinstance(block["generated_head"], str):
        return False
    return True


def load(repo: str) -> Optional[Dict[str, Any]]:
    """Parse the profile; None if absent / unreadable / malformed / too-new."""
    try:
        with open(os.path.join(repo, PROFILE_PATH)) as fh:
            data = json.load(fh)
    except (IOError, OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    ver = data.get("version", VERSION)
    if not isinstance(ver, (int, float)) or isinstance(ver, bool) or ver > VERSION:
        return None
    for key in ("detected", "overrides"):
        if key in data and not _valid_block(data[key]):
            return None
    return data


def source_globs(repo: str) -> List[str]:
    """override -> detected -> DEFAULT_SOURCE_GLOBS (first non-empty list wins)."""
    data = load(repo)
    if data:
        for block in ("overrides", "detected"):
            g = (data.get(block) or {}).get("source_globs")
            if g:
                return list(g)
    return list(DEFAULT_SOURCE_GLOBS)


def write(repo: str, detected: Dict[str, Any]) -> None:
    """Write the profile, preserving any parseable ``overrides``."""
    existing = load(repo)
    overrides = (existing or {}).get("overrides") or {}
    os.makedirs(os.path.join(repo, ".culprit"), exist_ok=True)
    with open(os.path.join(repo, PROFILE_PATH), "w") as fh:
        json.dump({"version": VERSION, "detected": detected,
                   "overrides": overrides}, fh, indent=2)
        fh.write("\n")


def staleness_note(repo: str) -> Optional[str]:
    """Soft note when HEAD has advanced >= _STALE_COMMITS past generation."""
    data = load(repo)
    head_gen = (data or {}).get("detected", {}).get("generated_head") if data else None
    if not head_gen:
        return None
    try:
        _proc.git(["merge-base", "--is-ancestor", head_gen, "HEAD"], repo)  # raises if not
        out = _proc.git(["rev-list", "--count", "{}..HEAD".format(head_gen)], repo, check=False)
        n = int(out.strip() or "0")
    except (_proc.ProcError, ValueError):
        return None
    if n >= _STALE_COMMITS:
        return ("culprit profile generated {} commits ago; "
                "run `culprit init` to refresh".format(n))
    return None
