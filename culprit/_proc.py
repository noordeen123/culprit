"""Thin, read-only subprocess helpers for git and gh.

Every command here is read-only by construction. Nothing in culprit ever
mutates the target repository or the PR.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import List, Optional


class ProcError(RuntimeError):
    """A subprocess exited non-zero."""

    def __init__(self, cmd: List[str], returncode: int, stderr: str):
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr
        super().__init__("`{}` exited {}: {}".format(" ".join(cmd), returncode, stderr.strip()))


def run(cmd: List[str], cwd: Optional[str] = None, check: bool = True) -> str:
    """Run a command and return stdout. Raise ProcError on failure when check."""
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check and proc.returncode != 0:
        raise ProcError(cmd, proc.returncode, proc.stderr)
    return proc.stdout


def git(args: List[str], repo: str, check: bool = True) -> str:
    return run(["git", "-C", repo] + args, check=check)


def have_gh() -> bool:
    return shutil.which("gh") is not None


def gh(args: List[str], repo: str, check: bool = True) -> str:
    return run(["gh"] + args, cwd=repo, check=check)
