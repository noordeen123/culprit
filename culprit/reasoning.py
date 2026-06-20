"""The one LLM step, isolated behind an adapter.

- ``HarnessAdapter``: returns the structured result + markdown skeleton and
  leaves the narrative to the calling agent (the Claude Code harness). No API
  key, no network. This is what the SKILL.md uses.
- ``ClaudeAPIAdapter``: calls the Claude API (Anthropic SDK) to write the
  narrative. This is what the standalone CLI / CI uses. Requires
  ``pip install culprit[api]`` and ``ANTHROPIC_API_KEY``.

Swapping adapters is the only difference between the skill and the product;
the engine above is identical.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from . import report

# Quality-first default; --fast drops to Sonnet. Classify (elsewhere) is the
# cheap tier and never needs the API in the skill path.
MODEL_DEFAULT = "claude-opus-4-8"
MODEL_FAST = "claude-sonnet-4-6"

_SYSTEM = (
    "You are a root-cause analysis assistant. You are given a deterministic, "
    "machine-built analysis of a pull request or branch: its classification "
    "(bugfix or feature), the changed files, and either a ranked suspect set "
    "(the commits that last touched the lines a bugfix removed) or a blast-radius "
    "map (reverse imports + covering tests). Write a tight, evidence-grounded "
    "report. For a bugfix: symptom, the single most likely introducing commit and "
    "why, how the bug manifested, whether the fix fully addresses the root cause, "
    "and the test gap that let it through. For a feature: the real affected areas, "
    "a risk ranking, and the specific test surface to exercise. Cite commit hashes "
    "and file paths from the data; never invent commits or files."
)


class ReasoningAdapter:
    """Turn a structured result into a markdown narrative."""

    def explain(self, result: Dict[str, Any]) -> str:
        raise NotImplementedError


class HarnessAdapter(ReasoningAdapter):
    """No-op: hand the skeleton back; the surrounding agent does the reasoning."""

    def explain(self, result: Dict[str, Any]) -> str:
        return report.markdown_skeleton(result)


class ClaudeAPIAdapter(ReasoningAdapter):
    """Call the Claude API to author the narrative."""

    def __init__(self, model: str = MODEL_DEFAULT, api_key: Optional[str] = None):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    def explain(self, result: Dict[str, Any]) -> str:
        try:
            import anthropic
        except ImportError:
            raise RuntimeError(
                "ClaudeAPIAdapter needs the 'anthropic' SDK - install with "
                "`pip install culprit[api]`."
            )
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")

        client = anthropic.Anthropic(api_key=self.api_key)
        skeleton = report.markdown_skeleton(result)
        user = (
            "Structured analysis (JSON):\n```json\n{}\n```\n\n"
            "Markdown skeleton to complete:\n```md\n{}\n```\n\n"
            "Return the completed report as markdown."
        ).format(json.dumps(result, indent=2, default=str), skeleton)

        # Stream the narrative (it can be long); adaptive thinking for the
        # multi-step causal reasoning.
        with client.messages.stream(
            model=self.model,
            max_tokens=8000,
            thinking={"type": "adaptive"},
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            return skeleton + "\n\n_(reasoning declined by the model; showing skeleton only)_\n"
        text = "".join(b.text for b in message.content if b.type == "text")
        return text or skeleton


def get_adapter(mode: str = "harness", fast: bool = False) -> ReasoningAdapter:
    if mode == "api":
        return ClaudeAPIAdapter(model=MODEL_FAST if fast else MODEL_DEFAULT)
    return HarnessAdapter()
