"""Assemble the structured result and a markdown skeleton.

The structured result is the machine-readable output (JSON); the skeleton is
the human-readable scaffold the reasoning layer fills with the narrative.
Neither step calls an LLM — that's isolated in ``culprit.reasoning``.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def build(ctx: Dict[str, Any], classification: Dict[str, Any],
          bugfix: Optional[Dict[str, Any]], feature: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    target = {k: ctx.get(k) for k in (
        "source", "kind", "pr_number", "title", "head_ref", "base_ref",
        "head_sha", "base_sha", "head_date", "repo_url", "repo_host", "links", "labels")}
    target["changed_files"] = ctx.get("changed_files", [])
    target["commit_count"] = len(ctx.get("commits", []))
    return {
        "target": target,
        "classification": classification,
        "bugfix": bugfix,
        "feature": feature,
    }


def _fmt_target(t: Dict[str, Any]) -> str:
    who = "PR #{}".format(t["pr_number"]) if t.get("pr_number") else "branch {}".format(
        t.get("head_ref"))
    title = " — {}".format(t["title"]) if t.get("title") else ""
    return "{}{}  (base: {})".format(who, title, t.get("base_ref"))


def markdown_skeleton(result: Dict[str, Any]) -> str:
    t = result["target"]
    c = result["classification"]
    lines = []
    lines.append("# RCA: {}".format(_fmt_target(t)))
    lines.append("")
    lines.append("**Classification:** {} (confidence {}, score {})".format(
        c["verdict"], c["confidence"], c["score"]))
    for ev in c.get("evidence", []):
        lines.append("- {}".format(ev))
    lines.append("")
    lines.append("Changed files ({}):".format(len(t["changed_files"])))
    for f in t["changed_files"][:40]:
        lines.append("- {}".format(f))
    lines.append("")

    if result.get("bugfix") is not None:
        b = result["bugfix"]
        lines.append("## Suspect set")
        for note in b.get("notes", []):
            lines.append("> {}".format(note))
        if not b.get("suspects"):
            lines.append("_No suspects found (base may not be fetched locally)._")
        for i, s in enumerate(b.get("suspects", []), 1):
            pr = " (PR #{})".format(s["pr_number"]) if s.get("pr_number") else ""
            lines.append("{}. `{}` — {} — {}{}".format(
                i, s["short"], s.get("author"), s.get("subject"), pr))
            lines.append("   - {} buggy line(s), weight {}, files: {}".format(
                s["lines"], s.get("weight"), ", ".join(s.get("files", []))))
        lines.append("")
        lines.append("## Why it broke")
        lines.append("_(reasoning layer fills: symptom → root cause → introducing commit "
                     "→ why → fix assessment → test gap)_")

    if result.get("feature") is not None:
        f = result["feature"]
        lines.append("## Blast radius")
        lines.append("Total dependents: {}".format(f.get("total_dependents")))
        if f.get("high_risk"):
            lines.append("**High-risk touched modules:**")
            for p in f["high_risk"]:
                lines.append("- {}".format(p))
        lines.append("**Most-depended-on changed files:**")
        for p, n in list(f.get("dependent_counts", {}).items())[:15]:
            lines.append("- {} ← {} importer(s)".format(p, n))
        if f.get("covering_tests"):
            lines.append("**Covering tests:**")
            for p in f["covering_tests"][:30]:
                lines.append("- {}".format(p))
        lines.append("")
        lines.append("## Risk assessment")
        lines.append("_(reasoning layer fills: affected areas, risk ranking, test surface "
                     "to exercise)_")

    return "\n".join(lines) + "\n"
