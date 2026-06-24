"""Shared pytest fixtures."""
import pytest

from githelper import git


@pytest.fixture
def git_repo(tmp_path):
    """An initialized, user-configured empty git repo; returns its path."""
    d = str(tmp_path)
    git(d, "init", "-b", "main")
    git(d, "config", "user.email", "t@t.test")
    git(d, "config", "user.name", "Tester")
    return d
