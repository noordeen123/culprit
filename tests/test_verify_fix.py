"""Tests for culprit.verify_fix: fix verification before committing."""
import os
import tempfile

import pytest
from githelper import git as _git

from culprit import profile, verify_fix


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


@pytest.fixture()
def solo_repo():
    """helper() defined and used only in core.py -- a fully localized change."""
    d = tempfile.mkdtemp(prefix="culprit-vfix-")
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")
    with open(os.path.join(d, "core.py"), "w") as fh:
        fh.write("def helper(v):\n    return v + 1\n\nprint(helper(3))\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "init")
    return d


_CLEAN_UNTESTED_DIFF = """\
diff --git a/core.py b/core.py
--- a/core.py
+++ b/core.py
@@ -1,2 +1,2 @@ def helper(v):
-    return v + 1
+    return v + 2
"""

_CLEAN_TESTED_DIFF = _CLEAN_UNTESTED_DIFF + """\
diff --git a/test_core.py b/test_core.py
--- /dev/null
+++ b/test_core.py
@@ -0,0 +1,3 @@
+from core import helper
+def test_helper():
+    assert helper(2) == 4
"""

_MISSED_WITH_TEST_DIFF = """\
diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,2 +1,2 @@ def scale(v):
 from util import scale
-result = scale(10)
+result = scale(11)
diff --git a/test_scale.py b/test_scale.py
--- /dev/null
+++ b/test_scale.py
@@ -0,0 +1,3 @@
+from util import scale
+def test_scale():
+    assert scale(2) == 4
"""

_NO_TEST_NOTE = "no test verifies it"


def test_clean_untested_fix_is_complete_with_medium_risk(solo_repo):
    # Nothing missed (untouched == 0) but no test. Verdict tracks completeness, so
    # it is `complete`; the missing test shows up as medium risk plus a note --
    # not as `partial`, which is reserved for genuinely missed call sites.
    res = verify_fix.assess(solo_repo, _CLEAN_UNTESTED_DIFF)
    assert res["untouched_references"] == []
    assert res["adds_test"] is False
    assert res["verdict"] == "complete"
    assert res["risk_level"] == "medium"
    assert any(_NO_TEST_NOTE in n for n in res["notes"])


def test_clean_tested_fix_is_complete_low_risk(solo_repo):
    # Same fix but with a test: complete and low risk, no "add a test" note.
    res = verify_fix.assess(solo_repo, _CLEAN_TESTED_DIFF)
    assert res["adds_test"] is True
    assert res["verdict"] == "complete"
    assert res["risk_level"] == "low"
    assert not any(_NO_TEST_NOTE in n for n in res["notes"])


def test_missed_call_site_with_test_is_partial(multi_call_repo):
    # A test is present but a call site (b.py) was missed: completeness is off, so
    # the verdict is `partial`, distinct from the clean-untested `complete` case.
    res = verify_fix.assess(multi_call_repo, _MISSED_WITH_TEST_DIFF)
    assert res["untouched_references"]
    assert res["adds_test"] is True
    assert res["verdict"] == "partial"
    assert res["risk_level"] == "medium"


def test_missed_call_site_without_test_is_risky(multi_call_repo):
    res = verify_fix.assess(multi_call_repo, _PARTIAL_DIFF)
    assert res["adds_test"] is False
    assert res["verdict"] == "risky"
    assert res["risk_level"] == "high"


def test_partial_verdict_when_call_site_missed(multi_call_repo):
    res = verify_fix.assess(multi_call_repo, _PARTIAL_DIFF)
    assert res["verdict"] in ("partial", "risky")
    assert res["untouched_references"]  # b.py missed
    assert "scale" in res["symbols_fixed"]


def test_complete_verdict_with_test(multi_call_repo):
    res = verify_fix.assess(multi_call_repo, _COMPLETE_WITH_TEST_DIFF)
    # Both call sites patched and a test added; complete or partial (util.py defines scale too)
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


def test_verify_fix_honors_profile_source_globs(tmp_path):
    d = str(tmp_path)
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")
    with open(os.path.join(d, "app.py"), "w") as fh:
        fh.write("def helper():\n    return 1\n")
    with open(os.path.join(d, "user.py"), "w") as fh:
        fh.write("from app import helper\nhelper()\n")
    with open(os.path.join(d, "vendor.js"), "w") as fh:
        fh.write("helper();\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "seed")
    diff = ("diff --git a/app.py b/app.py\n"
            "--- a/app.py\n+++ b/app.py\n"
            "@@ -1,2 +1,2 @@ def helper():\n"
            "-    return 1\n+    return 2\n")
    r_default = verify_fix.assess(d, diff, "main")
    profile.write(d, {"generated_head": "", "source_globs": ["*.py"], "test_globs": []})
    r_narrow = verify_fix.assess(d, diff, "main")
    assert any("vendor.js" in ref for ref in r_default["untouched_references"])
    assert not any("vendor.js" in ref for ref in r_narrow["untouched_references"])
