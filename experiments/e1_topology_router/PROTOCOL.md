# E1: does topology-aware routing cut tokens at equal detail recall?

Status: protocol written **before any results were produced**. The pass/fail rules below are fixed.

## Question

After retrieval returns the top-50 candidate chunks, a router decides how many to put in the prompt. Does a router
that first looks at the *shape* of those candidates (clusters of related chunks) inject fewer tokens than routers that
only look at scores, while still delivering the details the question needs?

"Topology" here means the H0 part of persistent homology. For a point cloud, the H0 features are exactly the merge
heights of single-linkage clustering, which equal the edge lengths of a minimum spanning tree (MST). H1 (loops) is not
tested. Inspired by <https://arxiv.org/html/2406.07990v2>, which measures ambiguity this way but reports no retrieval
results.

## Routers compared (same retrieval scores for all)

| Id | Router | Tunable parameters |
|---|---|---|
| P0 | Fixed top-k | k |
| P1 | Margin gate: if the top score clearly leads, inject 1 chunk; otherwise top-k fallback; nothing if the top score is below a floor | floor, margin, fallback k |
| P1b | Global relative cutoff: keep chunks scoring at least beta times the top score | floor, beta, max k |
| P2 | Topology router: cut the MST of the top-m candidates into clusters; keep clusters whose best score is at least alpha times the top score; inside each kept cluster apply a relative cutoff and a per-cluster cap | floor, m, gap threshold, alpha, beta, per-cluster cap |

P1b is the strong baseline. P1 and P0 are the cheap ones.

## Gym (synthetic, ground truth known)

Chunks: 40 topics x 50 chunks, three "key" chunks per topic. Four query types with known needed chunks:

- A: one specific fact (needs 1 chunk)
- B: broad question about one topic (needs the 3 key chunks)
- C: facts from 2 or 3 different topics (needs 1 chunk per topic)
- D: vague question with no needed chunk (the right action is to inject nothing)

Retrieval is plain TF-IDF cosine, so the experiment tests **routing structure**, not semantic matching.

## Procedure

1. Validation seeds 101-103 and test seeds 301-305 (see "Changes made before the full run"). Seeds generate different gyms.
2. For each router, evaluate configurations on validation. P0, P1 and P1b are searched exhaustively over their grids.
   P2 gets a random sample of 600 configurations from a larger grid (so it is not favoured by search effort).
   A sensitivity run gives P2 more configurations.
3. For each recall target R in {0.85, 0.90, 0.95}, choose per router the configuration with the fewest mean tokens
   whose validation macro recall is at least R (if none qualifies, the highest recall).
4. Evaluate the chosen configurations once on the test seeds. Nothing is tuned on test data.

## Metrics

- tokens injected per query (chunk text tokens, about 4 characters each, plus 2 per chunk)
- macro recall: mean of per-type recall for types A, B, C (recall = needed chunks injected / needed chunks)
- waste ratio: injected tokens that were not needed / injected tokens
- abstention rate on D: share of vague queries where nothing was injected
- router overhead: median milliseconds and distance computations per query

## Pass/fail rule (primary: R = 0.90, P2 against the best baseline chosen on validation)

E1 **passes** only if all three hold on the test seeds:

1. P2 uses at least 10% fewer mean tokens than the best baseline, and the 95% paired-bootstrap interval of the
   difference excludes 0.
2. P2's macro recall is no more than 0.01 below the baseline's (non-inferior).
3. Median router overhead (MST on the chosen m) is at most 10 ms per query in this pure-Python implementation.

Otherwise E1 **fails**, and topology routing is dropped from the design unless a later experiment on real embeddings
and real data says otherwise.

## Known limits (stated up front)

- The gym is my own generator. It encodes my assumptions about what queries look like. A pass here shows the
  mechanism can work, not that it helps in practice.
- Word-count vectors have no semantics. Real embeddings have different neighbourhood shapes, which could help or hurt.
- A and D queries are included on purpose because topology should not help there, so they test for harm.
- Results must be repeated with real embeddings and real conversations before any claim is made.

## Changes made before the full run

A smoke run (validation seed 101, test seed 201, 40 configurations per router) was used only to check that the code
works. It showed two problems in my own setup. Both were fixed before the full run, and the pass/fail rules above
were not touched.

1. **Unequal grids.** P1 and P1b could inject at most 20 chunks while P0 could inject 30, which handicapped the
   baselines. Every router may now use up to the full pool of 50 candidates. This can only help the baselines, so
   it is conservative against P2.
2. **Seen test data.** The smoke run printed results for test seed 201, so the test seeds were moved to 301-305,
   which have never been looked at.
