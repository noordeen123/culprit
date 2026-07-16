"""Shared helpers for the benchmark scripts: git plumbing and the repo cache."""
import os
import re
import subprocess

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")


def git(repo, *args):
    """Run git in `repo`, return stdout; raise CalledProcessError on failure."""
    return subprocess.run(
        ["git", "-C", repo, *args], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stdout


def repo_name(url):
    return re.sub(r"\.git$", "", url.rstrip("/").rsplit("/", 1)[-1])


def ensure_clone(url):
    """Full clone of `url` under .cache/ (blame needs full history); reused across runs."""
    if os.path.isdir(url):  # already a local path
        return url
    os.makedirs(CACHE_DIR, exist_ok=True)
    dest = os.path.join(CACHE_DIR, repo_name(url))
    if not os.path.isdir(os.path.join(dest, ".git")):
        subprocess.run(["git", "clone", url, dest], check=True)
    return dest
