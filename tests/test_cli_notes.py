"""The reasoning-mode note must only appear when the run actually reasons.

`--verify-fix` and `--select-tests` return structured data and never build a
narrative, so telling the user about ANTHROPIC_API_KEY there is noise. An agent
calling verify_fix as a pre-commit gate should see the verdict and nothing else.
"""
import os

import pytest
from githelper import git as _git

from culprit import cli

_API_NOTE = "ANTHROPIC_API_KEY"


@pytest.fixture
def fix_repo(git_repo, monkeypatch):
    """A repo with a helper called from two files, plus a diff patching one."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    files = {
        "util.py": "def scale(v):\n    return v * 2\n",
        "a.py": "from util import scale\nresult = scale(10)\n",
        "b.py": "from util import scale\nx = scale(20)\n",
    }
    for name, body in files.items():
        with open(os.path.join(git_repo, name), "w") as fh:
            fh.write(body)
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-m", "seed")
    # A second commit so `--last` (HEAD~1..HEAD) has a real base to diff against.
    with open(os.path.join(git_repo, "a.py"), "w") as fh:
        fh.write("from util import scale\nresult = scale(11)\n")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-m", "bump the scale factor")
    diff = os.path.join(git_repo, "fix.diff")
    with open(diff, "w") as fh:
        fh.write("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
                 "@@ -1,2 +1,2 @@ def scale(v):\n from util import scale\n"
                 "-result = scale(10)\n+result = scale(11)\n")
    return git_repo, diff


def test_verify_fix_does_not_mention_the_api_key(fix_repo, capsys):
    repo, diff = fix_repo
    cli.main(["--repo", repo, "--verify-fix", diff])
    err = capsys.readouterr().err
    assert _API_NOTE not in err, "verify-fix never reasons, so the note is noise"


def test_verify_fix_still_prints_the_verdict(fix_repo, capsys):
    repo, diff = fix_repo
    rc = cli.main(["--repo", repo, "--verify-fix", diff])
    out = capsys.readouterr().out
    assert "verdict:" in out
    assert rc in (0, 1)


def test_select_tests_does_not_mention_the_api_key(fix_repo, capsys):
    repo, _ = fix_repo
    cli.main(["--repo", repo, "--last", "--select-tests", "--no-save"])
    err = capsys.readouterr().err
    assert _API_NOTE not in err


def test_a_reasoning_run_still_warns_about_the_missing_key(fix_repo, capsys):
    # The note is useful where it is true: a normal run does build a narrative,
    # so the api -> harness fallback must still be announced.
    repo, _ = fix_repo
    cli.main(["--repo", repo, "--last", "--json", "--no-save"])
    err = capsys.readouterr().err
    assert _API_NOTE in err
