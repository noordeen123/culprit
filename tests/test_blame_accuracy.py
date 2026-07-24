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


def _commit(repo, msg, when):
    """Commit staged changes with a deterministic author/committer date."""
    _git(repo, "commit", "-m", msg,
         env={"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when})


@pytest.fixture
def tie_repo(git_repo):
    """Two suspects own one buggy line each, an exact line-count tie.

    The reformat commit is deliberately NEWER, so date order alone would rank
    it first: the test proves the reformat demotion, not date luck.
    """
    f = "data.py"
    _write(git_repo, f, "X = 1  # BUG-A\nY = 2  # BUG-B\n")
    _git(git_repo, "add", f)
    _commit(git_repo, "feat: add data", "2023-01-01T00:00:00")
    feat = _sha(git_repo)

    _write(git_repo, f, "X = 1  # BUG-A\nY  =  2   # BUG-B\n")   # touches only line 2
    _git(git_repo, "add", f)
    _commit(git_repo, "style: reformat table", "2024-01-01T00:00:00")

    _git(git_repo, "checkout", "-b", "fix/data")
    _write(git_repo, f, "X = 10\nY = 20\n")                       # fix touches both lines
    _git(git_repo, "add", f)
    _commit(git_repo, "fix: correct data values", "2024-06-01T00:00:00")
    return git_repo, feat


def test_tiebreak_reformat_commit_loses(tie_repo):
    repo, feat = tie_repo
    ctx = pr_context.from_local(repo, base="main", head="fix/data")
    res = suspect.find_suspects(ctx, repo)
    assert len(res["suspects"]) == 2
    # 1-1 line tie: the "style: reformat" commit loses despite being newer
    assert res["suspects"][0]["hash"] == feat


@pytest.fixture
def date_tie_repo(git_repo):
    """Two non-reformat suspects tied on lines, newer commit wins."""
    f = "calc.py"
    _write(git_repo, f, "A = 1  # BUG\n")
    _git(git_repo, "add", f)
    _commit(git_repo, "feat: add a", "2023-01-01T00:00:00")

    _write(git_repo, f, "A = 1  # BUG\nB = 2  # BUG\n")
    _git(git_repo, "add", f)
    _commit(git_repo, "feat: add b", "2024-01-01T00:00:00")
    newer = _sha(git_repo)

    _git(git_repo, "checkout", "-b", "fix/calc")
    _write(git_repo, f, "A = 10\nB = 20\n")
    _git(git_repo, "add", f)
    _commit(git_repo, "fix: correct values", "2024-06-01T00:00:00")
    return git_repo, newer


def test_tiebreak_newer_commit_wins_among_equals(date_tie_repo):
    repo, newer = date_tie_repo
    ctx = pr_context.from_local(repo, base="main", head="fix/calc")
    res = suspect.find_suspects(ctx, repo)
    assert len(res["suspects"]) == 2
    assert res["suspects"][0]["hash"] == newer


@pytest.fixture
def chained_repo(git_repo):
    """A writes the buggy line; B mechanically refactors it; a branch fixes it.

    Blame at base lands on B (the absorber). Chaining blames B's own removed
    lines at B^ and finds A.
    """
    f = "core.py"
    _write(git_repo, f,
           "def total(items):\n"
           "    result = 0\n"
           "    for it in items:\n"
           "        result += it.price - it.discount - it.discount  # BUG: discount twice\n"
           "    return result\n")
    _git(git_repo, "add", f)
    _commit(git_repo, "feat: add total", "2023-01-01T00:00:00")
    intro = _sha(git_repo)

    _write(git_repo, f,
           "def total(items):\n"
           "    result = 0\n"
           "    for item in items:\n"
           "        result += item.price - item.discount - item.discount  # BUG: discount twice\n"
           "    return result\n")
    _git(git_repo, "add", f)
    _commit(git_repo, "refactor: rename loop variable", "2024-01-01T00:00:00")
    absorber = _sha(git_repo)

    _git(git_repo, "checkout", "-b", "fix/total")
    _write(git_repo, f,
           "def total(items):\n"
           "    result = 0\n"
           "    for item in items:\n"
           "        result += item.price - item.discount\n"
           "    return result\n")
    _git(git_repo, "add", f)
    _commit(git_repo, "fix: apply discount once", "2024-06-01T00:00:00")
    return git_repo, intro, absorber


def test_chain_off_absorber_hides_intro(chained_repo):
    repo, intro, absorber = chained_repo
    ctx = pr_context.from_local(repo, base="main", head="fix/total")
    res = suspect.find_suspects(ctx, repo, chain="off")
    hashes = [s["hash"] for s in res["suspects"]]
    assert res["suspects"][0]["hash"] == absorber
    assert intro not in hashes  # today's behavior: A is invisible


def test_chain_additive_surfaces_intro_below_absorber(chained_repo):
    repo, intro, absorber = chained_repo
    ctx = pr_context.from_local(repo, base="main", head="fix/total")
    res = suspect.find_suspects(ctx, repo, chain="additive")
    hashes = [s["hash"] for s in res["suspects"]]
    assert res["suspects"][0]["hash"] == absorber  # additive never dethrones
    assert intro in hashes
    chained = next(s for s in res["suspects"] if s["hash"] == intro)
    assert chained["chained_from"] == absorber
    assert chained["hop"] == 1


def test_chain_passthrough_makes_intro_prime(chained_repo):
    repo, intro, absorber = chained_repo
    ctx = pr_context.from_local(repo, base="main", head="fix/total")
    res = suspect.find_suspects(ctx, repo, chain="passthrough")
    # absorber subject matches the mechanical regex: blame passes through
    assert res["suspects"][0]["hash"] == intro
    # promoted to a full-weight primary - not rendered as a hop-back guess
    assert "chained_from" not in res["suspects"][0]
    assert res["suspects"][0]["weight"] is not None


@pytest.fixture
def substantive_absorber_repo(git_repo):
    """Same shape, but B is a real logic change; passthrough must NOT transfer."""
    f = "core.py"
    _write(git_repo, f,
           "def total(items):\n"
           "    result = 0\n"
           "    for it in items:\n"
           "        result += it.price - it.discount - it.discount  # BUG: discount twice\n"
           "    return result\n")
    _git(git_repo, "add", f)
    _commit(git_repo, "feat: add total", "2023-01-01T00:00:00")
    intro = _sha(git_repo)

    _write(git_repo, f,
           "def total(items):\n"
           "    result = 0\n"
           "    for it in items:\n"
           "        tax = it.price * 0.2 if it.taxable else 0.0\n"
           "        result += it.price + tax - it.discount - it.discount  # BUG: discount twice\n"
           "    return result\n")
    _git(git_repo, "add", f)
    _commit(git_repo, "feat: apply tax to taxable items", "2024-01-01T00:00:00")
    absorber = _sha(git_repo)

    _git(git_repo, "checkout", "-b", "fix/total")
    _write(git_repo, f,
           "def total(items):\n"
           "    result = 0\n"
           "    for it in items:\n"
           "        tax = it.price * 0.2 if it.taxable else 0.0\n"
           "        result += it.price + tax - it.discount\n"
           "    return result\n")
    _git(git_repo, "add", f)
    _commit(git_repo, "fix: apply discount once", "2024-06-01T00:00:00")
    return git_repo, intro, absorber


def test_chain_passthrough_keeps_substantive_absorber_prime(substantive_absorber_repo):
    repo, intro, absorber = substantive_absorber_repo
    ctx = pr_context.from_local(repo, base="main", head="fix/total")
    res = suspect.find_suspects(ctx, repo, chain="passthrough")
    hashes = [s["hash"] for s in res["suspects"]]
    assert res["suspects"][0]["hash"] == absorber  # no transfer: B is substantive
    assert intro in hashes                          # but A still surfaces additively


def test_chain_dead_ends_safely_on_file_creator(reformat_repo):
    """Chaining from a file-creating commit finds no removed lines, no crash,
    same prime as chain='off'."""
    repo, intro = reformat_repo
    ctx = pr_context.from_local(repo, base="main", head="fix/area")
    res = suspect.find_suspects(ctx, repo, chain="passthrough")
    assert res["suspects"]
    assert res["suspects"][0]["hash"] == intro


def test_is_mechanical_similarity_path_fires_without_keyword():
    """A subject with no mechanical keyword still counts as mechanical when the
    removed and added lines are near-identical (the difflib similarity path)."""
    subject = "adjust parameter"  # no refactor/rename/etc. keyword
    diff = ("-    return compute_total(items, discount_rate)\n"
            "+    return compute_total(items, discount_ratio)\n")
    assert suspect._is_mechanical(subject, diff) is True


def test_is_mechanical_false_for_substantive_change_without_keyword():
    """No keyword and genuinely different lines: not mechanical."""
    subject = "add tax handling"
    diff = ("-    x = 1\n"
            "+    tax = price * rate + surcharge - rebate\n"
            "+    total = base + tax\n")
    assert suspect._is_mechanical(subject, diff) is False
