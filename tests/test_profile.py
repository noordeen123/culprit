"""Tests for the project profile (.culprit/profile.json)."""
import json
import os

import pytest
from githelper import git as _git

from culprit import profile
from culprit.blast_radius import DEFAULT_SOURCE_GLOBS


def _write(repo, name, text=""):
    path = os.path.join(repo, name)
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(name) else None
    with open(path, "w") as fh:
        fh.write(text)


def _commit_all(repo, msg="c"):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", msg)


@pytest.fixture
def py_repo(git_repo):
    """5 python modules + one vendored js file, all committed."""
    for i in range(5):
        _write(git_repo, "pkg/mod{}.py".format(i), "x = {}\n".format(i))
    _write(git_repo, "vendor/lib.js", "// vendored\n")
    _commit_all(git_repo)
    return git_repo


def test_detect_narrows_to_present_source_and_excludes_lone_vendor(py_repo):
    det = profile.detect(py_repo)
    assert "*.py" in det["source_globs"]
    assert "*.js" not in det["source_globs"]  # 1 vendored js < _MIN_EXT_FILES
    assert det["generated_head"]  # a sha


@pytest.fixture
def elixir_repo(git_repo):
    for i in range(5):
        _write(git_repo, "lib/m{}.ex".format(i), "defmodule M{} do\nend\n".format(i))
    _commit_all(git_repo)
    return git_repo


def test_detect_extends_to_frequent_unknown_extension(elixir_repo):
    det = profile.detect(elixir_repo)
    assert "*.ex" in det["source_globs"]


@pytest.fixture
def tested_repo(git_repo):
    for i in range(5):
        _write(git_repo, "pkg/mod{}.py".format(i), "x = {}\n".format(i))
    _write(git_repo, "tests/foo_test.py", "def test_x():\n    assert True\n")
    _commit_all(git_repo)
    return git_repo


def test_detect_records_test_conventions(tested_repo):
    det = profile.detect(tested_repo)
    assert "*_test.py" in det["test_globs"]
    assert "tests/" in det["test_globs"]


def test_load_none_when_absent(git_repo):
    assert profile.load(git_repo) is None
    assert profile.source_globs(git_repo) == list(DEFAULT_SOURCE_GLOBS)


def test_load_none_when_malformed_or_too_new(git_repo):
    os.makedirs(os.path.join(git_repo, ".culprit"))
    path = os.path.join(git_repo, profile.PROFILE_PATH)
    with open(path, "w") as fh:
        fh.write("{ not json")
    assert profile.load(git_repo) is None
    assert profile.source_globs(git_repo) == list(DEFAULT_SOURCE_GLOBS)
    with open(path, "w") as fh:
        json.dump({"version": 999, "detected": {"source_globs": ["*.py"]},
                   "overrides": {}}, fh)
    assert profile.load(git_repo) is None
    assert profile.source_globs(git_repo) == list(DEFAULT_SOURCE_GLOBS)


def test_override_wins_over_detected(git_repo):
    os.makedirs(os.path.join(git_repo, ".culprit"))
    with open(os.path.join(git_repo, profile.PROFILE_PATH), "w") as fh:
        json.dump({"version": 1,
                   "detected": {"source_globs": ["*.py"]},
                   "overrides": {"source_globs": ["*.rb"]}}, fh)
    assert profile.source_globs(git_repo) == ["*.rb"]


def test_detected_used_when_no_override(git_repo):
    os.makedirs(os.path.join(git_repo, ".culprit"))
    with open(os.path.join(git_repo, profile.PROFILE_PATH), "w") as fh:
        json.dump({"version": 1,
                   "detected": {"source_globs": ["*.py"]},
                   "overrides": {}}, fh)
    assert profile.source_globs(git_repo) == ["*.py"]


def test_write_preserves_overrides(py_repo):
    profile.write(py_repo, profile.detect(py_repo))
    data = profile.load(py_repo)
    data["overrides"] = {"source_globs": ["*.rb"]}
    with open(os.path.join(py_repo, profile.PROFILE_PATH), "w") as fh:
        json.dump(data, fh)
    # Refresh detected; override must survive.
    profile.write(py_repo, {"generated_head": "abc", "source_globs": ["*.py"],
                            "test_globs": []})
    after = profile.load(py_repo)
    assert after["overrides"] == {"source_globs": ["*.rb"]}
    assert after["detected"]["source_globs"] == ["*.py"]


def test_staleness_note(py_repo, monkeypatch):
    monkeypatch.setattr(profile, "_STALE_COMMITS", 3)  # keep the test cheap
    profile.write(py_repo, profile.detect(py_repo))
    assert profile.staleness_note(py_repo) is None  # fresh
    for i in range(4):  # > threshold
        _write(py_repo, "n{}.py".format(i), "y = {}\n".format(i))
        _commit_all(py_repo, "c{}".format(i))
    note = profile.staleness_note(py_repo)
    assert note and "culprit init" in note


def test_load_none_when_version_not_numeric(git_repo):
    os.makedirs(os.path.join(git_repo, ".culprit"))
    with open(os.path.join(git_repo, profile.PROFILE_PATH), "w") as fh:
        json.dump({"version": "bad", "detected": {"source_globs": ["*.py"]},
                   "overrides": {}}, fh)
    assert profile.load(git_repo) is None
    assert profile.source_globs(git_repo) == list(DEFAULT_SOURCE_GLOBS)


def test_empty_source_globs_treated_as_absent(git_repo):
    os.makedirs(os.path.join(git_repo, ".culprit"))
    # empty override falls through to detected; empty detected falls to DEFAULT
    with open(os.path.join(git_repo, profile.PROFILE_PATH), "w") as fh:
        json.dump({"version": 1,
                   "detected": {"source_globs": ["*.py"]},
                   "overrides": {"source_globs": []}}, fh)
    assert profile.source_globs(git_repo) == ["*.py"]
    with open(os.path.join(git_repo, profile.PROFILE_PATH), "w") as fh:
        json.dump({"version": 1,
                   "detected": {"source_globs": []},
                   "overrides": {"source_globs": []}}, fh)
    assert profile.source_globs(git_repo) == list(DEFAULT_SOURCE_GLOBS)


def test_staleness_note_none_when_head_not_resolvable(git_repo):
    os.makedirs(os.path.join(git_repo, ".culprit"))
    with open(os.path.join(git_repo, profile.PROFILE_PATH), "w") as fh:
        json.dump({"version": 1,
                   "detected": {"generated_head": "0" * 40, "source_globs": ["*.py"],
                                "test_globs": []},
                   "overrides": {}}, fh)
    # a nonexistent generated_head -> merge-base --is-ancestor errors -> None
    assert profile.staleness_note(git_repo) is None
