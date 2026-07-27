# Does culprit help a coding agent, or can the agent just do it?

An agent with bash can run `git blame` itself. So the question worth answering is
not "is culprit accurate" (that is `benchmarks/run.py`) but "does culprit beat, or
help, an agent that has git and no culprit".

Three arms, same 10 regressions, same scoring rules:

| Arm | What it is |
|---|---|
| **A** | culprit alone |
| **B** | an agent alone (Claude Opus, full bash and git, no culprit) |
| **C** | the same agent, given culprit's ranked output first |

## Result

| | A: culprit | B: agent | C: agent + culprit |
|---|---|---|---|
| Introducing commit ranked #1 | 80% | **90%** | **90%** |
| Introducing commit in top 5 | 90% | **100%** | **100%** |

Cost, over the 9 cases where both agent arms ran the same problem:

| | B: agent | C: agent + culprit | change |
|---|---|---|---|
| mean tokens | 55,639 | 48,014 | **-14%** |
| mean tool calls | 15.0 | 8.9 | **-41%** |

culprit itself takes no tokens and under a second.

**The agent beats culprit on accuracy, and culprit does not make the agent more
accurate. What it does is get the agent to the same answer in about half the
steps, in 9 of 9 cases with no reversals.** On the hardest case the agent needed
42 tool calls alone and 16 with culprit.

culprit is an accelerator for an agent, not a replacement for one. Any claim that
it finds root causes better than a capable agent is not supported by this data.

The agent is not merely deferring to the tool: arm C reordered culprit's ranking
in 7 of 10 cases, and on case 04, where culprit's top suspect was wrong, the agent
rejected it and found the right commit by running `make -qp` to compare the
default goal at HEAD and at its parent. Empirical evidence of that kind is
something a history-only engine cannot produce.

## Fairness

The ground truth is each fix's `Fixes:` trailer, so an agent that can reach the
fix commit can simply read the answer. Every case therefore gets a sandbox: a
`--shared` clone rewound to the fix's parent, with every other ref, the remote,
and the reflog removed. Verified per sandbox: the fix is not an ancestor of HEAD,
only one ref exists, searching all reachable history for the expected SHA returns
nothing, and the introducing commit *is* still reachable so the case remains
solvable.

Both arms get the same input. `pr_context.from_local` passes culprit the diff with
`title=None, body=None`, so the agent is given the diff and nothing else about the
fix. Agents are told not to search the web, since the real fix is public.

Both arms are scored by `benchmarks/run.py`'s own `score_case`, so no arm gets a
friendlier judge, and culprit is re-run on the same 10 cases rather than compared
against its full-50 average.

## Limits

- n=10. The direction is consistent but the sample is small.
- This slice is easier than the full dataset: culprit scores 80% here against 50%
  on all 50 cases, so the absolute numbers flatter every arm. Only the comparison
  between arms is meaningful.
- Cases 26 and 27 share an introducing commit, so they are not independent.
- Arm B never fell below top 5, so there is no evidence here that culprit rescues
  an agent that would otherwise have failed.
- Only suspect finding was measured. `verify_fix`, the pre-commit completeness
  gate, is untested by this benchmark.

## Reproducing

```bash
python benchmarks/agent/setup.py 10 0   # build isolated sandboxes for 10 cases
```

Then run an agent per sandbox. Give it `sandboxes/caseNN/repo` and
`sandboxes/caseNN/fix.diff`, and for arm C also culprit's output, and have it write
`{"suspects": ["<sha>", ...]}` to `answers_b/caseNN.json` or `answers_c/caseNN.json`.

```bash
python benchmarks/agent/score.py       # score all three arms
```

`results.json` holds the run reported above, including per-case token and tool-call
counts.
