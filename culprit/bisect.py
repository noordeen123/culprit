"""Optional `git bisect` confirmation - prove "when it broke".

culprit's suspect set is a static heuristic (blame the fix's lines at base). When
the user supplies a repro/test command, we run a *real* `git bisect` to find the
first commit where the test fails, and cross-check it against the heuristic
suspect. Agreement turns "likely introduced by" into "confirmed by bisect."

`git bisect` checks out commits and moves HEAD, which would break culprit's
read-only guarantee, so it runs entirely inside a throwaway git worktree (shares
the object DB, torn down in a finally). The user's checkout, HEAD, and index are
never touched.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from typing import Any, Dict, Optional

from . import _proc
from .suspect import _iso, _pr_for_commit  # noqa: F401  (_iso kept for parity)

_FIRST_BAD = re.compile(r"^([0-9a-f]{7,40}) is the first bad commit", re.M)


def _commit_meta(repo: str, sha: str) -> Dict[str, Any]:
    out = _proc.git(
        ["show", "-s", "--format=%H%x1f%an%x1f%aI%x1f%s", sha], repo, check=False
    ).strip()
    parts = out.split("\x1f")
    if len(parts) < 4:
        return {"hash": sha, "short": sha[:10]}
    return {"hash": parts[0], "short": parts[0][:10], "author": parts[1],
            "date": parts[2], "subject": parts[3]}


def run_bisect(repo: str, good: Optional[str], bad: Optional[str], cmd: str,
               head_for_pr: str = "HEAD") -> Dict[str, Any]:
    """Bisect `good..bad` with `cmd` in a throwaway worktree; return the first-bad commit.

    `cmd` must exit 0 when the bug is ABSENT (good) and non-zero when PRESENT (bad);
    exit 125 marks an untestable commit to skip. Returns a dict that always carries
    `error` (None on success) so callers can render gracefully.
    """
    base_result = {"good": good, "bad": bad, "first_bad": None,
                   "agrees_with_suspect": None, "log": "", "error": None}

    if not bad:
        return dict(base_result, error="no 'bad' revision (base) to bisect from")
    if not good:
        return dict(base_result, error="no 'good' revision - pass --good <ref> "
                                       "(a commit/tag from before the bug)")

    bad_sha = _proc.git(["rev-parse", "--verify", str(bad)], repo, check=False).strip()
    good_sha = _proc.git(["rev-parse", "--verify", str(good)], repo, check=False).strip()
    if not bad_sha or not good_sha:
        return dict(base_result, error="could not resolve good/bad revisions locally")

    parent = tempfile.mkdtemp(prefix="culprit-bisect-")
    wt = os.path.join(parent, "wt")   # worktree path must not pre-exist
    try:
        add = _proc.run(["git", "-C", repo, "worktree", "add", "--detach", wt, bad_sha],
                        check=False)
        if not os.path.exists(os.path.join(wt, ".git")):
            return dict(base_result, error="could not create a bisect worktree: " + add.strip())

        def g(*args, check=False):
            return _proc.run(["git", "-C", wt] + list(args), check=check)

        g("bisect", "start")
        g("bisect", "bad", bad_sha)
        good_out = g("bisect", "good", good_sha)
        # If `good` is already bad, git complains and bisect can't run.
        run_out = g("bisect", "run", "sh", "-c", cmd)
        log = good_out + run_out
        g("bisect", "reset")

        m = _FIRST_BAD.search(run_out)
        if not m:
            err = ("bisect could not isolate a first-bad commit - check that the "
                   "command fails (non-zero) at 'bad' and passes at 'good'")
            return dict(base_result, good=good_sha, bad=bad_sha, log=log[-2000:], error=err)

        first = _commit_meta(repo, m.group(1))
        first["pr_number"] = _pr_for_commit(repo, first["hash"], head_for_pr)
        return {"good": good_sha, "bad": bad_sha, "first_bad": first,
                "agrees_with_suspect": None, "log": log[-2000:], "error": None}
    finally:
        _proc.run(["git", "-C", repo, "worktree", "remove", "--force", wt], check=False)
        _proc.run(["git", "-C", repo, "worktree", "prune"], check=False)
        shutil.rmtree(parent, ignore_errors=True)


def confirm(ctx: Dict[str, Any], repo: str, suspects, cmd: str,
            good: Optional[str] = None, bad: Optional[str] = None) -> Dict[str, Any]:
    """Run bisect with sensible defaults and set `agrees_with_suspect`."""
    prime = suspects[0]["hash"] if suspects else None
    bad = bad or ctx.get("base_sha") or ctx.get("base_ref")
    # Default good = the prime suspect's parent (if it introduced the bug, its
    # parent should be clean). User can override with --good.
    if not good and prime:
        good = _proc.git(["rev-parse", "--verify", prime + "^"], repo, check=False).strip() or None

    head = ctx.get("head_sha") or ctx.get("head_ref") or "HEAD"
    result = run_bisect(repo, good, bad, cmd, head_for_pr=str(head))
    if result.get("first_bad") and prime:
        result["agrees_with_suspect"] = (result["first_bad"]["hash"] == prime)
    return result
