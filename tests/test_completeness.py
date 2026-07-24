import os
import subprocess
import tempfile

import pytest
from githelper import git as _git

from culprit import completeness


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
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "init")
    with open(f, "w") as fh:
        fh.write("L2\nL3\n")           # suspect removes L1
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "drop L1")
    sha = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], check=True,
                         capture_output=True, text=True).stdout.strip()
    fix_diff = ("diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
                "@@ -1,1 +1,3 @@\n+L1\n+X\n+Y\n")     # 3 added lines, 1 overlaps
    ctx = {"diff": fix_diff, "changed_files": ["f.py"], "title": "fix: stuff", "commits": []}
    res = completeness.assess(ctx, d, [{"hash": sha}])
    assert res["is_revert"] is False


def test_symbol_from_enclosing_def_on_a_context_line(multi_call_repo):
    # The fix changes a line *inside* scale(); the `def scale` is a context line in
    # the hunk (no @@ heading, no call on the changed line). The enclosing function
    # name must still be picked up so other call sites are found.
    diff = ("diff --git a/util.py b/util.py\n--- a/util.py\n+++ b/util.py\n"
            "@@ -1,2 +1,2 @@\n def scale(v):\n-    return v * 2\n+    return v * 3\n")
    ctx = {"diff": diff, "changed_files": ["util.py"], "title": "fix: scale", "commits": []}
    res = completeness.assess(ctx, multi_call_repo, [])
    assert "scale" in res["symbols"]
    sites = sum(res["other_call_sites"].values(), [])
    assert "a.py" in sites and "b.py" in sites


def test_assess_respects_source_globs(tmp_path):
    # A symbol referenced from a .py file and a vendored .js file. Narrowing
    # source_globs to python must drop the .js reference from other-call-sites.
    git_repo = str(tmp_path)
    _git(git_repo, "init", "-b", "main")
    _git(git_repo, "config", "user.email", "t@t.test")
    _git(git_repo, "config", "user.name", "Tester")
    with open(os.path.join(git_repo, "core.py"), "w") as fh:
        fh.write("def helper():\n    return 1\n")
    with open(os.path.join(git_repo, "user.py"), "w") as fh:
        fh.write("from core import helper\nhelper()\n")
    with open(os.path.join(git_repo, "vendor.js"), "w") as fh:
        fh.write("helper();\n")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-m", "seed")

    diff = ("diff --git a/core.py b/core.py\n"
            "--- a/core.py\n+++ b/core.py\n"
            "@@ -1,2 +1,2 @@ def helper():\n"
            "-    return 1\n+    return 2\n")
    ctx = {"diff": diff, "changed_files": ["core.py"]}

    wide = completeness.assess(ctx, git_repo, [])
    narrow = completeness.assess(ctx, git_repo, [], source_globs=["*.py"])
    js_wide = any("vendor.js" in f for fs in wide["other_call_sites"].values() for f in fs)
    js_narrow = any("vendor.js" in f for fs in narrow["other_call_sites"].values() for f in fs)
    assert js_wide is True     # default globs include *.js
    assert js_narrow is False  # narrowed to *.py -> js reference excluded


def _seed(repo):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed")


def test_assess_excludes_builtin_calls_from_symbols(git_repo):
    with open(os.path.join(git_repo, "app.py"), "w") as fh:
        fh.write("def compute_total(items):\n"
                 "    return sum(i.price for i in items)\n")
    _seed(git_repo)
    diff = ("diff --git a/app.py b/app.py\n"
            "--- a/app.py\n+++ b/app.py\n"
            "@@ -1,2 +1,2 @@ def compute_total(items):\n"
            "-    return sum(i.price for i in items)\n"
            "+    return sum(i.price for i in items if isinstance(i.price, int))\n")
    ctx = {"diff": diff, "changed_files": ["app.py"]}
    res = completeness.assess(ctx, git_repo, [], source_globs=["*.py"])
    assert "compute_total" in res["symbols"]           # enclosing def, repo-defined
    for noise in ("sum", "isinstance", "len", "any"):   # builtins / not repo-defined
        assert noise not in res["symbols"]


