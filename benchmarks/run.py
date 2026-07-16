"""Score culprit's suspect engine against the ground-truth dataset.

Usage: python benchmarks/run.py [--dataset benchmarks/dataset.jsonl]
                                [--out benchmarks/results.json]
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))   # import culprit from the repo
sys.path.insert(0, _HERE)                    # import common when run as a script

from common import ensure_clone, git  # noqa: E402

from culprit import pr_context, suspect  # noqa: E402

OUTCOMES = ("top1", "in_set", "miss", "empty", "error")


def score_case(suspects, expected, top=5):
    """Classify one case: top1 | in_set | miss | empty."""
    if not suspects:
        return "empty"

    def hit(s):
        h = s.get("hash") or ""
        return any(h.startswith(e) or e.startswith(h) for e in expected)

    if hit(suspects[0]):
        return "top1"
    if any(hit(s) for s in suspects[:top]):
        return "in_set"
    return "miss"


def run_case(repo_path, fix_sha):
    """Run the engine exactly as a user analyzing that fix commit would."""
    ctx = pr_context.from_local(repo_path, base=fix_sha + "^", head=fix_sha)
    return suspect.find_suspects(ctx, repo_path)["suspects"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", default=os.path.join(_HERE, "dataset.jsonl"))
    ap.add_argument("--out", default=os.path.join(_HERE, "results.json"))
    args = ap.parse_args()

    with open(args.dataset) as fh:
        cases = [json.loads(line) for line in fh if line.strip()]

    results = []
    for case in cases:
        row = dict(case)
        try:
            repo_path = ensure_clone(case["repo"])
            suspects = run_case(repo_path, case["fix_sha"])
            row["outcome"] = score_case(suspects, case["expected"])
            row["prime"] = suspects[0]["hash"] if suspects else None
        except Exception as exc:  # per-case failures never abort the run
            row["outcome"] = "error"
            row["error"] = str(exc)
        results.append(row)
        print("{:7s} {}  {}".format(row["outcome"], case["fix_sha"][:10], case["repo"]))

    counts = {o: sum(1 for r in results if r["outcome"] == o) for o in OUTCOMES}
    scored = len(results) - counts["error"]
    summary = {
        "cases": len(results),
        "scored": scored,
        "counts": counts,
        "top1_rate": round(counts["top1"] / scored, 3) if scored else None,
        "in_set_rate": round((counts["top1"] + counts["in_set"]) / scored, 3)
                       if scored else None,
        "engine_rev": git(os.path.dirname(_HERE), "rev-parse", "HEAD").strip(),
    }
    with open(args.out, "w") as fh:
        json.dump({"summary": summary, "results": results}, fh, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
