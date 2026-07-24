"""`culprit init` subcommand + staleness note."""
import json
import os

import pytest
from githelper import git as _git

from culprit import cli, profile


@pytest.fixture
def py_repo(git_repo):
    for i in range(5):
        p = os.path.join(git_repo, "pkg")
        os.makedirs(p, exist_ok=True)
        with open(os.path.join(p, "m{}.py".format(i)), "w") as fh:
            fh.write("x = {}\n".format(i))
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-m", "seed")
    return git_repo


def test_init_writes_profile(py_repo, capsys):
    rc = cli.main(["init", "--repo", py_repo])
    assert rc == 0
    data = json.load(open(os.path.join(py_repo, profile.PROFILE_PATH)))
    assert data["version"] == 1
    assert "*.py" in data["detected"]["source_globs"]
    assert data["overrides"] == {}


def test_init_preserves_overrides_on_rerun(py_repo):
    cli.main(["init", "--repo", py_repo])
    data = profile.load(py_repo)
    data["overrides"] = {"source_globs": ["*.rb"]}
    with open(os.path.join(py_repo, profile.PROFILE_PATH), "w") as fh:
        json.dump(data, fh)
    cli.main(["init", "--repo", py_repo])  # refresh
    after = profile.load(py_repo)
    assert after["overrides"] == {"source_globs": ["*.rb"]}


def test_init_warns_on_unparseable_existing(py_repo, capsys):
    os.makedirs(os.path.join(py_repo, ".culprit"), exist_ok=True)
    with open(os.path.join(py_repo, profile.PROFILE_PATH), "w") as fh:
        fh.write("{ broken")
    rc = cli.main(["init", "--repo", py_repo])
    assert rc == 0
    err = capsys.readouterr().err
    assert "overwrit" in err.lower() or "could not" in err.lower()
    assert profile.load(py_repo)["overrides"] == {}  # reset, since unparseable
