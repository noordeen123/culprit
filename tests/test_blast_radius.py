import os
import tempfile

import pytest
from githelper import git as _git

from culprit import blast_radius


@pytest.fixture()
def py_repo():
    """A Python package: util imported by main and by a test (no quotes)."""
    d = tempfile.mkdtemp(prefix="culprit-py-")
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")
    os.makedirs(os.path.join(d, "pkg"))
    os.makedirs(os.path.join(d, "tests"))
    files = {
        "pkg/__init__.py": "",
        "pkg/util.py": "def helper():\n    return 1\n",
        "pkg/main.py": "from pkg.util import helper\n\ndef run():\n    return helper()\n",
        "tests/test_util.py": "from pkg.util import helper\n\ndef test_helper():\n    assert helper() == 1\n",
    }
    for rel, body in files.items():
        with open(os.path.join(d, rel), "w") as fh:
            fh.write(body)
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "init")
    return d


def test_python_imports_detected(py_repo):
    # main.py imports pkg.util with no quotes - the bare-import pattern must catch it
    imps = blast_radius._importers(py_repo, "util", "pkg/util.py", blast_radius.DEFAULT_SOURCE_GLOBS)
    assert "pkg/main.py" in imps
    assert "tests/test_util.py" in imps


def test_python_test_gap_sees_coverage(py_repo):
    tg = blast_radius.test_gap(["pkg/util.py"], py_repo)
    assert "tests/test_util.py" in tg["covering_tests"]
    assert "pkg/util.py" not in tg["untested"]   # it IS covered


def test_python_test_gap_flags_uncovered(py_repo):
    tg = blast_radius.test_gap(["pkg/main.py"], py_repo)   # nothing imports main
    assert "pkg/main.py" in tg["untested"]
