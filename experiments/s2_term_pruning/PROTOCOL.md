# S2: does dropping very common query words keep retrieval time flat without losing details?

Status: protocol written **before the change was implemented or measured**. The pass/fail rules are fixed.

## Background

S1 failed: median retrieval time on the real store was 5.6 ms at 10,000 chunks and 34.2 ms at 100,000 (p95 72 ms).
About 63% of the time was the FTS5 query, which matches chunks containing *any* query word, so a word that appears in
thousands of chunks forces a scan of a long list. Those words carry almost no information about what the user wants.

## Change under test

Before searching, each query word is checked against the index: if it appears in more than `common_df` chunks
(default 2,000) it is dropped from the search. If every word is dropped, the search stage returns nothing (the
always-loaded behavior chunks are unaffected). The check is bounded (it stops counting at `common_df + 1`) and cached
per word. A second, independent change: SQLite `synchronous=NORMAL` (standard in WAL mode) so the usage-counter write
that happens on each retrieval is cheaper.

`common_df = 0` switches the change off, which gives the baseline on the identical store and queries.

## Setup

Same bulk-loaded stores as S1 (E1 gym text, Zipf word frequencies), sizes 1,000 / 10,000 / 100,000, 300 queries each.
**Fresh seed 601** (S1 used 501). One threshold (2,000), no tuning grid, one run. Disclosure: I chose 2,000 knowing the
gym's structure (common words appear in thousands of chunks, topic words in dozens), so the gym is favourable to this
rule; real text needs the same check on real data.

## Metrics

- median and p95 `Memory.retrieve` latency, pruning on and off
- macro needed-chunk recall over query types A, B, C (a needed chunk counts if it is in the retrieved chunk list;
  at most 6 chunks are returned)
- mean tokens injected, and for vague queries (type D) tokens injected
- tokens always within the 400-token budget

## Pass/fail rule

S2 **passes** only if all hold:

1. at N = 100,000 with pruning on, median and p95 latency are at most 50 ms (the S1 criterion);
2. median latency grows by at most 3x from N = 10,000 to N = 100,000 (the S1 criterion);
3. macro needed-chunk recall with pruning on is no more than 0.01 below pruning off (same store, same queries), at
   every N;
4. tokens injected never exceed the budget.

Otherwise S2 **fails** and the change is reverted.

## Outcome note (added after the run)

The run missed criterion 2 (see RESULTS.md), so per the rule above the change is not adopted: pruning is off by
default (`COMMON_TERM_DF = 0`, available as `Memory.common_df`) and the `synchronous=NORMAL` setting was removed. The
rule was not edited after seeing the result.

## Known limits

- Synthetic text. Real words follow less clean frequency patterns; a legitimate query made only of common words (for
  example "project status" in a store full of project notes) would return nothing from search.
- The `uses` write still happens on every retrieval; only its commit cost is reduced.
