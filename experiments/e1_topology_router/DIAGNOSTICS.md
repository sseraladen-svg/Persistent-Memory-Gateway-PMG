# E1 diagnostics

Descriptive checks run after the verdict. They do not change it.

## 1. Are chunks of the same topic closer together than chunks of different topics?

MST edge lengths (cosine distance) among the top-20 candidates, validation gyms.

| Edge type | Count | 5% | 25% | median | 75% | 95% |
|---|---|---|---|---|---|---|
| same topic | 17084 | 0.597 | 0.660 | 0.701 | 0.750 | 0.833 |
| different topics | 5669 | 0.835 | 0.890 | 0.907 | 0.928 | 0.959 |

Share of all MST edges at or below each gap threshold in the grid:

| gap | 0.6 | 0.7 | 0.75 | 0.8 | 0.85 | 0.9 | 0.95 | 1.0 |
|---|---|---|---|---|---|---|---|---|
| share of edges | 4% | 37% | 57% | 69% | 74% | 84% | 98% | 100% |

## 2. What the tuned P2 did with the clusters (target 0.90)

Chosen configuration: `{'floor': 0.0, 'm': 50, 'gap': 0.6, 'alpha': 0.3, 'beta': 0.8, 'cap': 3}`

- mean number of clusters it found: 47.0 out of 48.5 candidates
- queries where every candidate was its own cluster: 34%

If this is near 100%, the optimiser chose settings where clustering does nothing, and P2 reduces to a relative score cutoff like P1b.

## 3. Tokens versus recall on the test seeds

Each configuration is chosen on validation data for the target, then evaluated on test seeds.

| Target | P0 tokens / recall | P1b tokens / recall | P2 tokens / recall |
|---|---|---|---|
| 0.80 | 250 / 0.790 | 114 / 0.790 | 129 / 0.798 |
| 0.84 | 354 / 0.826 | 153 / 0.823 | 161 / 0.820 |
| 0.88 | 477 / 0.865 | 236 / 0.861 | 245 / 0.866 |
| 0.90 | 599 / 0.891 | 298 / 0.883 | 387 / 0.891 |
| 0.92 | 698 / 0.908 | 390 / 0.904 | 396 / 0.904 |
| 0.94 | 835 / 0.928 | 660 / 0.936 | 400 / 0.906 |
| 0.95 | 932 / 0.936 | 660 / 0.936 | 400 / 0.906 |

## 4. Vague (type D) questions

- median top score on vague questions: 0.257; on answerable questions: 0.395
- P1b at target 0.90 injects 920 tokens on average for vague questions, which is the most expensive query type and returns nothing useful.
