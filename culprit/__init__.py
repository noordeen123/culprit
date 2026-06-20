"""culprit - root-cause analysis for a PR or branch.

Repo-agnostic engine: deterministic git/PR analysis that emits structured JSON.
The only LLM step (the "why it broke" narrative) is isolated behind
``culprit.reasoning`` so the same engine drives both the Claude Code skill
(harness reasons) and the standalone CLI (Claude API reasons).
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("culprit")
except PackageNotFoundError:  # running from a source tree that isn't installed
    __version__ = "0.0.0+unknown"
