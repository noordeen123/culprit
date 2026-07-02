import os
import tempfile

import pytest

from culprit import pr_context, suspect
from githelper import git as _git


@pytest.fixture()
def branch_repo():
    """main: good -> BUG origin; branch fix/area: a wip commit, then the fix."""
    d = tempfile.mkdtemp(prefix="culprit-selfsus-")
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")
    app = os.path.join(d, "calc.py")

    def commit(body, msg):
        with open(app, "w") as fh:
            fh.write(body)
        _git(d, "add", "calc.py")
        _git(d, "commit", "-m", msg)

    commit("def area(w, h):\n    return w * h\n", "feat: add area")        # main, good
    commit("def area(w, h):\n    return w + h\n", "perf: tweak area")      # main, BUG origin
    _git(d, "checkout", "-b", "fix/area")
    commit("def area(w, h):\n    return w + h  # wip\n", "wip: note")      # branch edits the line
    commit("def area(w, h):\n    return w * h\n", "fix: multiply")         # branch, the fix
    return d


def test_suspect_on_branch_is_flagged(branch_repo):
    # base = the previous branch commit (like --last): blame lands on the branch's
    # own work, which is NOT the bug's origin.
    ctx = pr_context.from_local(branch_repo, base="fix/area~1", head="fix/area")
    res = suspect.find_suspects(ctx, branch_repo, trunk="main")
    assert res["origin_on_branch"] is True
    assert res["suspects"][0]["in_base"] is False


def test_suspect_in_trunk_is_not_flagged(branch_repo):
    # base = main (the real target): blame lands on the actual bug-origin commit.
    ctx = pr_context.from_local(branch_repo, base="main", head="fix/area")
    res = suspect.find_suspects(ctx, branch_repo, trunk="main")
    assert res["origin_on_branch"] is False
    assert res["suspects"][0]["in_base"] is True


def test_no_trunk_leaves_in_base_none(branch_repo):
    ctx = pr_context.from_local(branch_repo, base="main", head="fix/area")
    res = suspect.find_suspects(ctx, branch_repo)  # no trunk -> can't classify
    assert res["origin_on_branch"] is False
    assert res["suspects"][0]["in_base"] is None
