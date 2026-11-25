# E8: can PMG notice, without an LLM, that a new note replaces an old one?

Status: protocol written **before the feature was implemented or run**. The pass/fail rules are fixed.

## Problem

Slot keys (`user.city`) only come from the optional LLM classifier. With the rule-based classifier, "the audit deadline
is March 10" is stored next to "the audit deadline is March 3", and retrieval can return the stale one. That breaks
goal 9 (correctness) and the promise that a changed fact replaces the old one.

## Feature under test (cheap, no LLM)

When a new note has no slot key, look at the 5 best keyword matches of the same kind. Replace one only if **all** hold:

1. the two notes differ only in numeric or month tokens (digits, dates, percentages, month names), at least one on
   each side;
2. the differing tokens come after every shared token (the value is at the end, as in "deadline is March 3");
3. at least 2 shared content tokens, and shared tokens are at least 60% of the shorter note.

The replaced text stays in the raw log (it is linked to the same chunk). Everything else is added as a new chunk as
before. Textual values ("the owner is Priya" -> "the owner is Ravi") are deliberately **not** handled: from words
alone, a changed name can equally mean a different slot, so that case is left to the LLM classifier's slot keys.

## Gym (synthetic, built by me)

150 invented entities x 24 attributes. Stream = initial facts, then updates, distractors and duplicates.

- tail-numeric slots (100): "E A is March 3" -> update "E A is March 10" (half of the updates insert "now": "E A is now March 10")
- middle-numeric slots (50): "E A is 5 million dollars" -> "E A is 7 million dollars"
- textual slots (50): "E A is Priya" -> "E A is Ravi"
- distractors that must NOT replace anything (150): same attribute for a different entity (50); same entity, different
  attribute (50); numbered slots, "E sprint 3 A is March 5" then "E sprint 4 A is March 5" (50)
- exact duplicates (50), handled by the existing duplicate merge

## Measured, baseline (`supersede` off) against feature (`supersede` on), same stream

- update recall per slot family: the new value is retrievable and the old value is gone (top-3 keyword matches for "E A")
- stale rate: share of updated slots whose old value still appears in the top-3
- false-replacement rate on distractors: a distractor fact that is no longer retrievable
- chunk count difference (must equal the number of replacements)

## Pass/fail rule

E8 **passes** only if all hold:

1. tail-numeric update recall (replaced) at least 0.45 (half the updates insert a filler word and are expected to be
   missed) and, among updates **without** the filler word, at least 0.9;
2. false-replacement rate over all 150 distractors at most 0.01;
3. stale rate for tail-numeric slots at least 80% lower than baseline for updates that were replaced;
4. the current value of every initial, non-updated fact is still retrievable (no collateral loss).

Otherwise E8 **fails** and the feature is not enabled by default.

## Known limits

- Templated text written by me: real phrasing varies more. The rule is built to prefer missing an update over losing a
  fact, and the numbers here only show that it behaves that way on this data.
- Textual updates, middle-numeric updates and "now"-style rewording are expected misses and are reported as such.

## Outcome note (added after the run)

The run failed criterion 1: only 2 of the 100 tail-numeric updates were replaced (the rule accepted 2 of 100 pairs;
6 pairs shared the month). The cause is in my rule 3: a changed date usually changes the month token too, and value
tokens counted in the denominator, so "Kavrotel deadline is April 10" against "... March 3" shared 2 of 4 tokens (0.5,
below 0.6) and was rejected. The safety criteria held (0 false replacements over 150 distractor pairs, no collateral
loss), so the rule is safe but far too strict. The rule was not edited here; a revised rule is registered as E8b with a
fresh seed. This run's code is the commit that contains this note.
