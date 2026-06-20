"""Line-evolution timeline: how the buggy lines became a bug, commit by commit.

For each line range the fix touched, ``git log -L<start>,<end>:<file>`` over the
base history gives every commit that ever modified those exact lines, oldest
first. We tag the earliest as ``origin``, the prime-suspect commit as
``suspect``, the rest as ``modified``, and append a synthetic ``fix`` step from
the fix diff. That ordered list is what the HTML report visualizes as a vertical
timeline (origin → … → the commit that broke it → the fix).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import _proc
from .suspect import _parse_hunks, _iso, _pr_for_commit

# Field/record delimiters that won't appear in commit metadata.
_SOH, _US, _STX = "\x01", "\x1f", "\x02"
_FMT = _SOH + "%H" + _US + "%an" + _US + "%aI" + _US + "%s" + _STX

_MAX_PR_LOOKUPS = 12  # _pr_for_commit is costly; bound total lookups per run


def _hunk_text(body: str) -> str:
    """Keep the unified-diff from the first @@ hunk header onward (drop the
    `diff --git` / `index` / `---` / `+++` preamble)."""
    lines = body.splitlines()
    out: List[str] = []
    started = False
    for ln in lines:
        if not started and ln.startswith("@@"):
            started = True
        if started:
            out.append(ln)
    return "\n".join(out).strip("\n")


def _file_block(diff: str, path: str) -> str:
    """Extract the fix's diff block for `path` from the full unified diff."""
    lines = (diff or "").splitlines()
    block: List[str] = []
    capturing = False
    for ln in lines:
        if ln.startswith("diff --git "):
            if capturing:
                break
            capturing = ("a/" + path in ln) or ("b/" + path in ln) or (path in ln)
            if capturing:
                block = []
            continue
        if capturing:
            block.append(ln)
    return _hunk_text("\n".join(block))


def _log_L(repo: str, start: int, end: int, path: str, base: str) -> List[Dict[str, Any]]:
    """Parse `git log -L<start>,<end>:<file> --reverse <base>` into ordered steps."""
    spec = "-L{},{}:{}".format(start, end, path)
    try:
        out = _proc.git(
            ["log", "--reverse", spec, "--format=" + _FMT, str(base)],
            repo, check=False,
        )
    except _proc.ProcError:
        return []
    steps: List[Dict[str, Any]] = []
    # Each commit block starts at _SOH; split and drop the empty leading chunk.
    for chunk in out.split(_SOH)[1:]:
        if _STX not in chunk:
            continue
        header, body = chunk.split(_STX, 1)
        fields = header.split(_US)
        if len(fields) < 4:
            continue
        sha, author, date_iso, subject = fields[0], fields[1], fields[2], fields[3]
        steps.append({
            "hash": sha.strip(),
            "short": sha.strip()[:10],
            "author": author,
            "date": date_iso,
            "subject": subject,
            "diff": _hunk_text(body),
        })
    return steps


def build_timeline(ctx: Dict[str, Any], repo: str, suspects: List[Dict[str, Any]],
                   max_ranges: int = 10, max_steps: int = 25) -> Dict[str, Any]:
    """Build per-range line-evolution timelines. Returns {ranges:[...], notes:[...]}."""
    base = ctx.get("base_sha") or ctx.get("base_ref")
    head_diff = ctx.get("diff") or ""
    notes: List[str] = []
    if not base:
        return {"ranges": [], "notes": ["no base revision; timeline unavailable"]}

    suspect_hashes = {s["hash"] for s in suspects} if suspects else set()
    prime = suspects[0]["hash"] if suspects else None

    parsed = _parse_hunks(head_diff)
    pairs: List[Tuple[str, int, int]] = []
    for f in parsed:
        path = f["old_path"]
        for (start, end) in (f["removed_ranges"] or f["context_ranges"]):
            pairs.append((path, start, end))
    if len(pairs) > max_ranges:
        notes.append("{} buggy ranges; showing the first {}".format(len(pairs), max_ranges))
        pairs = pairs[:max_ranges]

    pr_cache: Dict[str, Optional[int]] = {}
    pr_budget = [_MAX_PR_LOOKUPS]
    head = ctx.get("head_sha") or ctx.get("head_ref") or "HEAD"

    def pr_for(sha: str) -> Optional[int]:
        if sha in pr_cache:
            return pr_cache[sha]
        if pr_budget[0] <= 0:
            return None
        pr_budget[0] -= 1
        pr_cache[sha] = _pr_for_commit(repo, sha, str(head))
        return pr_cache[sha]

    ranges_out: List[Dict[str, Any]] = []
    for (path, start, end) in pairs:
        steps = _log_L(repo, start, end, path, str(base))
        if not steps:
            continue
        truncated = False
        if len(steps) > max_steps:
            steps = [steps[0]] + steps[-(max_steps - 1):]
            truncated = True

        # Only the PRIME suspect is the red "broke" node — one clear culprit.
        # The earliest commit is the origin; everything else is a modification.
        # (Other ranked suspects still appear in the suspect-set section.)
        has_prime = any(st["hash"] == prime for st in steps)
        for i, st in enumerate(steps):
            if st["hash"] == prime:
                st["role"] = "suspect"
            elif i == 0:
                st["role"] = "origin"
            else:
                st["role"] = "modified"
            # PR attribution: only spend the budget on the interesting steps.
            st["pr_number"] = pr_for(st["hash"]) if st["role"] in ("origin", "suspect") else None
        # If the prime suspect didn't touch this range, mark the latest pre-fix
        # commit as the suspect so every range still shows where it last changed.
        if not has_prime and len(steps) > 1:
            steps[-1]["role"] = "suspect"
            steps[-1]["pr_number"] = pr_for(steps[-1]["hash"])

        # Synthetic fix step from the head diff for this file.
        fix_diff = _file_block(head_diff, path)
        steps.append({
            "hash": ctx.get("head_sha") or "",
            "short": (ctx.get("head_sha") or "")[:10] or (ctx.get("head_ref") or "HEAD"),
            "author": None,
            "subject": ctx.get("title") or "THE FIX",
            "date": ctx.get("head_date"),
            "pr_number": ctx.get("pr_number"),
            "role": "fix",
            "diff": fix_diff,
        })

        ranges_out.append({
            "file": path,
            "range": [start, end],
            "truncated": truncated,
            "steps": steps,
        })

    return {"ranges": ranges_out, "notes": notes}
