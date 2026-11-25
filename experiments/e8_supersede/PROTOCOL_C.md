# E8c: replace a note when its trailing value changes, with the value treated as one unit

Status: written **before the change was implemented or run**. Follows E8 and E8b (see their outcome notes).

## Why

E8b missed because "March 18" -> "December 18" changes the month but keeps the day, and rule 2 (changed tokens must come
after every shared token) rejects it. The filler word "now" ("deadline is now March 10") was also rejected on purpose.

## The rule (replaces the E8b rule)

Work on the lowercase tokens of each note, stopwords kept. Let the **value run** be the maximal run of number, date
or month tokens at the very end of the note. Replace an older note of the same kind (found among the 5 best keyword
matches) only if **all** hold:

1. both notes have a non-empty value run, and the runs are different;
2. the token just before the value run, skipping filler words (`now currently updated update changed new actually`),
   is one of `is are was to at be` (the value is being assigned);
3. everything before the value run, with stopwords and filler words removed, is **identical** in both notes (same
   tokens, same order) and has at least 2 tokens.

So a changed entity, attribute, "sprint 3" -> "sprint 4", "for 2025" -> "for 2026" or "week 3" -> "week 4" all fail
rule 3 or rule 2. Textual values and values followed by a unit ("5 million dollars") have no value run and are not
handled.

## Data

Same gym and metrics as E8b with a **fresh seed (903)**: 100 tail-numeric updates (half with "now"), 50 middle-numeric,
50 textual, 150 original distractor pairs (different entity, different attribute, "sprint 3/4"), 50 year-slot pairs,
plus 50 new "week" pairs ("E A is March 5 for week 3" then "... for week 4"), and 50 exact duplicates. One run.

## Pass/fail rule

E8c **passes** only if all hold:

1. at least 0.9 of all 100 tail-numeric updates are replaced (new value shown, old value gone), including those with "now";
2. false replacements over all 250 distractor pairs (150 + 50 year + 50 week) at most 0.01;
3. no distractor fact and no non-updated fact is lost;
4. the old message stays reachable from the chunk (checked in unit tests, not in the run).

Otherwise E8c fails, the feature stays off, and no further tuning on this gym is done: the next step is real data.

## Known limits

Templated text written by me. Last-write-wins: a stale message re-sent after its update replaces the update (this
happens twice in the gym through the duplicates and is counted against criterion 1, as in E8b).

## Outcome note (added after the run)

E8c **passed** on seed 903: 0.95 of all 100 tail-numeric updates were replaced (0.92 of the plain ones), with 0 false
replacements over 250 distractor pairs (different entity, different attribute, "sprint 3/4", year slots, week slots)
and no collateral loss. The rule accepted all 100 pairs; the 5 updates counted as misses are all the gym re-sending the old message after its update (checked one by one), which last-write-wins correctly applies. Decision: the feature is
enabled by default (`Memory.supersede = True`) with the caveats below, since the replaced text always stays in the raw
log. Not handled, by design: textual values and values followed by a unit. The caveat that matters: the data is
templated text written by me, and real phrasing is messier, so this is a conservative rule, not a proven one.