def test_assess_keeps_repo_defined_helper_and_finds_call_sites(git_repo):
    with open(os.path.join(git_repo, "lib.py"), "w") as fh:
        fh.write("def compute_total(items):\n    return 0\n")
    with open(os.path.join(git_repo, "caller.py"), "w") as fh:
        fh.write("from lib import compute_total\ncompute_total([])\n")
    _seed(git_repo)
    # A fix (new file) that calls the repo-defined helper.
    diff = ("diff --git a/app.py b/app.py\n"
            "--- /dev/null\n+++ b/app.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+from lib import compute_total\n"
            "+compute_total([1])\n")
    ctx = {"diff": diff, "changed_files": ["app.py"]}
    res = completeness.assess(ctx, git_repo, [], source_globs=["*.py"])
    assert "compute_total" in res["symbols"]
    sites = res["other_call_sites"].get("compute_total", [])
    assert any("caller.py" in f for f in sites)


def test_assess_drops_builtin_named_project_method(git_repo):
    # The repo DEFINES `get`, but `get` is on the denylist -> not a symbol.
    with open(os.path.join(git_repo, "store.py"), "w") as fh:
        fh.write("def get(key):\n    return key\n")
    with open(os.path.join(git_repo, "other.py"), "w") as fh:
        fh.write("from store import get\nget('x')\n")
    _seed(git_repo)
    diff = ("diff --git a/store.py b/store.py\n"
            "--- a/store.py\n+++ b/store.py\n"
            "@@ -1,2 +1,2 @@ def get(key):\n"
            "-    return key\n+    return key or 'default'\n")
    ctx = {"diff": diff, "changed_files": ["store.py"]}
    res = completeness.assess(ctx, git_repo, [], source_globs=["*.py"])
    assert "get" not in res["symbols"]                  # denylist wins over repo-defined


def test_assess_recognizes_brace_language_method_definition(git_repo):
    # A Java/C-family method definition carries no leading `def`/`func` keyword;
    # _is_defined must still recognize it (the body opens on the same line) so the
    # symbol survives and its other call sites are reported. Without this, the
    # precision filter silences completeness for every C-family method.
    with open(os.path.join(git_repo, "Calc.java"), "w") as fh:
        fh.write("class Calc {\n"
                 "    public int computeTotal(int x) {\n"
                 "        return x + 1;\n"
                 "    }\n"
                 "}\n")
    with open(os.path.join(git_repo, "Caller.java"), "w") as fh:
        fh.write("class Caller {\n"
                 "    void run(Calc c) {\n"
                 "        c.computeTotal(5);\n"
                 "    }\n"
                 "}\n")
    _seed(git_repo)
    diff = ("diff --git a/Calc.java b/Calc.java\n"
            "--- a/Calc.java\n+++ b/Calc.java\n"
            "@@ -2,3 +2,3 @@ public int computeTotal(int x) {\n"
            "-        return x + 1;\n"
            "+        return x + 2;\n")
    ctx = {"diff": diff, "changed_files": ["Calc.java"]}
    res = completeness.assess(ctx, git_repo, [], source_globs=["*.java"])
    assert "computeTotal" in res["symbols"]
    sites = res["other_call_sites"].get("computeTotal", [])
    assert any("Caller.java" in f for f in sites)


def test_assess_skips_ubiquitous_symbol(git_repo, monkeypatch):
    monkeypatch.setattr(completeness, "_COMMON_REFS", 2)  # keep the fixture small
    with open(os.path.join(git_repo, "lib.py"), "w") as fh:
        fh.write("def widely_used():\n    return 1\n")
    for i in range(4):  # 4 referencing files > threshold of 2
        with open(os.path.join(git_repo, "u{}.py".format(i)), "w") as fh:
            fh.write("from lib import widely_used\nwidely_used()\n")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-m", "seed")
    diff = ("diff --git a/lib.py b/lib.py\n"
            "--- a/lib.py\n+++ b/lib.py\n"
            "@@ -1,2 +1,2 @@ def widely_used():\n"
            "-    return 1\n+    return 2\n")
    ctx = {"diff": diff, "changed_files": ["lib.py"]}
    res = completeness.assess(ctx, git_repo, [], source_globs=["*.py"])
    assert "widely_used" not in res["other_call_sites"]        # too common -> skipped
    assert any("widely_used" in n for n in res["notes"])       # skip is noted
