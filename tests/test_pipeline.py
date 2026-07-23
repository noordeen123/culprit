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


def test_profile_narrows_source_globs_in_pipeline(bug_repo):
    # Add a vendored .js that references the changed module's name; without a
    # profile it shows as a dependent/importer, with a *.py-only profile it does not.
    from culprit import profile
    with open(os.path.join(bug_repo, "vendor.js"), "w") as fh:
        fh.write("import app from './app'\n")
    _git(bug_repo, "add", "vendor.js")
    _git(bug_repo, "commit", "-m", "chore: vendored js")

    # Write a profile that narrows to python only.
    profile.write(bug_repo, {"generated_head": "", "source_globs": ["*.py"],
                             "test_globs": []})
    res = cli.analyze(bug_repo, pr=None, base="main", head="fix/area")
    # The vendored js must never appear among selected tests / dependents.
    blob = repr(res)
    assert "vendor.js" not in blob
