import os
import tempfile

import pytest

from culprit import coupling


from githelper import git as _git


@pytest.fixture()
def coupled_repo():
    """a.py and b.py always change together; c.py changes with them too."""
    d = tempfile.mkdtemp(prefix="culprit-coup-")
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")

    def touch_commit(files, msg):
        for f in files:
            with open(os.path.join(d, f), "a") as fh:
                fh.write(msg + "\n")
        _git(d, "add", "-A")
        _git(d, "commit", "-m", msg)

    for i in range(5):
        touch_commit(["a.py", "b.py", "c.py"], "change {}".format(i))
    touch_commit(["a.py", "b.py"], "tweak ab")
    return d


def test_co_change_partners(coupled_repo):
    res = coupling.cochange(coupled_repo, ["a.py"], min_support=2)
    partners = {p["file"] for p in res["coupled"].get("a.py", [])}
    assert "b.py" in partners and "c.py" in partners


def test_missed_change_flagged(coupled_repo):
    # changing only a.py and b.py -> c.py should surface as possibly-missed.
    res = coupling.cochange(coupled_repo, ["a.py", "b.py"], min_support=2)
    missed = {m["file"] for m in res["missed"]}
    assert "c.py" in missed
