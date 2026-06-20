"""culprit — root-cause analysis for a PR or branch.

Repo-agnostic engine: deterministic git/PR analysis that emits structured JSON.
The only LLM step (the "why it broke" narrative) is isolated behind
``culprit.reasoning`` so the same engine drives both the Claude Code skill
(harness reasons) and the standalone CLI (Claude API reasons).
"""

__version__ = "0.1.0"
