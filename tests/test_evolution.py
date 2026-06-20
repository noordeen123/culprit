import os
import subprocess
import tempfile

import pytest

from culprit import cli, evolution, pr_context, suspect


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@pytest.fixture()
def evo_repo():
    """origin commit creates a line, a middle commit edits it, a later commit
    introduces the bug, and a fix branch corrects it."""
    d = tempfile.mkdtemp(prefix="culprit-evo-")
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")
    app = os.path.join(d, "calc.py")

    def commit(body, msg):
        with open(app, "w") as fh:
            fh.write(body)
        _git(d, "add", "calc.py")
        _git(d, "commit", "-m", msg)

    commit("def area(w, h):\n    return w * h\n", "feat: add area")          # origin (correct)
    commit("def area(w, h):\n    return (w * h)\n", "refactor: parens")      # modified
    commit("def area(w, h):\n    return (w + h)\n", "perf: tweak area")      # BUG introduced
    _git(d, "checkout", "-b", "fix/area")
    commit("def area(w, h):\n    return (w * h)\n", "fix: area multiply")    # the fix
    return d


def test_timeline_has_origin_suspect_and_fix(evo_repo):
    ctx = pr_context.from_local(evo_repo, base="main", head="fix/area")
    suspects = suspect.find_suspects(ctx, evo_repo)["suspects"]
    tl = evolution.build_timeline(ctx, evo_repo, suspects)
    assert tl["ranges"], "expected at least one range timeline"
    steps = tl["ranges"][0]["steps"]
    roles = [s["role"] for s in steps]
    assert roles[0] == "origin"
    assert "suspect" in roles
    assert roles[-1] == "fix"
    # steps are chronological and each carries a diff hunk
    assert all("diff" in s for s in steps)
    # the suspect step is the "perf: tweak area" commit that introduced w + h
    suspect_step = next(s for s in steps if s["role"] == "suspect")
    assert "tweak area" in suspect_step["subject"]


def test_timeline_attached_via_analyze(evo_repo):
    result = cli.analyze(evo_repo, pr=None, base="main", head="fix/area")
    assert result["bugfix"]["timeline"]["ranges"]
