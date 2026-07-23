"""Bugfix path: find the commit(s) that introduced the bug.

The insight: in a *fix* diff, the lines the fix removed or changed (the ``-``
lines) are the buggy lines. Blame those lines at the base revision and the
commit that last touched them is the prime suspect. For pure-addition fixes
(a guard added, nothing removed) we blame the surrounding context instead.

Produces a ranked suspect set; the reasoning layer turns it into the "why".
"""
from __future__ import annotations

import datetime
import difflib
import os
import re
from typing import Any, Dict, Iterable, List, Optional

from . import _proc

MAX_FILES = 150  # safety cap on how many changed files to blame in one run

# Commits that look like mechanical churn (refactors, reformats, renames)
# rather than logic changes. Used to (a) break ranking ties against them and
# (b) detect blame-absorbing commits worth chaining through.
#
# Deliberately excludes "move": commits that move code frequently ARE the
# bug's origin (the -M -C lesson) — benchmarking showed matching "move"
# demotes true root-cause commits.
_MECHANICAL_RE = re.compile(
    r"(?i)\b(refactor|reformat|restyle|style|indent|whitespace|typo|"
    r"clean\s?up|rename|reorder|simplify)\b")


def _ranked(entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rank suspect entries deterministically.

    Descending by blamed line count; on ties a mechanical-looking subject
    loses, then the newer commit wins (ISO date strings compare correctly;
    undated entries sort last). Two stable sorts: date pass first, then the
    primary key, so date order survives within equal primary keys.
    """
    ordered = sorted(entries, key=lambda e: e.get("date") or "", reverse=True)
    ordered.sort(key=lambda e: (-e["lines"],
                                1 if _MECHANICAL_RE.search(e.get("subject") or "") else 0))
    return ordered


_CHAIN_BUDGET = 12   # max chained blame invocations per find_suspects call
_CHAIN_DECAY = 0.5   # weight decay per hop for additively-added candidates


def _commit_diff(repo: str, sha: str, files: List[str]) -> str:
    """A commit's own diff restricted to `files` ('' on any failure)."""
    try:
        return _proc.git(["show", sha, "--format=", "--no-color", "--"] + list(files), repo)
    except _proc.ProcError:
        return ""


def _is_mechanical(subject: Optional[str], diff_text: str) -> bool:
    """True when a commit looks like refactor/reformat churn, not a logic change.

    Either signal suffices: a mechanical-looking subject, or removed/added
    lines that are near-identical after whitespace normalization.
    """
    if _MECHANICAL_RE.search(subject or ""):
        return True
    removed, added = [], []
    for line in diff_text.splitlines():
        if line.startswith("-") and not line.startswith("---"):
            removed.append(" ".join(line[1:].split()))
        elif line.startswith("+") and not line.startswith("+++"):
            added.append(" ".join(line[1:].split()))
    if not removed or not added:
        return False
    sm = difflib.SequenceMatcher(None, "\n".join(removed), "\n".join(added))
    return sm.ratio() >= 0.8


def _chain_from_diff(repo: str, sha: str, diff_text: str, hop: int,
                     budget: List[int]) -> List[Dict[str, Any]]:
    """Blame `sha`'s own removed lines at ``sha^``: the commits it edited over.

    Returns candidate entries shaped like ``agg`` values plus ``chained_from``
    and ``hop``. Pure-addition commits (no removed lines) are dead ends.
    ``budget`` is a 1-element list so the caller's budget decrements persist.
    """
    parent = sha + "^"
    out: Dict[str, Dict[str, Any]] = {}
    for f in _parse_hunks(diff_text):
        for (start, end) in f["removed_ranges"]:
            if budget[0] <= 0:
                return list(out.values())
            budget[0] -= 1
            for ln in _blame_lines(repo, parent, f["old_path"], start, end):
                csha = ln.get("sha")
                if not csha or csha == sha:
                    continue
                c = out.setdefault(csha, {
                    "hash": csha,
                    "author": ln.get("author"),
                    "date": _iso(ln.get("author_time")),
                    "subject": ln.get("summary"),
                    "lines": 0,
                    "files": set(),
                    "chained_from": sha,
                    "hop": hop,
                })
                c["lines"] += 1
                c["files"].add(f["old_path"])
    return list(out.values())


def _common_depth(paths: List[str]) -> int:
    """Return how many leading path components all paths share."""
    if not paths:
        return 0
    parts_list = [p.replace("\\", "/").split("/") for p in paths]
    depth = 0
    for level in zip(*parts_list):
        if len(set(level)) == 1:
            depth += 1
        else:
            break
    return depth


def _cluster_key(path: str, depth: int) -> str:
    parts = path.replace("\\", "/").split("/")
    return parts[depth] if depth < len(parts) else path


def _detect_multi_cluster(parsed: List[Dict[str, Any]]) -> Optional[str]:
    """Return a warning note when the diff's files span unrelated subsystems.

    Detects this by finding the common path prefix of all changed files, then
    grouping by the next path component. Two or more distinct groups means the
    branch likely contains multiple unrelated changes, which can cause the blame
    to land on the wrong prime suspect.
    """
    paths = [f["old_path"] for f in parsed if f.get("old_path")]
    if len(paths) < 2:
        return None
    depth = _common_depth(paths)
    groups: Dict[str, List[str]] = {}
    for p in paths:
        key = _cluster_key(p, depth)
        groups.setdefault(key, []).append(p)
    if len(groups) < 2:
        return None
    cluster_desc = "; ".join(
        "{} ({})".format(k, ", ".join(v[:2]) + ("…" if len(v) > 2 else ""))
        for k, v in list(groups.items())[:4]
    )
    return (
        "the diff spans {} distinct subsystem(s) ({}); the branch may contain multiple "
        "unrelated changes — the prime suspect may belong to the wrong cluster. "
        "Consider running `--last` on individual commits for a focused analysis.".format(
            len(groups), cluster_desc
        )
    )

_DIFF_GIT = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_OLD_PATH = re.compile(r"^--- (?:a/)?(.+)$")
_NEW_PATH = re.compile(r"^\+\+\+ (?:b/)?(.+)$")
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _parse_hunks(diff: str) -> List[Dict[str, Any]]:
    """Return [{old_path, removed_ranges, context_ranges}] per file.

    ``removed_ranges`` are (start, end) line ranges in the OLD file covering
    runs of removed lines. ``context_ranges`` cover the old-side hunk extent,
    used as a fallback for pure-addition hunks.
    """
    files: Dict[str, Dict[str, Any]] = {}
    old_path: Optional[str] = None
    old_lineno = 0
    run_start: Optional[int] = None
    cur: Optional[Dict[str, Any]] = None

    def close_run(end_inclusive: int):
        nonlocal run_start
        if run_start is not None and cur is not None:
            cur["removed_ranges"].append((run_start, end_inclusive))
            run_start = None

    for line in diff.splitlines():
        m = _DIFF_GIT.match(line)
        if m:
            close_run(old_lineno - 1)
            old_path = m.group(1)
            cur = files.setdefault(old_path, {"old_path": old_path,
                                              "removed_ranges": [], "context_ranges": []})
            continue
        m = _OLD_PATH.match(line)
        if m and cur is not None:
            if m.group(1) != "/dev/null":
                cur["old_path"] = m.group(1)
                old_path = m.group(1)
            continue
        if _NEW_PATH.match(line):
            continue
        m = _HUNK.match(line)
        if m:
            close_run(old_lineno - 1)
            old_start = int(m.group(1))
            old_count = int(m.group(2) or "1")
            old_lineno = old_start
            if cur is not None and old_count > 0:
                cur["context_ranges"].append((old_start, old_start + old_count - 1))
            continue
        if cur is None:
            continue
        if line.startswith("-") and not line.startswith("---"):
            if run_start is None:
                run_start = old_lineno
            old_lineno += 1
        elif line.startswith("+") and not line.startswith("+++"):
            # added line: belongs to new file only, doesn't advance old_lineno
            pass
        else:
            # context line (or other): a removed run ends here
            close_run(old_lineno - 1)
            old_lineno += 1

    close_run(old_lineno - 1)
    # Keep files that actually changed something we can blame.
    return [f for f in files.values() if f["removed_ranges"] or f["context_ranges"]]


def _blame_lines(repo: str, rev: str, path: str, start: int, end: int) -> List[Dict[str, str]]:
    """Return per-line blame info for path@rev over [start, end].

    Deliberately no -M/-C: they blame whoever wrote moved content, but when a
    bug is introduced by a move/refactor the introducing commit is the mover —
    benchmarking against Fixes:-trailer ground truth showed -M -C reduces
    top-1 accuracy. A repo's ``.git-blame-ignore-revs`` (mass-reformat commits)
    is honored when present; if git rejects the file (bad content, git < 2.23)
    fall back to plain blame.
    """
    base_args = ["blame", "--line-porcelain",
                 "-L", "{},{}".format(start, end), rev, "--", path]
    attempts = []
    if os.path.exists(os.path.join(repo, ".git-blame-ignore-revs")):
        attempts.append(base_args[:1] +
                        ["--ignore-revs-file", ".git-blame-ignore-revs"] +
                        base_args[1:])
    attempts.append(base_args)
    out = None
    for args in attempts:
        try:
            out = _proc.git(args, repo)
            break
        except _proc.ProcError:
            continue
    if out is None:
        return []
    lines: List[Dict[str, str]] = []
    cur: Dict[str, str] = {}
    for raw in out.splitlines():
        m = re.match(r"^([0-9a-f]{7,40}) \d+ \d+", raw)
        if m:
            if cur:
                lines.append(cur)
            cur = {"sha": m.group(1)}
        elif raw.startswith("author "):
            cur["author"] = raw[len("author "):]
        elif raw.startswith("author-time "):
            cur["author_time"] = raw[len("author-time "):]
        elif raw.startswith("summary "):
            cur["summary"] = raw[len("summary "):]
    if cur:
        lines.append(cur)
    return lines


def _iso(epoch: Optional[str]) -> Optional[str]:
    if not epoch:
        return None
    try:
        return datetime.datetime.utcfromtimestamp(int(epoch)).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return None


def _is_ancestor(repo: str, sha: str, ref: str) -> bool:
    """True if `sha` is reachable from `ref` (i.e. already in the target history)."""
    try:
        _proc.git(["merge-base", "--is-ancestor", sha, ref], repo)  # exit 0 = ancestor
        return True
    except _proc.ProcError:
        return False


def _pr_for_commit(repo: str, sha: str, upto: str) -> Optional[int]:
    """Best-effort: find the 'Merge pull request #N' that brought sha in."""
    try:
        out = _proc.git(
            ["log", "--merges", "--ancestry-path", "--reverse", "--pretty=%s",
             "{}..{}".format(sha, upto)],
            repo, check=False,
        )
    except _proc.ProcError:
        return None
    for subj in out.splitlines():
        m = re.search(r"Merge pull request #(\d+)", subj)
        if m:
            return int(m.group(1))
    return None


def find_suspects(ctx: Dict[str, Any], repo: str, max_suspects: int = 5,
                  trunk: Optional[str] = None, chain: str = "additive") -> Dict[str, Any]:
    """Blame the buggy lines at base and rank the introducing commits.

    ``trunk`` is the branch this work targets (e.g. ``origin/main``). When given,
    each suspect is tagged ``in_base`` - whether it already exists in the target
    history. A suspect that is NOT in the trunk is a commit on the current branch
    (part of this very change), so it is *not* a real "when it broke": the report
    flags that and points the user at their target branch instead.

    ``chain`` looks one blame hop past the top suspects, whose own edits may
    have absorbed blame from the true introducing commit: ``"additive"`` adds
    hop-back candidates below the primaries (never dethrones); ``"passthrough"``
    additionally transfers blame through absorbers detected as mechanical
    (refactor/reformat), which can change the prime suspect. The "additive" default
    was chosen by benchmark: see benchmarks/ (50 Fixes:-trailer ground-truth cases;
    numbers in this commit's message).
    """
    base = ctx.get("base_sha") or ctx.get("base_ref")
    head = ctx.get("head_sha") or ctx.get("head_ref") or "HEAD"
    notes: List[str] = []
    if not base or _proc.git(["rev-parse", "--verify", str(base)], repo, check=False).strip() == "":
        return {"suspects": [], "blamed_lines": 0, "trunk": trunk,
                "origin_on_branch": False,
                "notes": ["base revision not resolvable locally; "
                          "fetch the base branch to enable suspect blame"]}

    # Aggregate blame across all buggy line ranges. Cap the work so a huge
    # changeset (e.g. a branch far ahead of a stale base) can't blow up.
    agg: Dict[str, Dict[str, Any]] = {}
    blamed_lines = 0
    parsed = _parse_hunks(ctx.get("diff") or "")
    if len(parsed) > MAX_FILES:
        notes.append("changeset has {} files; blaming only the first {} "
                     "(narrow the base or analyze one commit)".format(len(parsed), MAX_FILES))
        parsed = parsed[:MAX_FILES]
    for f in parsed:
        path = f["old_path"]
        ranges = f["removed_ranges"] or f["context_ranges"]
        if not f["removed_ranges"] and f["context_ranges"]:
            notes.append("{}: pure-addition fix; blaming surrounding context".format(path))
        for (start, end) in ranges:
            for ln in _blame_lines(repo, str(base), path, start, end):
                sha = ln.get("sha")
                if not sha:
                    continue
                blamed_lines += 1
                entry = agg.setdefault(sha, {
                    "hash": sha,
                    "author": ln.get("author"),
                    "date": _iso(ln.get("author_time")),
                    "subject": ln.get("summary"),
                    "lines": 0,
                    "files": set(),
                })
                entry["lines"] += 1
                entry["files"].add(path)

    # Detect multi-cluster contamination before ranking: warn when the changed
    # files span unrelated subsystems, which can mislead the blame ranking.
    cluster_note = _detect_multi_cluster(parsed)
    if cluster_note:
        notes.append(cluster_note)

    ordered = _ranked(agg.values())

    # Chained blame: the top suspects' own edits may have absorbed blame from
    # the true introducing commit - look one hop past them.
    extras: Dict[str, Dict[str, Any]] = {}
    if chain in ("additive", "passthrough") and ordered:
        budget = [_CHAIN_BUDGET]
        transferred = False
        for entry in ordered[:3]:
            files = sorted(entry["files"])
            diff_text = _commit_diff(repo, entry["hash"], files)
            if not diff_text:
                continue
            cands = _chain_from_diff(repo, entry["hash"], diff_text, 1, budget)
            if not cands:
                continue
            if chain == "passthrough" and _is_mechanical(entry.get("subject"), diff_text):
                # Blame passes through the mechanical absorber at full weight.
                entry["lines"] = max(0, entry["lines"] - sum(c["lines"] for c in cands))
                transferred = True
                for c in cands:
                    tgt = agg.get(c["hash"])
                    if tgt is not None:
                        tgt["lines"] += c["lines"]
                        tgt["files"] |= c["files"]
                    else:
                        # Promoted to a full-weight primary: shed the chained
                        # metadata so the report treats it as a direct hit, not
                        # a hop-back guess.
                        c.pop("chained_from", None)
                        c.pop("hop", None)
                        agg[c["hash"]] = c
                # Hop 2 (added to the additive tier) through the strongest hop-1 candidate
                # when it, too, is mechanical.
                best = max(cands, key=lambda c: c["lines"])
                bdiff = _commit_diff(repo, best["hash"], sorted(best["files"]))
                if bdiff and _is_mechanical(best.get("subject"), bdiff):
                    for c2 in _chain_from_diff(repo, best["hash"], bdiff, 2, budget):
                        if c2["hash"] not in agg and c2["hash"] not in extras:
                            extras[c2["hash"]] = c2
            else:
                for c in cands:
                    if c["hash"] in agg:
                        continue  # already a primary suspect - leave it alone
                    e = extras.setdefault(c["hash"], c)
                    if e is not c:
                        e["lines"] += c["lines"]
                        e["files"] |= c["files"]
        if transferred:
            ordered = _ranked(agg.values())

    suspects = ordered[:max_suspects]
    if len(suspects) < max_suspects and extras:
        tail = sorted(extras.values(), key=lambda e: e.get("date") or "", reverse=True)
        tail.sort(key=lambda e: -(e["lines"] * _CHAIN_DECAY ** e["hop"]))
        suspects.extend(tail[:max_suspects - len(suspects)])

    for s in suspects:
        s["files"] = sorted(s["files"])
        s["pr_number"] = _pr_for_commit(repo, s["hash"], str(head))
        s["short"] = s["hash"][:10]
        s["weight"] = (None if s.get("chained_from")
                       else round(s["lines"] / blamed_lines, 2) if blamed_lines else 0.0)
        s["in_base"] = _is_ancestor(repo, s["hash"], trunk) if trunk else None

    # The prime suspect being a branch-local commit means the blame landed on this
    # change's own work, not the bug's origin in the target history.
    origin_on_branch = bool(suspects) and trunk is not None and suspects[0].get("in_base") is False
    if origin_on_branch:
        notes.append("the blamed commit is on the current branch (part of this change), not in "
                     "'{}' - analyze against your target branch to find the bug's origin".format(trunk))

    return {"suspects": suspects, "blamed_lines": blamed_lines, "notes": notes,
            "trunk": trunk, "origin_on_branch": origin_on_branch}
