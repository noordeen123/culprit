#!/usr/bin/env python3
"""Score all three arms on the same cases, by the same rules.

  A: culprit alone            (deterministic, ~0 tokens, sub-second)
  B: agent alone with git     (Opus + bash)
  C: agent given culprit's output first

Uses benchmarks/run.py's own score_case so no arm gets a friendlier judge.
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))   # repo root
sys.path[:0] = [REPO, os.path.join(REPO, "benchmarks")]

from run import score_case  # noqa: E402


def load(path):
    try:
        return json.load(open(path))
    except Exception:
        return None


def main():
    rows = []
    for meta_path in sorted(glob.glob(os.path.join(HERE, "sandboxes", "case*", "meta.json"))):
        idx = os.path.basename(os.path.dirname(meta_path))[4:]
        meta = json.load(open(meta_path))
        expected = meta["expected"]

        cul = load(os.path.join(HERE, "culprit_out", "case%s.json" % idx)) or []
        b = load(os.path.join(HERE, "answers_b", "case%s.json" % idx))
        c = load(os.path.join(HERE, "answers_c", "case%s.json" % idx))
        if b is None and c is None:
            continue

        def outcome(ans):
            if ans is None:
                return None
            return score_case([{"hash": s} for s in ans.get("suspects", [])], expected)

        rows.append({
            "case": idx,
            # NB: substring "/git" also matches "/github.com", so compare the
            # final path segment instead.
            "repo": meta["repo"].rstrip("/").rsplit("/", 1)[-1],
            "expected": expected[0][:10],
            "A": score_case(cul, expected) if cul else "empty",
            "B": outcome(b),
            "C": outcome(c),
            "C_reordered": (c or {}).get("changed_tool_order"),
        })

    if not rows:
        print("no answers yet")
        return

    print("\ncase  repo     expected     A:culprit   B:agent     C:agent+culprit")
    print("-" * 74)
    for r in rows:
        print("{:>4}  {:<7}  {:<11}  {:<11} {:<11} {:<11}".format(
            r["case"], r["repo"], r["expected"],
            r["A"], r["B"] or "-", r["C"] or "-"))

    def rate(key, hits):
        vals = [r[key] for r in rows if r[key] is not None]
        return (100.0 * sum(1 for v in vals if v in hits) / len(vals)) if vals else 0.0, len(vals)

    print("\n{:<18} {:>10} {:>10} {:>10}".format("", "A culprit", "B agent", "C both"))
    for label, hits in (("top-1", ("top1",)), ("top-5", ("top1", "in_set"))):
        a, na = rate("A", hits)
        b, nb = rate("B", hits)
        c, nc = rate("C", hits)
        print("{:<18} {:>9.0f}% {:>9.0f}% {:>9.0f}%".format(label, a, b, c))
    print("{:<18} {:>10} {:>10} {:>10}".format("n", na, nb, nc))

    reordered = [r for r in rows if r["C_reordered"] is not None]
    if reordered:
        kept = sum(1 for r in reordered if not r["C_reordered"])
        print("\narm C kept culprit's ranking in {}/{} cases".format(kept, len(reordered)))
    json.dump(rows, open(os.path.join(HERE, "results3.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
