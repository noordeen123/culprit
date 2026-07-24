"""Tests for the benchmark harness (benchmarks/ is a dev tool, not packaged)."""
import os
import subprocess
import sys

import pytest
from githelper import git as _git

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "benchmarks"))

import mine  # noqa: E402
import run as bench_run  # noqa: E402
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


def _suspect(sha):
    return {"hash": sha}


def test_score_case_outcomes():
    exp = ["a" * 40]
    assert bench_run.score_case([_suspect("a" * 40), _suspect("b" * 40)], exp) == "top1"
    assert bench_run.score_case([_suspect("b" * 40), _suspect("a" * 40)], exp) == "in_set"
    assert bench_run.score_case([_suspect("b" * 40)], exp) == "miss"
    assert bench_run.score_case([], exp) == "empty"


def test_score_case_in_set_respects_top_cutoff():
    exp = ["a" * 40]
    six = [_suspect(c * 40) for c in "bcdef"] + [_suspect("a" * 40)]
    assert bench_run.score_case(six, exp, top=5) == "miss"


def test_score_case_matches_abbreviated_sha():
    assert bench_run.score_case([_suspect("a" * 40)], ["a" * 10]) == "top1"


def test_run_case_blames_intro_commit(trailer_repo):
    repo, intro = trailer_repo
    fix = _cgit(repo, "rev-parse", "HEAD").strip()
    suspects = bench_run.run_case(repo, fix)
    assert suspects and suspects[0]["hash"] == intro


def test_run_cli_help_exits_zero():
    root = os.path.join(os.path.dirname(__file__), "..")
    r = subprocess.run(
        [sys.executable, os.path.join(root, "benchmarks", "run.py"), "--help"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert r.returncode == 0


def test_run_case_passes_chain_mode(trailer_repo):
    repo, intro = trailer_repo
    fix = _cgit(repo, "rev-parse", "HEAD").strip()
    # the engine default is chain="additive"; an explicit "additive" must match it
    assert bench_run.run_case(repo, fix, chain="additive") == bench_run.run_case(repo, fix)
