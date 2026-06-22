import os
import subprocess
import tempfile

import pytest

from culprit import completeness


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@pytest.fixture()
def multi_call_repo():
    """`scale` is called from a.py and b.py; defined in util.py."""
    d = tempfile.mkdtemp(prefix="culprit-comp-")
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")
    files = {
        "util.py": "def scale(v):\n    return v * 2\n",
        "a.py": "from util import scale\nresult = scale(10)\n",
        "b.py": "from util import scale\nx = scale(20)\n",
    }
    for name, body in files.items():
        with open(os.path.join(d, name), "w") as fh:
            fh.write(body)
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "init")
    return d


# A fix that touches one call site of scale() in a.py.
_DIFF = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,2 +1,2 @@
 from util import scale
-result = scale(10)
+result = scale(11)
"""


def test_finds_untouched_call_sites(multi_call_repo):
    ctx = {"diff": _DIFF, "changed_files": ["a.py"], "title": "fix: bump", "commits": []}
    res = completeness.assess(ctx, multi_call_repo, [])
    assert "scale" in res["symbols"]
    sites = sum(res["other_call_sites"].values(), [])
    assert "b.py" in sites          # the call site the fix did not touch
    assert "a.py" not in sites      # the changed file is excluded
    assert res["untouched_count"] >= 1
    assert res["adds_test"] is False
    assert res["is_revert"] is False


def test_adds_test_true_when_change_includes_a_test(multi_call_repo):
    ctx = {"diff": _DIFF, "changed_files": ["a.py", "a_test.py"], "title": "fix", "commits": []}
    res = completeness.assess(ctx, multi_call_repo, [])
    assert res["adds_test"] is True


def test_revert_detected_from_title(multi_call_repo):
    ctx = {"diff": _DIFF, "changed_files": ["a.py"],
           "title": 'Revert "perf: tweak area"', "commits": []}
    res = completeness.assess(ctx, multi_call_repo, [])
    assert res["is_revert"] is True
