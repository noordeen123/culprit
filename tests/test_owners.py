import os
import tempfile

import pytest

from culprit import owners


from githelper import git as _git


@pytest.fixture()
def owned_repo():
    d = tempfile.mkdtemp(prefix="culprit-own-")
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")
    os.makedirs(os.path.join(d, ".github"))
    with open(os.path.join(d, ".github", "CODEOWNERS"), "w") as fh:
        fh.write("*.py @py-team\n/docs/ @docs-team\n")
    with open(os.path.join(d, "app.py"), "w") as fh:
        fh.write("x = 1\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "init", env={"GIT_AUTHOR_NAME": "Alice", "GIT_COMMITTER_NAME": "Alice"})
    with open(os.path.join(d, "app.py"), "a") as fh:
        fh.write("y = 2\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "edit", env={"GIT_AUTHOR_NAME": "Alice", "GIT_COMMITTER_NAME": "Alice"})
    return d


def test_codeowners_and_authors(owned_repo):
    res = owners.suggest(owned_repo, ["app.py"])
    assert "@py-team" in res["codeowners"]
    assert any(a["name"] == "Alice" for a in res["authors"])


def test_no_codeowners_is_graceful(tmp_path):
    d = str(tmp_path)
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")
    with open(os.path.join(d, "a.py"), "w") as fh:
        fh.write("x=1\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "init")
    res = owners.suggest(d, ["a.py"])
    assert res["codeowners"] == []
    assert res["authors"]  # at least the committer
