"""Tests for the benchmark harness (benchmarks/ is a dev tool, not packaged)."""
import os
import sys

import pytest
from githelper import git as _git

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "benchmarks"))

import mine  # noqa: E402
from common import git as _cgit  # noqa: E402


def test_parse_trailers_extracts_fixes_sha():
    body = 'fix thing\n\nFixes: 54e85e7af1 ("commit that broke it")\n'
    assert mine.parse_trailers(body) == ["54e85e7af1"]


def test_parse_trailers_regression_pattern_and_dedupe():
    body = ("Fixes: abc1234\n"
            "The regression introduced in abc1234 hurt everyone.\n")
    assert mine.parse_trailers(body) == ["abc1234"]


def test_parse_trailers_ignores_plain_text():
    assert mine.parse_trailers("fix: everything\n\nno trailer here") == []


@pytest.fixture
def trailer_repo(git_repo):
    """Repo whose fix commit carries a Fixes: trailer naming the intro commit."""
    p = os.path.join(git_repo, "f.txt")
    with open(p, "w") as fh:
        fh.write("bug\n")
    _git(git_repo, "add", "f.txt")
    _git(git_repo, "commit", "-m", "feat: add f")
    intro = _cgit(git_repo, "rev-parse", "HEAD").strip()
    with open(p, "w") as fh:
        fh.write("fixed\n")
    _git(git_repo, "add", "f.txt")
    _git(git_repo, "commit", "-m",
         'fix: f\n\nFixes: {} ("feat: add f")'.format(intro[:12]))
    return git_repo, intro


def test_mine_extracts_case_from_fixture_repo(trailer_repo):
    repo, intro = trailer_repo
    cases, summary = mine.mine(repo, repo, cap=10)
    assert len(cases) == 1
    assert cases[0]["expected"] == [intro]
    assert cases[0]["source"] == "fixes-trailer"
    assert summary["mined"] == 1


def test_mine_drops_unresolvable_sha(trailer_repo):
    repo, _ = trailer_repo
    with open(os.path.join(repo, "g.txt"), "w") as fh:
        fh.write("x\n")
    _git(repo, "add", "g.txt")
    _git(repo, "commit", "-m", "fix: g\n\nFixes: deadbeef1234 (\"nonexistent\")")
    cases, summary = mine.mine(repo, repo, cap=10)
    assert len(cases) == 1  # only the resolvable one
    assert summary["dropped_unresolvable"] == 1
