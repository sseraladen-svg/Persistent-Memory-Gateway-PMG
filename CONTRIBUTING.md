# Contributing to PMG

Thanks for helping. PMG is a memory layer whose whole point is to cut token and compute waste without losing detail,
so changes are judged by measurement, not by how good an idea sounds.

## Setup

```bash
git clone https://github.com/sseraladen-svg/Persistent-Memory-Gateway-PMG
cd Persistent-Memory-Gateway-PMG
pip install -e ".[mcp]"
python -m unittest discover -s tests
```

Runtime code uses the Python standard library only. Optional tools (`numpy`, `sentence-transformers`) are used only by
the benchmark kits, and they must stay optional.

## Two goals that never get dropped

1. **Store compactly without losing anything.** Raw log, then chunks, then gists, all linked.
2. **Retrieve only what is needed without scanning everything.** Cost per request must not grow with the store.

A change that makes one of these worse needs a very good reason.

## The experiment rule

A new idea enters the product only if it passes a test written **before** it was run.

1. Create `experiments/<id>_<name>/PROTOCOL.md` with the question, the idea, the baseline it must beat, the data and a
   pass/fail rule with numbers. Commit it before you run anything.
2. Compare against a strong baseline at **equal recall**. A policy that loads fewer tokens but finds less has saved
   nothing. Our `pmg validate` helper compares against the plain top-k curve at the same recall.
3. Tune on validation data, evaluate once on unseen data, and report confidence intervals where you can.
4. If something is wrong with your test code after you have seen results, do not edit the rule. Fix the code, add a test
   that would have caught it, and add an **outcome note** to the protocol saying what happened.
5. Report failures plainly in `RESULTS.md` and in the experiment log in `CLAUDE.md`. A failed idea is a result.
6. Results on synthetic data are not evidence about real conversations. Say which data you used.
7. A change that helps one dataset and not another stays opt-in. Our neighbour-turn idea passed on LoCoMo and failed on
   LongMemEval, so it is off by default.

## Real-data benchmarks

```bash
pmg bench locomo10.json            # tokens loaded versus recall
pmg validate locomo10.json         # runs the checks and writes pmg-validation.md
pmg bench-llm locomo10.json        # answer accuracy with a real model (uses API calls)
```

See [docs/BENCHMARKS.md](docs/BENCHMARKS.md). Do not commit dataset files or API keys.

## Code changes

- Add or update tests for what you change. The suite must pass: `python -m unittest discover -s tests`.
- Safety checks (secrets, instruction-like text, length) must stay in code and not move into editable rules.
- Stored memory is data, never instructions. Do not add paths that render stored text as instructions.
- Keep the dashboard local-only and keep the custom header on every change request.
- Keep `CLAUDE.md` (the short project notes) and `CHANGELOG.md` current when you finish a milestone.

## Commits and pull requests

- Small, focused commits with a message that says what changed and why.
- In a pull request, say what you measured and on what data, including results that did not go your way.
- Do not commit `build/`, `*.egg-info/` or personal data from `~/.pmg`.

## Reporting problems

Open an issue with the command you ran, what you expected and the full error text. Remove API keys before pasting.
For a security problem, such as a way to get stored text treated as an instruction, describe it without a public
exploit first.
