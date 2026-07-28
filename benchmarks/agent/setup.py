#!/usr/bin/env python3
"""Build isolated sandboxes for the agent-baseline arm of the suspect benchmark.

Fairness rules, mirroring exactly what culprit's engine receives:

  * culprit gets ONLY the diff. pr_context.from_local sets title=None, body=None,
    so it never sees the fix commit message. The agent gets the same: the diff,
    and nothing else about the fix.
  * The ground truth lives in the fix commit's `Fixes:` trailer, so the agent must
    not be able to reach the fix commit. Each sandbox is a --shared clone rewound
    to the fix's parent with every other ref, the remote, and the reflog removed,
    so `git log --all` cannot see the fix or anything after it.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))   # repo root
CACHE = os.path.join(REPO, "benchmarks", ".cache")
SANDBOX = os.path.join(HERE, "sandboxes")


def git(args, cwd, check=True):
    p = subprocess.run(["git"] + args, cwd=cwd, check=check,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, encoding="utf-8", errors="replace")
    return p.stdout


def repo_name(url):
    return url.rstrip("/").rsplit("/", 1)[-1].replace(".git", "")


def build(case, idx):
    src = os.path.join(CACHE, repo_name(case["repo"]))
    fix = case["fix_sha"]
    parent = git(["rev-parse", fix + "^"], src).strip()

    dest = os.path.join(SANDBOX, "case{:02d}".format(idx))
    work = os.path.join(dest, "repo")
    if os.path.exists(dest):
        subprocess.run(["rm", "-rf", dest], check=True)
    os.makedirs(dest)

    # The diff the agent is asked to explain, taken from the real fix.
    diff = git(["diff", "{}...{}".format(parent, fix)], src)
    with open(os.path.join(dest, "fix.diff"), "w", encoding="utf-8") as fh:
        fh.write(diff)

    # Shared clone (no object copy), rewound to the parent.
    subprocess.run(["git", "clone", "--quiet", "--shared", "--no-checkout", src, work],
                   check=True, capture_output=True)
    git(["checkout", "--quiet", "-B", "bench", parent], work)

    # Make the fix and everything after it unreachable by name.
    for line in git(["for-each-ref", "--format=%(refname)"], work).splitlines():
        ref = line.strip()
        if ref and ref != "refs/heads/bench":
            git(["update-ref", "-d", ref], work, check=False)
    git(["remote", "remove", "origin"], work, check=False)
    subprocess.run(["rm", "-rf", os.path.join(work, ".git", "logs")], check=True)

    # Verification: the fix commit must not be reachable from any ref.
    reachable = git(["rev-list", "--all"], work).split()
    leaked = fix in reachable or any(e in reachable for e in case["expected"] if e == fix)
    tip = git(["rev-parse", "HEAD"], work).strip()

    meta = {"idx": idx, "repo": case["repo"], "fix_sha": fix, "parent": parent,
            "expected": case["expected"], "tip": tip, "leaked_fix": leaked,
            "diff_bytes": len(diff)}
    with open(os.path.join(dest, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2)
    return meta


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    with open(os.path.join(REPO, "benchmarks", "dataset.jsonl")) as fh:
        cases = [json.loads(x) for x in fh if x.strip()]
    os.makedirs(SANDBOX, exist_ok=True)
    built = []
    for i in range(start, min(start + n, len(cases))):
        m = build(cases[i], i)
        built.append(m)
        print("case{:02d}  {:<9} parent={}  diff={}B  leaked={}".format(
            i, repo_name(m["repo"]), m["parent"][:10], m["diff_bytes"], m["leaked_fix"]))
    bad = [m for m in built if m["leaked_fix"]]
    print("\n{} sandboxes built, {} leaking the fix commit".format(len(built), len(bad)))


if __name__ == "__main__":
    main()
