"""culprit CLI - orchestrate the engine and emit a report.

    rca                      # analyze the current branch (local git or its PR)
    rca --pr 16786           # analyze a specific GitHub PR
    rca --repo /path --base main
    rca --mode api --fast    # use the Claude API reasoning layer (standalone)
    rca --json               # print the structured result only

In Claude Code the default --mode harness emits the skeleton and the harness
writes the narrative. --mode api calls Claude directly for terminal/CI use.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from typing import Any, Dict, Optional

from . import (bisect, blast_radius, classify, completeness, config, coupling,
               coverage, evolution, intent, lifecycle, owners, pr_context,
               reasoning, report, risk, suspect, testimpact, trace)


def _run(ctx: Dict[str, Any], repo: str, force: Optional[str] = None,
         coverage_path: Optional[str] = None) -> Dict[str, Any]:
    """Run the deterministic pipeline over an already-resolved context."""
    cls = classify.classify(ctx)
    if force:
        # Reflect the override in the displayed classification, not just the path.
        cls = dict(cls)
        cls["verdict"] = force
        cls["evidence"] = ["forced to '{}' via --force".format(force)] + list(cls.get("evidence", []))
    verdict = force or cls["verdict"]

    bugfix = feature = None
    if verdict == "feature":
        feature = blast_radius.analyze(ctx, repo)
    else:
        # bugfix or unknown -> run RCA (the more actionable default)
        bugfix = suspect.find_suspects(ctx, repo)
        # Attach the line-evolution timeline (origin -> ... -> suspect -> fix).
        bugfix["timeline"] = evolution.build_timeline(ctx, repo, bugfix.get("suspects", []))
        # Did the touched files have any tests? (why the bug slipped through)
        bugfix["test_gap"] = blast_radius.test_gap(ctx.get("changed_files", []), repo)
        # Intent of the suspect/origin, the bug's lifecycle, and fix completeness.
        if bugfix.get("suspects"):
            bugfix["suspects"][0]["intent"] = intent.enrich(repo, ctx, bugfix["suspects"][0])
        intent.enrich_origin(repo, ctx, bugfix["timeline"])
        bugfix["lifecycle"] = lifecycle.build(repo, ctx, bugfix.get("suspects", []))
        bugfix["completeness"] = completeness.assess(ctx, repo, bugfix.get("suspects", []))

    # Optional coverage precision: which changed lines are actually uncovered.
    cov = None
    if coverage_path:
        try:
            cov = coverage.analyze(ctx.get("diff", ""), coverage.parse(coverage_path))
        except Exception as exc:  # never let a bad coverage file break the run
            cov = {"uncovered": {}, "files_with_uncovered": 0, "checked_files": 0,
                   "notes": ["could not read coverage report: {}".format(exc)]}

    result = report.build(ctx, cls, bugfix, feature, coverage=cov)
    # Test impact: which existing tests to run for this change (any verdict).
    result["test_impact"] = testimpact.select(ctx, repo)
    # Predictive signals: co-change ("did you forget X?") + reviewer suggestions.
    changed = ctx.get("changed_files", [])
    suspects = (bugfix or {}).get("suspects", [])
    result["coupling"] = coupling.cochange(repo, changed)
    result["owners"] = owners.suggest(repo, changed, suspects)
    return result


def analyze(repo: str, pr: Optional[int], base: str, head: Optional[str],
            force: Optional[str] = None, coverage_path: Optional[str] = None) -> Dict[str, Any]:
    """Resolve a PR/branch into a context and run the pipeline."""
    ctx = pr_context.resolve(repo, pr=pr, base=base, head=head)
    return _run(ctx, repo, force, coverage_path)


def analyze_trace(repo: str, text: str, head: Optional[str] = None) -> Dict[str, Any]:
    """RCA from a stack trace: parse frames, resolve to repo files, run the pipeline."""
    frames = trace.parse(text)
    resolved, skipped = trace.resolve_files(repo, frames)
    if not resolved:
        raise SystemExit("culprit: no stack frames resolved to files tracked in this repo.")
    ctx = pr_context.from_trace(repo, resolved, head=head)
    result = _run(ctx, repo, force="bugfix")
    result["trace"] = {"frames": resolved, "skipped": [f["file"] for f in skipped]}
    return result


def _save(result: Dict[str, Any], narrative: str) -> str:
    run = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.join(os.path.expanduser("~/culprit/output"), run)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "result.json"), "w") as fh:
        json.dump(result, fh, indent=2, default=str)
    with open(os.path.join(out_dir, "report.md"), "w") as fh:
        fh.write(narrative)
    return out_dir


def _serve_cmd(argv: list) -> int:
    from . import serve
    sp = argparse.ArgumentParser(prog="rca serve",
                                 description="Interactive local web UI with a base-branch picker.")
    sp.add_argument("--repo", default=".", help="repo path (default: cwd)")
    sp.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    sp.add_argument("--port", type=int, default=8722, help="port (default: 8722)")
    sp.add_argument("--no-open", action="store_true", help="don't open a browser")
    a = sp.parse_args(argv)
    return serve.run(repo=a.repo, host=a.host, port=a.port, open_browser=not a.no_open)


def main(argv: Optional[list] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "serve":
        return _serve_cmd(argv[1:])

    p = argparse.ArgumentParser(prog="rca", description="Root-cause analysis for a PR or branch.")
    p.add_argument("pr", nargs="?", type=int, help="PR number (optional)")
    p.add_argument("--pr", dest="pr_flag", type=int, help="PR number")
    p.add_argument("--repo", default=".", help="repo path (default: cwd)")
    p.add_argument("--base", default=None,
                   help="base ref for the diff. Default (local, no PR): the latest commit "
                        "(HEAD~1) - 'the change I just made'. Pass a branch (e.g. develop) "
                        "to analyze a whole branch.")
    p.add_argument("--head", default=None, help="head ref (default: current branch)")
    p.add_argument("--last", action="store_true",
                   help="analyze only the latest commit (HEAD~1), ignoring the configured base")
    p.add_argument("--force", choices=["bugfix", "feature"], help="override classification")
    p.add_argument("--trace", metavar="PATH",
                   help="RCA from a stack trace (file path, or - for stdin); needs no fix/PR/test")
    p.add_argument("--bisect", metavar="CMD",
                   help="repro/test command - runs git bisect (in a throwaway worktree) to "
                        "confirm the suspect. Must exit non-zero when the bug is present.")
    p.add_argument("--good", metavar="REF", help="known-good ref for --bisect (default: suspect's parent)")
    p.add_argument("--bad", metavar="REF", help="known-bad ref for --bisect (default: the base)")
    p.add_argument("--mode", choices=["harness", "api"], default="harness",
                   help="reasoning layer (default: harness)")
    p.add_argument("--fast", action="store_true", help="api mode: use the faster/cheaper model")
    p.add_argument("--json", action="store_true", help="print structured result only")
    p.add_argument("--select-tests", dest="select_tests", action="store_true",
                   help="print the tests to run for this change (one per line), then exit")
    p.add_argument("--coverage", metavar="PATH",
                   help="lcov/Cobertura report to pinpoint which changed lines are uncovered")
    p.add_argument("--html", metavar="PATH", help="write a self-contained HTML report to PATH")
    p.add_argument("--open", dest="open_", action="store_true", help="open the HTML report in a browser")
    p.add_argument("--narrative-file", metavar="PATH",
                   help="embed a pre-written markdown narrative in the HTML report")
    p.add_argument("--no-save", action="store_true", help="don't write to ~/culprit/output")
    p.add_argument("--fail-on", dest="fail_on", choices=["low", "medium", "high"],
                   help="exit non-zero when the QA risk level meets/exceeds this (CI gate)")
    args = p.parse_args(argv)

    repo = os.path.abspath(os.path.expanduser(args.repo))
    pr = args.pr_flag if args.pr_flag is not None else args.pr

    # Base resolution (local mode): --last forces latest commit; else explicit
    # --base; else the repo's configured base (CULPRIT_BASE / .culprit.toml);
    # else None -> latest commit.
    if args.last:
        base = None
    elif args.base is not None:
        base = args.base
    else:
        base = config.repo_base(repo)

    if args.trace:
        text = (sys.stdin.read() if args.trace == "-"
                else open(os.path.expanduser(args.trace), encoding="utf-8").read())
        result = analyze_trace(repo, text, head=args.head)
        tr = result.get("trace") or {}
        sys.stderr.write("trace: {} frame(s) resolved, {} skipped\n".format(
            len(tr.get("frames", [])), len(tr.get("skipped", []))))
    else:
        result = analyze(repo, pr=pr, base=base, head=args.head, force=args.force,
                         coverage_path=args.coverage)

    # Optional: confirm the suspect with a real git bisect (read-only, in a worktree).
    if args.bisect and result.get("bugfix"):
        bz = bisect.confirm(result["target"], repo, result["bugfix"].get("suspects", []),
                            args.bisect, good=args.good, bad=args.bad)
        result["bugfix"]["bisect"] = bz
        if bz.get("error"):
            msg = bz["error"]
        else:
            agrees = bz.get("agrees_with_suspect")
            note = ("agrees with suspect" if agrees is True
                    else "differs from suspect" if agrees is False
                    else "no suspect to compare")
            msg = "first-bad {} ({})".format((bz.get("first_bad") or {}).get("short", "?"), note)
        sys.stderr.write("bisect: {}\n".format(msg))

    # Test selection mode: just print the tests to run (CI-pipeable), then exit.
    if args.select_tests:
        for t in (result.get("test_impact") or {}).get("tests", []):
            print(t)
        return 0

    # QA gate: exit non-zero when risk meets/exceeds --fail-on (no PR writes).
    gate_code = 0
    if args.fail_on:
        rk = result.get("risk") or {}
        lvl, sc = rk.get("level", "low"), rk.get("score", 0)
        if risk.level_at_least(lvl, args.fail_on):
            gate_code = 2
            sys.stderr.write("QA gate: risk {} ({}/100) >= {} - failing.\n".format(lvl, sc, args.fail_on))
        else:
            sys.stderr.write("QA gate: risk {} ({}/100) < {} - passing.\n".format(lvl, sc, args.fail_on))

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return gate_code

    # Resolve the "why" narrative for the report: an explicit file wins, else
    # the API adapter generates one; harness mode leaves it empty (the visual
    # timeline stands on its own with no API key).
    narrative_md = ""
    if args.narrative_file:
        with open(os.path.expanduser(args.narrative_file), encoding="utf-8") as fh:
            narrative_md = fh.read()
    elif args.mode == "api":
        narrative_md = reasoning.get_adapter(mode="api", fast=args.fast).explain(result)

    if args.html:
        from . import htmlreport
        out_path = os.path.abspath(os.path.expanduser(args.html))
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(htmlreport.render(result, narrative_md))
        sys.stderr.write("Wrote HTML report to {}\n".format(out_path))
        if args.open_:
            import webbrowser
            webbrowser.open("file://" + out_path)
        return gate_code

    # Default: markdown to stdout.
    narrative = narrative_md or reasoning.get_adapter(mode=args.mode, fast=args.fast).explain(result)
    print(narrative)

    if not args.no_save:
        out_dir = _save(result, narrative)
        sys.stderr.write("\nSaved to {}\n".format(out_dir))
    return gate_code


if __name__ == "__main__":
    raise SystemExit(main())
