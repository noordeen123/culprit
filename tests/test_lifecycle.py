import os
import tempfile

import pytest

from culprit import lifecycle, pr_context, suspect


from githelper import git as _git


@pytest.fixture()
def tagged_repo():
    """v1 predates the bug; the bug ships in v2; a fix branch corrects it.

    History on main: feat (v1.0.0) -> fix: lint -> perf: tweak [BUG] (v2.0.0).
    """
    d = tempfile.mkdtemp(prefix="culprit-life-")
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")
    app = os.path.join(d, "calc.py")

    def commit(body, msg):
        with open(app, "w") as fh:
            fh.write(body)
        _git(d, "add", "calc.py")
        _git(d, "commit", "-m", msg)

    commit("def area(w, h):\n    return w * h\n", "feat: add area")
    _git(d, "tag", "v1.0.0")
    commit("def area(w, h):\n    return w * h  # tidy\n", "fix: lint")
    commit("def area(w, h):\n    return w + h\n", "perf: tweak area")   # BUG
    _git(d, "tag", "v2.0.0")
    _git(d, "checkout", "-b", "fix/area")
    commit("def area(w, h):\n    return w * h\n", "fix: multiply not add")
    return d


def test_releases_span_and_recurrence(tagged_repo):
    ctx = pr_context.from_local(tagged_repo, base="main", head="fix/area")
    suspects = suspect.find_suspects(ctx, tagged_repo)["suspects"]
    lc = lifecycle.build(tagged_repo, ctx, suspects)
    # v2 shipped the bug; v1 predates it.
    assert "v2.0.0" in lc["releases"]
    assert "v1.0.0" not in lc["releases"]
    # one commit (the fix) passed between the suspect and head.
    assert lc["commits_span"] == 1
    # the prior "fix: lint" commit makes this a (small) recurrence count.
    assert lc["recurrence"]["fix_count"] >= 1
    assert lc["recurrence"]["file"] == "calc.py"


def test_no_suspect_is_graceful():
    lc = lifecycle.build(".", {"head_sha": None}, [])
    assert lc["releases"] == []
    assert lc["recurrence"] is None
    assert lc["notes"]
