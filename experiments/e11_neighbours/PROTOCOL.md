# E11: does loading the turns next to a match find more of what a question needs, per token?

Status: protocol written **before the policy was implemented or run**. The rule below is fixed.

## Why

On real LoCoMo (E3/E5/E6) every policy plateaus: keyword top-20 (706 tokens) still finds only 68% of the needed
turns, and embeddings were worse. Many needed turns are short replies next to the turn that matches the question.
Hypothesis: adding the turn before and after each hit raises recall for fewer tokens than simply loading more hits.

## Policy under test (keyword search only, no LLM)

`top-k +-1`: take the k best keyword hits, add the previous and next message (by position in the conversation),
remove duplicates. Fixed grid, each run once, no tuning: k = 1, 2, 3, 5.

## Baseline

The keyword `top-k` curve from the same run (k = 1, 3, 5, 10, 20), linearly interpolated: the tokens a plain top-k
needs to reach the same recall as the policy.

## Data

LoCoMo `locomo10.json`, 1981 questions (same as E3). One run; nothing is tuned, so no held-out split. Result is for
LoCoMo only; LongMemEval is run afterwards and reported separately.

## Pass / fail

For each k, saving = 1 - tokens(policy) / tokens(plain top-k at the same recall).
**PASS** if at least 2 of the 4 settings save at least 10%. Otherwise FAIL. A setting whose recall falls outside the
top-k curve is reported as "cannot compare" and does not count as a pass.
No confidence interval is computed (point estimates over 1981 questions); a pass that is close to 10% is reported as
inconclusive, not as a win.

## If it passes

The policy is only a candidate: it must still be re-run on LongMemEval before `Memory.retrieve` changes, because
neighbouring turns may help LoCoMo's style of dialogue and not other data.

## Outcome note (added after the run; the rules above were not changed)

First run on the user's machine printed "FAIL (0 of 4)". That was an implementation bug, not the rule: the baseline
list in `pmg validate` also matched the new "top-k +-1" rows (names start with "top-"), so each setting was compared
with itself. The fixed code uses only plain top-1/3/5/10/20, as this protocol says, and has a test. Recomputed from the
same printed numbers (plain top-k: 0.316/39, 0.470/112, 0.539/183, 0.618/359, 0.684/706):

| setting | tokens / recall | plain top-k tokens at that recall | saving |
|---|---|---|---|
| top-1 +-1 | 109 / 0.470 | 112 | 3% |
| top-2 +-1 | 203 / 0.595 | 308 | 34% |
| top-3 +-1 | 297 / 0.650 | 527 | 44% |
| top-5 +-1 | 476 / 0.709 | above the curve (top-20 reaches 0.684 at 706) | cannot compare, does not count |

**PASS on the pre-registered rule (2 of 4, both far above 10%)** on LoCoMo only. Candidate, not adopted:
`Memory.retrieve` is unchanged until LongMemEval confirms it. E3 recomputed with the correct baseline is unchanged
(FAIL: 310 vs 305 tokens).
