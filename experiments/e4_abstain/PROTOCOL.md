# E4: can PMG load nothing for vague questions without hurting short ones?

Status: protocol written **before the rule was implemented or run**. The pass/fail rules are fixed.

## Problem

For a vague question ("so what do you think about all that?") PMG still loads whatever the few matching words happen
to hit: about 127 tokens per vague question on the real store, the same as for a real question. The goal is to load
nothing when nothing fits. The risk is the opposite error: loading nothing for a short question that was answerable.

## Rule under test (cheap, no LLM, opt-in `Memory.evidence_rule = (info_frac, rare_df)`)

After keyword matching, a chunk may be loaded only if it has **evidence**:

1. an *informative* query word is a word that appears in at most `max(rare_df, info_frac x N)` chunks (N = chunks
   ever stored; counted with a bounded query, so cost does not grow with the store);
2. a chunk has evidence if it contains at least **2 distinct informative query words**, or **1 informative word that
   appears in at most `rare_df` chunks** (a rare identifier, such as a name or a code).

If no chunk has evidence, nothing is loaded from search (standing instructions are unaffected).

Two settings are fixed in advance and each is run once: `(0.01, 5)` and `(0.01, 50)`.

## Data (synthetic, built by me; real store, N = 10,000, seed 1001)

E1 gym query types, plus one new type:

- A one specific fact, B broad question with 5 topic words, C facts from 2 or 3 topics: answerable, need known chunks
- D vague: 5 common words, half the time plus one topic word: the right action is to load nothing
- **E short question: exactly one topic word plus 0-2 common words, needing that topic's 3 key chunks.** This is the
  harm class: a legitimate short question that the rule could wrongly silence.

300 queries per type mix, as in E1, 150 of type E.

## Metrics

tokens loaded on D (want near 0); macro needed-chunk recall on A, B, C; recall on E; tokens on E.
Baseline = same store and queries with the rule off.

## Pass/fail rule (per setting; E4 adopts the passing setting with the fewest tokens, if any)

1. tokens on D at least 80% lower than baseline;
2. macro recall on A, B, C no more than 0.01 below baseline;
3. recall on E no more than 0.05 below baseline.

If neither setting passes, the rule is not adopted and the finding is that vague and one-word questions cannot be told
apart from word statistics alone.

## Known limits

- The gym is mine. A single-topic-word question has the same word statistics whether it is vague or short, so the gym
  encodes that ambiguity by construction. Real vague questions differ (pronouns, no nouns at all), and real short
  questions often have rarer words.
- Keyword matching only. A semantic signal (the top embedding similarity) could separate these cases better; that
  needs real embeddings.

## Outcome note (added after the run)

Neither setting passed, so the rule is not adopted (`Memory.evidence_rule` stays `None`, available as opt-in).
Setting (0.01, 5) cut tokens on vague questions by 89% (126 -> 14) with A/B/C recall unchanged, but recall on short
one-topic-word questions fell from 0.109 to 0.038 (limit: 0.05 below baseline). Setting (0.01, 50) kept short-question
recall but cut vague-question tokens by only 43%. As the protocol anticipated, a vague question with one topic word and
a short question with one topic word look the same to word statistics. The baseline recall on E is itself only 0.109,
because one word cannot find three specific chunks. The next test of this idea needs a semantic signal (top
embedding similarity) on real data.
