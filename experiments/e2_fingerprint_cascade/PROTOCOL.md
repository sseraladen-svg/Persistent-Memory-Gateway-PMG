# E2: does a binary-fingerprint cascade match exact retrieval with far less compute?

Status: protocol written **before any results were produced**. The pass/fail rules below are fixed.

## Question

Goal 2 says: retrieve only what is needed without checking everything. Exact dense retrieval compares the query with
every stored vector (N x d floats read per query). A cascade first compares the query with a short binary fingerprint
of every chunk (a few bytes each), keeps a small shortlist, and re-ranks only the shortlist with the full vectors.
Does the cascade return the same chunks, with much less work?

Inspiration: DNA similarity search (binding = cheap match) and neuromorphic event-driven sparsity (cheap check first,
spend effort only on survivors). The mechanism is ordinary random-hyperplane hashing (SimHash) plus re-ranking.

## Systems (same vectors for both)

| Id | System | Per-query work |
|---|---|---|
| B0 | Exact dense brute force: cosine of the query with all N vectors (d = 256, float32), top-10 | reads N x 1024 bytes |
| C | Cascade: `bits`-bit SimHash of every chunk, Hamming distance to all N, shortlist of R, exact cosine on the R, top-10 | reads N x bits/8 bytes + R x 1024 bytes |

Dense vectors are a random projection (d = 256) of TF-IDF vectors from the E1 gym. This is a stand-in for real
embeddings, not a replacement. Both systems use the same vectors, so the comparison isolates the cascade.

## Gym

The E1 gym (`experiments/e1_topology_router/gym.py`) at three store sizes: N = 2,000 (40 topics), 10,000 (200 topics),
50,000 (1,000 topics), 50 chunks per topic, 300 queries per seed. Query types A, B, C2, C3, D as in E1.
Needed-chunk recall uses the top-10 results.

## Procedure

1. Validation seeds 101, 102; test seeds 401, 402, 403. Different seeds give different gyms.
2. For each N, grid: bits in {64, 128, 256}, R in {20, 40, 80, 160, 320}. Choose on validation the configuration with
   the fewest bytes read per query whose validation overlap@10 with B0 is at least 0.95.
3. Evaluate the chosen configuration once on the test seeds. Nothing is tuned on test data.
4. Single thread (`OMP_NUM_THREADS=1`), one warm-up pass, median of per-query latencies. Query embedding time is
   excluded for both systems; fingerprinting the query is included for C.

## Metrics

- overlap@10: share of B0's top-10 that C also returns
- macro needed-chunk recall at top-10: mean of per-type recall for A, B, C (D has nothing needed)
- bytes read per query (implementation-independent) and median latency (ms)
- paired bootstrap 95% interval (2,000 resamples) of the recall difference C minus B0

## Pass/fail rule (primary: N = 50,000, test seeds)

E2 **passes** only if all hold:

1. mean overlap@10 with B0 is at least 0.95;
2. macro needed-chunk recall of C is no more than 0.01 below B0 (point estimate; interval reported);
3. bytes read per query are at most 25% of B0, **and** median latency is at most 50% of B0.

Otherwise E2 **fails** and the cascade is dropped from the design.

N = 2,000 and 10,000 are reported as scaling information and are not part of the rule.

## Known limits (stated up front)

- Random-projected TF-IDF vectors are not semantic embeddings. Real embeddings have different geometry, so overlap
  at a given `bits` and R may be better or worse. Needs a repeat with a real embedding model on the user's machine.
- The cascade still scans all N fingerprints, so its cost is **linear in N** (with a much smaller constant). It does not
  meet goal 14 (cost independent of store size). A sublinear index (buckets or a graph) would be a separate experiment.
- Latency is numpy on one core and depends on the machine; bytes read does not.
- B0 is the quality ceiling for this representation. E2 says nothing about whether the vectors are good retrieval.

## Changes made before the full run

A smoke run (N = 2,000 only, validation seed 101, test seed 301) was used to check that the code works. It exposed two
things, and the pass/fail rules above were not touched.

1. **Seen test data.** The smoke run printed results for test seed 301, so the test seeds were moved to 401-403, which
   have never been looked at (smoke runs now use seed 201).
2. **Disclosure.** In that smoke run, at N = 2,000, the best grid point reached overlap@10 of only 0.85 and was not
   faster than exact search. This was seen before the full run. The rule was left as written, so the overlap
   threshold of 0.95 may turn out to be strict for this geometry. If E2 fails on it, that is the result.
