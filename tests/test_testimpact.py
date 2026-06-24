import os
import tempfile

import pytest

from culprit import testimpact


from githelper import git as _git


@pytest.fixture()
def import_graph_repo():
    """util <- service <- (test_service); util <- test_util_direct; unrelated test."""
    d = tempfile.mkdtemp(prefix="culprit-ti-")
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")
    files = {
        "util.py": "def scale(v):\n    return v * 2\n",
        "service.py": "from util import scale\n\ndef run(v):\n    return scale(v)\n",
        "test_util_direct.py": "from util import scale\n\ndef test_scale():\n    assert scale(2) == 4\n",
        "test_service.py": "from service import run\n\ndef test_run():\n    assert run(2) == 4\n",
        "test_unrelated.py": "def test_nothing():\n    assert True\n",
    }
    for name, body in files.items():
        with open(os.path.join(d, name), "w") as fh:
            fh.write(body)
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "init")
    return d


def test_selects_direct_and_transitive_tests(import_graph_repo):
    # changing util.py should select its direct test AND the test of a module that
    # imports it (one hop away), but not the unrelated test.
    ctx = {"changed_files": ["util.py"]}
    res = testimpact.select(ctx, import_graph_repo)
    assert "test_util_direct.py" in res["tests"]
    assert "test_service.py" in res["tests"]       # transitive via service.py
    assert "test_unrelated.py" not in res["tests"]


def test_changed_test_file_is_selected(import_graph_repo):
    ctx = {"changed_files": ["test_unrelated.py"]}
    res = testimpact.select(ctx, import_graph_repo)
    assert "test_unrelated.py" in res["tests"]
    assert res["by_test"]["test_unrelated.py"] == ["changed test file"]


def test_hops_limit_excludes_far_tests(import_graph_repo):
    # with hops=1, only the direct test of util is reachable, not the transitive one.
    ctx = {"changed_files": ["util.py"]}
    res = testimpact.select(ctx, import_graph_repo, hops=1)
    assert "test_util_direct.py" in res["tests"]
    assert "test_service.py" not in res["tests"]
