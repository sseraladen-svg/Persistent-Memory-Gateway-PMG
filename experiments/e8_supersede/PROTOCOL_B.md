# E8b: the supersede check with the shared-token rule measured on content words

Status: written **before the change was implemented or run**. Follows E8 (see PROTOCOL.md and its outcome note).

## What changes from E8

Only rule 3. E8 compared shared tokens with all tokens of the shorter note, so a changed month counted as a
difference. E8b measures it over **content tokens only** (tokens that are not numbers, dates or months):

3. at least 2 shared content tokens, and shared content tokens are at least 60% of the content tokens of the shorter
   note.

Rules 1 and 2 are unchanged: the notes differ only in numeric/month tokens, with at least one on each side, and the
differing tokens come after every shared token.

## Everything else

Same gym, same metrics, same pass/fail criteria as E8. The only difference in data is a **fresh seed (902)**, because
seed 901 was seen when the problem was found. One run.

## Additional guard check (reported, not a criterion)

Because loosening the rule could admit false replacements, the false-replacement rate is the criterion to watch
(at most 0.01 over 150 distractor pairs, unchanged). An extra 50 distractor pairs of a new kind are added and reported
separately: "year" slots ("Kavrotel budget for 2025 is 5" then "... for 2026 is 5"), where the number sits in the
middle and rule 2 should reject them.

## Known limits

Same as E8: templated text written by me; real phrasing varies more; textual changes ("owner is Priya" -> "owner is
Ravi") are deliberately not handled.

## Outcome note (added after the run)

E8b failed criterion 1 narrowly: 0.42 of all tail-numeric updates were replaced (needed 0.45) and 0.84 of the plain ones
(needed 0.9). The safety criteria held again: 0 false replacements over 150 distractor pairs and 0 over the 50
year-slot pairs, with no collateral loss. Descriptive diagnosis of the misses among the 50 plain updates: 6 were
changes where only the month changed and the day stayed ("March 18" -> "December 18"), which rule 2 rejects because a
shared token (the day) comes after the changed one; 2 more were an artifact of my gym (an old message re-sent after its
update replaced the update, which is last-write-wins). The rule was not edited after the run; the feature stays off by
default. A possible E8c would treat the trailing run of value tokens as one unit ("March 18" vs "December 18").
