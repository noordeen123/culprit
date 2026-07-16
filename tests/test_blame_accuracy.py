"""Blame accuracy: .git-blame-ignore-revs support and its fallback.

Moved-code blame (``-M -C``) was benchmarked against 50 real fix-commit ->
introducing-commit pairs (Fixes:-trailer ground truth from git/git and
systemd) and found to REGRESS suspect accuracy (top1 0.48 -> 0.44, in_set
0.60 -> 0.54): -M -C answers "who wrote this content", but when the bug is
introduced by the move/refactor itself, that's the wrong answer culprit
needs. -M -C was reverted; only plain blame plus ignore-revs support remains,
covered below.
"""
import os
import subprocess

import pytest
from githelper import git as _git

from culprit import pr_context, suspect


def _write(repo, name, text):
    with open(os.path.join(repo, name), "w") as fh:
        fh.write(text)


def _sha(repo):
    return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], check=True,
                          stdout=subprocess.PIPE, text=True).stdout.strip()


@pytest.fixture
def reformat_repo(git_repo):
    """A writes the bug; B reformats (listed in .git-blame-ignore-revs); a branch fixes."""
    _write(git_repo, "calc.py", "def area(w,h):\n    return w+h  # BUG\n")
    _git(git_repo, "add", "calc.py")
    _git(git_repo, "commit", "-m", "feat: area")                   # A: wrote the bug
    intro = _sha(git_repo)

    _write(git_repo, "calc.py", "def area(w, h):\n    return w + h  # BUG\n")
    _git(git_repo, "add", "calc.py")
    _git(git_repo, "commit", "-m", "style: reformat")              # B: reformat only
    reformat = _sha(git_repo)

    _write(git_repo, ".git-blame-ignore-revs", reformat + "\n")
    _git(git_repo, "add", ".git-blame-ignore-revs")
    _git(git_repo, "commit", "-m", "chore: ignore reformat in blame")

    _git(git_repo, "checkout", "-b", "fix/area")
    _write(git_repo, "calc.py", "def area(w, h):\n    return w * h\n")
    _git(git_repo, "add", "calc.py")
    _git(git_repo, "commit", "-m", "fix: multiply")
    return git_repo, intro


def test_ignore_revs_skips_reformat_commit(reformat_repo):
    repo, intro = reformat_repo
    ctx = pr_context.from_local(repo, base="main", head="fix/area")
    res = suspect.find_suspects(ctx, repo)
    assert res["suspects"]
    # blame maps through the ignored reformat commit back to A
    assert res["suspects"][0]["hash"] == intro


def test_bad_ignore_revs_file_falls_back_to_plain_blame(reformat_repo):
    repo, _ = reformat_repo
    _write(repo, ".git-blame-ignore-revs", "not-a-sha\n")  # git rejects this file
    ctx = pr_context.from_local(repo, base="main", head="fix/area")
    res = suspect.find_suspects(ctx, repo)
    assert res["suspects"], "must fall back to plain blame, not return nothing"
