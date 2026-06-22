import os
import subprocess
import tempfile

import pytest

from culprit import intent
from culprit.intent import _linked_issues


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@pytest.fixture()
def repo_with_body():
    d = tempfile.mkdtemp(prefix="culprit-intent-")
    _git(d, "init", "-b", "main")
    _git(d, "config", "user.email", "t@t.test")
    _git(d, "config", "user.name", "Tester")
    f = os.path.join(d, "a.py")
    with open(f, "w") as fh:
        fh.write("x = 1\n")
    _git(d, "add", "a.py")
    _git(d, "commit", "-m", "feat: thing\n\nRefactor the widget for clarity.\n\nFixes #42")
    return d


def test_enrich_extracts_body_and_linked_issues(repo_with_body):
    sha = subprocess.run(["git", "-C", repo_with_body, "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    res = intent.enrich(repo_with_body, {}, {"hash": sha, "subject": "feat: thing", "pr_number": None})
    assert res["body"] and "Refactor the widget" in res["body"]
    assert res["linked_issues"] == [42]
    assert res["pr"] is None  # no PR number -> no lookup attempted


def test_linked_issues_dedupes_across_texts():
    assert _linked_issues("Closes #1 and fixes #2", "resolves #1") == [1, 2]
    assert _linked_issues(None, "no refs here") == []


def test_enrich_origin_marks_only_the_first_origin():
    tl = {"ranges": [{"steps": [
        {"role": "origin", "hash": "deadbeef", "subject": "x", "pr_number": None},
        {"role": "suspect", "hash": "cafe", "pr_number": None},
    ]}]}
    # Bogus repo/sha: _commit_body fails gracefully (body None), no crash.
    intent.enrich_origin(".", {}, tl)
    assert "intent" in tl["ranges"][0]["steps"][0]
    assert "intent" not in tl["ranges"][0]["steps"][1]
