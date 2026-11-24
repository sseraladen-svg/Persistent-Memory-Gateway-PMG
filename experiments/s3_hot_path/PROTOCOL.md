# S3: can the real request path stay fast as the store grows?

Status: protocol written **before the changes were implemented or measured**. The pass/fail rules are fixed.

## Why this exists

S1 and S2 timed `Memory.retrieve(..., log=False)`. The product (proxy and MCP) calls it with `log=True`, which also
(a) sums the token size of **every stored chunk** (`SELECT SUM(...) FROM chunks`, a full scan, once per request) and
(b) writes usage counters and an event row with a commit. Reading the code shows (a) is O(N), so S1 and S2 understated
the real cost. S3 measures the path users actually run.

## Compared

| Label | Code | Settings |
|---|---|---|
| baseline | commit `a5f6b2e` (before any S3 change) | `common_df = 0`, as shipped |
| new | working tree after S3 changes | `common_df = 2000`, deferred usage writes, running token total |

S3 changes (to be implemented after this protocol is committed to the file system):
1. a running total of stored tokens kept in a `meta` table by SQL triggers, so the sum is O(1);
2. usage counters and event rows are buffered in memory and written in batches (every 25 requests or 2 seconds,
   whichever comes first, plus on `stats()`, `list()` and process exit), so a request does not wait for a commit;
3. word pruning from S2 (`common_df = 2000`) switched on for the "new" run.

## Setup

Bulk-loaded stores of 1,000 / 10,000 / 100,000 chunks from the E1 gym, 300 queries each, **fresh seed 801**, each
query run with `log=True`, 20 warm-up queries, one core. Both trees are measured by the same script on the same
generated data.

## Metrics

median and p95 latency per request; macro needed-chunk recall over query types A, B, C (needed chunk counts if it is
in the returned chunk list); tokens injected; stored-token total correctness (stats must equal a fresh full sum).

## Pass/fail rule (the "new" tree)

S3 **passes** only if all hold:

1. at N = 100,000 median and p95 latency are at most 50 ms;
2. median latency grows by at most 3x from N = 10,000 to N = 100,000;
3. macro needed-chunk recall is no more than 0.01 below baseline at every N;
4. tokens injected never exceed the budget, and the running token total equals a full recount;
5. no usage counters or events are lost: after a flush, the event count equals the number of logged requests.

Otherwise S3 **fails**. On a fail the changes that did not cause it may stay, but pruning stays off by default.

## Known limits

- Synthetic text from a generator I wrote; the 2,000 threshold was set knowing its structure (see S2).
- A crash can lose up to 25 buffered requests of usage statistics (never memories).
- Another process sees buffered statistics up to 2 seconds late.

## Outcome note (added after the run)

The run missed criterion 2 (growth from 10,000 to 100,000 chunks was 4.4x against a limit of 3x); every other criterion
passed. As the rule says, the changes that did not cause the failure stay and pruning stays off by default. A
descriptive ablation (same code, pruning off) gave medians of 1.55 / 4.35 / 33.2 ms at 1k / 10k / 100k, against the
baseline's 3.06 / 7.54 / 60.1 ms: the running total and batched writes account for roughly a 1.8x speedup, and pruning
for a further 2.4x at 100,000 chunks. The rule was not edited after seeing the result.
