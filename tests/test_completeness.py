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


def test_revert_threshold_not_too_lenient(tmp_path):
    # A 3-line fix that re-adds only ONE line the suspect removed must NOT be
    # flagged a revert (needs a majority overlap, not just one line).
    d = str(tmp_path)
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")
    f = os.path.join(d, "f.py")
    with open(f, "w") as fh:
        fh.write("L1\nL2\nL3\n")
    _git(d, "add", "-A"); _git(d, "commit", "-m", "init")
    with open(f, "w") as fh:
        fh.write("L2\nL3\n")           # suspect removes L1
    _git(d, "add", "-A"); _git(d, "commit", "-m", "drop L1")
    sha = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    fix_diff = ("diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
                "@@ -1,1 +1,3 @@\n+L1\n+X\n+Y\n")     # 3 added lines, 1 overlaps
    ctx = {"diff": fix_diff, "changed_files": ["f.py"], "title": "fix: stuff", "commits": []}
    res = completeness.assess(ctx, d, [{"hash": sha}])
    assert res["is_revert"] is False
