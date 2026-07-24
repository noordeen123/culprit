"""Mine ground-truth (fix commit -> introducing commit) pairs from a repo.

Repos following the Linux-kernel convention end fix commits with a trailer
naming the introducing commit: ``Fixes: <sha> ("subject")``. That trailer is
author-verified ground truth for the suspect benchmark.

Usage: python benchmarks/mine.py https://github.com/git/git --cap 25
"""
import argparse
import json
import os
import re
import subprocess

from common import ensure_clone, git

_FIXES = re.compile(r"(?im)^\s*Fixes:\s*([0-9a-f]{7,40})\b")
_REGRESSION = re.compile(r"(?i)regression introduced (?:in|by)\s+([0-9a-f]{7,40})\b")


def parse_trailers(body):
    """Return the introducing-commit shas a fix commit's body references."""
    shas = _FIXES.findall(body) + _REGRESSION.findall(body)
    seen, out = set(), []
    for s in shas:
        s = s.lower()
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _resolve(repo, ref):
    try:
        return git(repo, "rev-parse", "--verify", "--quiet",
                   ref + "^{commit}").strip() or None
    except subprocess.CalledProcessError:
        return None


def mine(repo, url, cap=25):
    """Return (cases, summary) for up to `cap` most-recent trailer fixes."""
    log = git(repo, "log", "--no-merges", "--format=%H%x00%B%x1e")
    cases = []
    summary = {"mined": 0, "dropped_unresolvable": 0, "dropped_no_parent": 0}
    for record in log.split("\x1e"):
        if cap and len(cases) >= cap:
            break
        record = record.strip("\n\x00 ")
        if not record or "\x00" not in record:
            continue
        fix_sha, body = record.split("\x00", 1)
        refs = parse_trailers(body)
        if not refs:
            continue
        summary["mined"] += 1
        if _resolve(repo, fix_sha + "^") is None:  # root commit: no base to diff
            summary["dropped_no_parent"] += 1
            continue
        expected = []
        for ref in refs:
            full = _resolve(repo, ref)
            if full and full != fix_sha:
                expected.append(full)
        if not expected:
            summary["dropped_unresolvable"] += 1
            continue
        cases.append({"repo": url, "fix_sha": fix_sha,
                      "expected": expected, "source": "fixes-trailer"})
    return cases, summary


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repo", help="repo URL (cloned into .cache/) or local path")
    ap.add_argument("--cap", type=int, default=25)
    ap.add_argument("--out", default=os.path.join(here, "dataset.jsonl"))
    args = ap.parse_args()
    path = ensure_clone(args.repo)
    cases, summary = mine(path, args.repo, cap=args.cap)
    with open(args.out, "a") as fh:
        for c in cases:
            fh.write(json.dumps(c) + "\n")
    print("mined={} kept={} dropped_unresolvable={} dropped_no_parent={} -> {}".format(
        summary["mined"], len(cases), summary["dropped_unresolvable"],
        summary["dropped_no_parent"], args.out))


if __name__ == "__main__":
    main()
