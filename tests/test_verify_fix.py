"""Tests for culprit.verify_fix — fix verification before committing."""
import os
import tempfile

import pytest

from culprit import verify_fix
from githelper import git as _git


@pytest.fixture()
def multi_call_repo():
    """scale() defined in util.py, called from a.py and b.py."""
    d = tempfile.mkdtemp(prefix="culprit-vfix-")
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


_PARTIAL_DIFF = """\
diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,2 +1,2 @@ def scale(v):
 from util import scale
-result = scale(10)
+result = scale(11)
"""

_COMPLETE_DIFF = """\
diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,2 +1,2 @@ def scale(v):
 from util import scale
-result = scale(10)
+result = scale(11)
diff --git a/b.py b/b.py
--- a/b.py
+++ b/b.py
@@ -1,2 +1,2 @@ def scale(v):
 from util import scale
-x = scale(20)
+x = scale(21)
"""

_COMPLETE_WITH_TEST_DIFF = """\
diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,2 +1,2 @@ def scale(v):
 from util import scale
-result = scale(10)
+result = scale(11)
diff --git a/b.py b/b.py
--- a/b.py
+++ b/b.py
@@ -1,2 +1,2 @@ def scale(v):
 from util import scale
-x = scale(20)
+x = scale(21)
diff --git a/test_scale.py b/test_scale.py
--- /dev/null
+++ b/test_scale.py
@@ -0,0 +1,3 @@
+from util import scale
+def test_scale():
+    assert scale(2) == 4
"""


def test_partial_verdict_when_call_site_missed(multi_call_repo):
    res = verify_fix.assess(multi_call_repo, _PARTIAL_DIFF)
    assert res["verdict"] in ("partial", "risky")
    assert res["untouched_references"]  # b.py missed
    assert "scale" in res["symbols_fixed"]


def test_complete_verdict_with_test(multi_call_repo):
    res = verify_fix.assess(multi_call_repo, _COMPLETE_WITH_TEST_DIFF)
    # Both call sites patched and a test added — complete or partial (util.py defines scale too)
    assert res["verdict"] in ("complete", "partial")
    assert res["adds_test"] is True
    # Adding a test keeps risk low or medium at worst
    assert res["risk_level"] in ("low", "medium")


def test_partial_without_test(multi_call_repo):
    res = verify_fix.assess(multi_call_repo, _COMPLETE_DIFF)
    # Both call sites patched but no test added
    assert res["verdict"] in ("partial", "risky")
    assert res["adds_test"] is False


def test_changed_files_parsed_from_diff(multi_call_repo):
    res = verify_fix.assess(multi_call_repo, _PARTIAL_DIFF)
    # b.py should appear in untouched_references (the missed call site)
    assert any("b.py" in r for r in res["untouched_references"])


def test_empty_diff_returns_safe_result(multi_call_repo):
    res = verify_fix.assess(multi_call_repo, "")
    assert res["verdict"] in ("complete", "partial", "risky")
    assert isinstance(res["symbols_fixed"], list)
    assert isinstance(res["tests_to_run"], list)


def test_risk_level_high_when_many_untouched(multi_call_repo):
    # Only fixing a.py when b.py also has a call site, no test coverage -> medium/high
    res = verify_fix.assess(multi_call_repo, _PARTIAL_DIFF)
    assert res["risk_level"] in ("medium", "high")
