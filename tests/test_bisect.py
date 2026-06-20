import os
import shlex
import subprocess
import sys
import tempfile

import pytest

from culprit import bisect, cli, pr_context, suspect


def _git(repo, *args, **kw):
    env = dict(os.environ, **kw.get("env", {}))
    subprocess.run(["git", "-C", repo, *args], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)


@pytest.fixture()
def bisectable_repo():
    """area() is correct, then a commit breaks it (w+h), then a fix branch."""
    d = tempfile.mkdtemp(prefix="culprit-bisect-test-")
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")
    app = os.path.join(d, "calc.py")

    def commit(body, msg, when):
        with open(app, "w") as fh:
            fh.write(body)
        _git(d, "add", "calc.py")
        _git(d, "commit", "-m", msg,
             env={"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when})

    commit("def area(w, h):\n    return w * h\n", "feat: add area", "2025-09-01T10:00:00")
    commit("def area(w, h):\n    return (w * h)\n", "refactor: parens", "2025-11-01T10:00:00")
    commit("def area(w, h):\n    return (w + h)\n", "perf: tweak area", "2026-01-01T10:00:00")  # BUG
    _git(d, "checkout", "-b", "fix/area")
    commit("def area(w, h):\n    return (w * h)\n", "fix: multiply not add", "2026-06-01T10:00:00")
    return d


# Command that fails (non-zero) when the bug is present. Use the running
# interpreter (not a hardcoded `python3`, which may not be on PATH).
_TEST_CMD = '{} -c "import calc, sys; sys.exit(0 if calc.area(2, 3) == 6 else 1)"'.format(
    shlex.quote(sys.executable))


def test_bisect_finds_the_bug_commit_and_agrees(bisectable_repo):
    ctx = pr_context.from_local(bisectable_repo, base="main", head="fix/area")
    suspects = suspect.find_suspects(ctx, bisectable_repo)["suspects"]
    res = bisect.confirm(ctx, bisectable_repo, suspects, _TEST_CMD)
    assert res["error"] is None, res["error"]
    assert res["first_bad"] is not None
    assert "tweak area" in res["first_bad"]["subject"]   # the perf commit introduced w+h
    assert res["agrees_with_suspect"] is True


def test_bisect_is_read_only(bisectable_repo):
    before_status = subprocess.run(["git", "-C", bisectable_repo, "status", "--porcelain"],
                                   capture_output=True, text=True).stdout
    before_head = subprocess.run(["git", "-C", bisectable_repo, "rev-parse", "HEAD"],
                                 capture_output=True, text=True).stdout
    ctx = pr_context.from_local(bisectable_repo, base="main", head="fix/area")
    suspects = suspect.find_suspects(ctx, bisectable_repo)["suspects"]
    bisect.confirm(ctx, bisectable_repo, suspects, _TEST_CMD)
    after_status = subprocess.run(["git", "-C", bisectable_repo, "status", "--porcelain"],
                                  capture_output=True, text=True).stdout
    after_head = subprocess.run(["git", "-C", bisectable_repo, "rev-parse", "HEAD"],
                                capture_output=True, text=True).stdout
    worktrees = subprocess.run(["git", "-C", bisectable_repo, "worktree", "list"],
                               capture_output=True, text=True).stdout
    assert before_status == after_status      # working tree untouched
    assert before_head == after_head          # HEAD not moved
    # only the main worktree remains (the temp bisect worktree was torn down)
    assert len([l for l in worktrees.splitlines() if l.strip()]) == 1


def test_bisect_without_suspect_is_not_comparable(bisectable_repo):
    # bisect succeeds but there is no heuristic suspect to compare against:
    # agrees_with_suspect must stay None (not collapse to False/"differs").
    ctx = pr_context.from_local(bisectable_repo, base="main", head="fix/area")
    res = bisect.confirm(ctx, bisectable_repo, [], _TEST_CMD, good="main~2")
    assert res["error"] is None
    assert res["first_bad"] is not None
    assert res["agrees_with_suspect"] is None


def test_bisect_needs_good(bisectable_repo):
    # no suspects + no --good -> graceful error, not a crash
    ctx = pr_context.from_local(bisectable_repo, base="main", head="fix/area")
    res = bisect.confirm(ctx, bisectable_repo, [], _TEST_CMD, good=None)
    assert res["error"] is not None
    assert res["first_bad"] is None
