"""Shared test helper: run a git command in a repo, raising on failure.

Importing module (not a fixture) so the many repo-building fixtures can call it
directly: ``from githelper import git as _git``.
"""
import os
import subprocess


def git(repo, *args, **kw):
    env = dict(os.environ, **kw.get("env", {}))
    subprocess.run(["git", "-C", repo, *args], check=True, env=env,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
