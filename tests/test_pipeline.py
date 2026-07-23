import os
import tempfile

import pytest
from githelper import git as _git

from culprit import cli


@pytest.fixture()
def bug_repo():
    """A repo where commit A introduces a bug and a branch fixes it."""
    d = tempfile.mkdtemp(prefix="culprit-test-")
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")

    app = os.path.join(d, "app.py")
    with open(app, "w") as fh:
        fh.write("def area(w, h):\n    return w + h\n")  # the bug: + instead of *
    _git(d, "add", "app.py")
    _git(d, "commit", "-m", "feat: add area")  # introducing commit A

    # base advances with an unrelated commit
    with open(os.path.join(d, "README.md"), "w") as fh:
        fh.write("readme\n")
    _git(d, "add", "README.md")
    _git(d, "commit", "-m", "docs: readme")

    # fix branch
    _git(d, "checkout", "-b", "fix/area")
    with open(app, "w") as fh:
        fh.write("def area(w, h):\n    return w * h\n")  # the fix
    _git(d, "add", "app.py")
    _git(d, "commit", "-m", "fix: area should multiply not add")
    return d


def test_bugfix_pipeline_finds_introducing_commit(bug_repo):
    result = cli.analyze(bug_repo, pr=None, base="main", head="fix/area")
    assert result["classification"]["verdict"] == "bugfix"
    suspects = result["bugfix"]["suspects"]
    assert suspects, "expected at least one suspect"
    # the prime suspect's subject is the commit that introduced the buggy line
    assert "add area" in suspects[0]["subject"]
    assert suspects[0]["lines"] >= 1


def test_test_gap_flags_untested_files(bug_repo):
    from culprit import blast_radius
    tg = blast_radius.test_gap(["app.py"], bug_repo)
    assert "app.py" in tg["untested"]      # no test imports app.py
    assert tg["covering_tests"] == []


def test_bugfix_result_has_test_gap(bug_repo):
    result = cli.analyze(bug_repo, pr=None, base="main", head="fix/area")
    assert "test_gap" in result["bugfix"]


def test_report_skeleton_renders(bug_repo):
    from culprit import report
    result = cli.analyze(bug_repo, pr=None, base="main", head="fix/area")
    md = report.markdown_skeleton(result)
    assert "# RCA:" in md
    assert "Suspect set" in md


def test_profile_narrows_completeness_call_sites(tmp_path):
    from culprit import profile
    d = str(tmp_path)
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")
    # main: buggy area() plus two pre-existing references (python + vendored js).
    with open(os.path.join(d, "app.py"), "w") as fh:
        fh.write("def area(w, h):\n    return w + h\n")
    with open(os.path.join(d, "user.py"), "w") as fh:
        fh.write("from app import area\narea(1, 2)\n")
    with open(os.path.join(d, "vendor.js"), "w") as fh:
        fh.write("area(1, 2);\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "feat: add area + refs")
    _git(d, "checkout", "-b", "fix/area")
    with open(os.path.join(d, "app.py"), "w") as fh:
        fh.write("def area(w, h):\n    return w * h\n")
    _git(d, "add", "app.py")
    _git(d, "commit", "-m", "fix: multiply")

    # No profile: default globs include *.js -> vendored js is a call site.
    res_default = cli.analyze(d, pr=None, base="main", head="fix/area")
    cs_default = res_default["bugfix"]["completeness"]["other_call_sites"]
    js_default = any("vendor.js" in f for fs in cs_default.values() for f in fs)

    # Profile narrows to *.py -> the js reference is excluded, python one remains.
    profile.write(d, {"generated_head": "", "source_globs": ["*.py"], "test_globs": []})
    res_narrow = cli.analyze(d, pr=None, base="main", head="fix/area")
    cs_narrow = res_narrow["bugfix"]["completeness"]["other_call_sites"]
    js_narrow = any("vendor.js" in f for fs in cs_narrow.values() for f in fs)
    py_narrow = any("user.py" in f for fs in cs_narrow.values() for f in fs)

    assert js_default is True    # default globs pick up the .js reference
    assert js_narrow is False    # profile narrowed to *.py drops it
    assert py_narrow is True     # the python reference is still found
