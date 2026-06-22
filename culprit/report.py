"""Assemble the structured result and a markdown skeleton.

The structured result is the machine-readable output (JSON); the skeleton is
the human-readable scaffold the reasoning layer fills with the narrative.
Neither step calls an LLM - that's isolated in ``culprit.reasoning``.
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
    title = " - {}".format(t["title"]) if t.get("title") else ""
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
        suspects = b.get("suspects", [])
        prime = suspects[0] if suspects else None
        lc = b.get("lifecycle") or {}
        cp = b.get("completeness") or {}

        # --- Introduced: what the author was trying to do when the bug went in ---
        lines.append("## Introduced")
        if prime:
            intent = prime.get("intent") or {}
            pr = intent.get("pr") or {}
            if pr.get("title"):
                pr_txt = " (PR #{}: {})".format(pr.get("number"), pr.get("title"))
            elif prime.get("pr_number"):
                pr_txt = " (PR #{})".format(prime["pr_number"])
            else:
                pr_txt = ""
            lines.append("Prime suspect `{}` - {} - {}{}".format(
                prime["short"], prime.get("author"), prime.get("subject"), pr_txt))
            if intent.get("linked_issues"):
                lines.append("- Addressed issue(s): {}".format(
                    ", ".join("#{}".format(n) for n in intent["linked_issues"])))
            if intent.get("body"):
                body_lines = intent["body"].strip().splitlines()
                if body_lines:
                    lines.append("- Stated intent: {}".format(body_lines[0][:200]))
            lines.append("_(reasoning: what was the author trying to do here?)_")
        else:
            lines.append("_No suspect found (base may not be fetched locally)._")
        for note in b.get("notes", []):
            lines.append("> {}".format(note))
        lines.append("")

        # --- Lived: how long it survived and how far it spread ---
        lines.append("## Lived")
        if lc.get("releases"):
            lines.append("- Shipped in {} release(s): {}{}".format(
                len(lc["releases"]), ", ".join(lc["releases"]),
                " (+more)" if lc.get("releases_truncated") else ""))
        if lc.get("commits_span"):
            lines.append("- {} commit(s) passed before the fix.".format(lc["commits_span"]))
        rec = lc.get("recurrence") or {}
        if rec.get("is_hotspot"):
            lines.append("- Hotspot: {} prior fix(es) to `{}`.".format(
                rec.get("fix_count"), rec.get("file")))
        for note in lc.get("notes", []):
            lines.append("> {}".format(note))
        lines.append("")

        # --- Broke: the ranked suspect set (and bisect, if run) ---
        lines.append("## Suspect set")
        for i, s in enumerate(suspects, 1):
            pr = " (PR #{})".format(s["pr_number"]) if s.get("pr_number") else ""
            lines.append("{}. `{}` - {} - {}{}".format(
                i, s["short"], s.get("author"), s.get("subject"), pr))
            lines.append("   - {} buggy line(s), weight {}, files: {}".format(
                s["lines"], s.get("weight"), ", ".join(s.get("files", []))))
        bz = b.get("bisect")
        if bz and not bz.get("error") and bz.get("first_bad"):
            agree = bz.get("agrees_with_suspect")
            verdict = ("confirmed by git bisect" if agree is True
                       else "bisect found a different first-failing commit" if agree is False
                       else "first failing commit")
            lines.append("- git bisect: {} `{}`.".format(verdict, bz["first_bad"].get("short")))
        lines.append("")

        lines.append("## Why it broke")
        lines.append("_(reasoning layer fills: symptom -> root cause -> the specific change "
                     "that broke it -> contrast the stated intent above with the actual effect)_")
        lines.append("")

        # --- Fixed: is the root cause fully addressed? ---
        lines.append("## Is the fix complete?")
        if cp.get("untouched_count"):
            lines.append("- {} other reference(s) to the changed symbol(s) {} were not "
                         "touched - the fix may be partial.".format(
                             cp["untouched_count"], ", ".join(cp.get("symbols", []))))
        lines.append("- Test in this change: {}".format("yes" if cp.get("adds_test") else "no"))
        if cp.get("is_revert"):
            lines.append("- This change effectively reverts the introducing commit.")
        lines.append("_(reasoning: does the fix address the root cause or just one symptom?)_")
        lines.append("")

        # --- Prevent: the test gap that let it through ---
        tg = b.get("test_gap") or {}
        lines.append("## Prevent")
        if tg.get("untested"):
            lines.append("Add coverage for: {}".format(", ".join(tg["untested"][:20])))
        elif tg.get("covering_tests"):
            lines.append("Touched files are covered by {} test file(s).".format(
                len(tg["covering_tests"])))
        else:
            lines.append("_(reasoning: what test would have caught this?)_")

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
            lines.append("- {} <- {} importer(s)".format(p, n))
        if f.get("covering_tests"):
            lines.append("**Covering tests:**")
            for p in f["covering_tests"][:30]:
                lines.append("- {}".format(p))
        lines.append("")
        lines.append("## Risk assessment")
        lines.append("_(reasoning layer fills: affected areas, risk ranking, test surface "
                     "to exercise)_")

    return "\n".join(lines) + "\n"
