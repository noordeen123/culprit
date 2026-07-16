"""Blame accuracy: moved code (-M -C) and .git-blame-ignore-revs support."""
import os
import subprocess

import pytest
from githelper import git as _git

from culprit import pr_context, suspect

# Multi-line so git's copy-detection threshold (~40 alnum chars) triggers.
BUGGY_FUNC = (
    "def compute_total_price(quantity, unit_price):\n"
    "    subtotal = quantity + unit_price   # BUG: should multiply\n"
    "    tax = subtotal * 0.18\n"
    "    return subtotal + tax\n"
)
FIXED_FUNC = BUGGY_FUNC.replace(
    "quantity + unit_price   # BUG: should multiply", "quantity * unit_price")


def _write(repo, name, text):
    with open(os.path.join(repo, name), "w") as fh:
        fh.write(text)


def _sha(repo):
    return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], check=True,
                          stdout=subprocess.PIPE, text=True).stdout.strip()


@pytest.fixture
def moved_code_repo(git_repo):
    """A writes the buggy function in util.py; B moves it to app.py; a branch fixes it."""
    _write(git_repo, "util.py", BUGGY_FUNC)
    _git(git_repo, "add", "util.py")
    _git(git_repo, "commit", "-m", "feat: add pricing")            # A: wrote the bug
    intro = _sha(git_repo)

    _write(git_repo, "util.py", "")                                # B: move to app.py
    _write(git_repo, "app.py", BUGGY_FUNC)
    _git(git_repo, "add", "util.py", "app.py")
    _git(git_repo, "commit", "-m", "refactor: move pricing to app")

    _git(git_repo, "checkout", "-b", "fix/pricing")
    _write(git_repo, "app.py", FIXED_FUNC)
    _git(git_repo, "add", "app.py")
    _git(git_repo, "commit", "-m", "fix: multiply price")
    return git_repo, intro


def test_moved_code_blames_original_author(moved_code_repo):
    repo, intro = moved_code_repo
    ctx = pr_context.from_local(repo, base="main", head="fix/pricing")
    res = suspect.find_suspects(ctx, repo)
    assert res["suspects"], "expected suspects"
    # -C follows the moved block: A (who wrote the bug), not B (who moved it)
    assert res["suspects"][0]["hash"] == intro
