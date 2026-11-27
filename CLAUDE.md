# CLAUDE.md — project memory for PMG

Read this first in every session. It replaces re-reading the whole conversation. Keep it short and current: update the
"Status" and "Experiment log" sections at the end of every milestone, and commit the change.

## What this project is

PMG (Persistent Memory Gateway) is a **memory layer, not a chatbot**. It sits between the user and any AI tool
(Claude, ChatGPT, OmniRoute/OpenRouter) as an MCP server and an OpenAI-compatible proxy. It stores information as
small chunks, uses rules and retrieval to load only what a prompt needs, and injects that into the prompt.
An LLM is used only to analyze, classify and tune rules, never to chat.

## The end product (what the user should experience)

- Install once; every chat in any tool behaves as if the AI remembers everything, while sending only a few hundred
  tokens of memory per question.
- Remembers across chats and tools; switching Claude -> ChatGPT mid-project loses nothing.
- Sends only what matters; sends nothing for vague questions.
- Never loses detail: gists for speed, raw text always kept underneath.
- Stays current: a changed fact replaces the old one (slot keys), it is not stacked.
- Private, local-first, user-deletable; stored memory is treated as data, never as instructions.
- Visible: a dashboard shows tokens loaded, saved, unused, and time per query; every chunk and rule is editable.
- Setup in minutes, no services.

## Goals (never drop the first two)

1. **Store compactly without losing anything**: fewest tokens spent on storing, no context lost
   (three levels: raw log -> chunks -> gists, linked by chunk ID).
2. **Retrieve only what is needed without scanning everything**: index + cheap-first cascade + relative cutoff;
   cost must not grow with store size.
3. Fewer tokens and less compute per question. 4. Faster responses. 5. No forgotten details.
6. Efficient output from what the MCP ingests. 7. Works across Claude, ChatGPT, OmniRoute/OpenRouter.
8. Private/local-first. 9. Correct (provenance, contradictions, retrieve nothing when nothing fits).
10. Safe from prompt injection via stored content. 11. Portable. 12. Easy setup. 13. Visible and controllable.
14. Cost independent of store size. 15. A cost ledger so every claim is measured.

The aim is **not** a top benchmark score. It is the best practical reduction of token and compute waste, with speed
and no forgotten details. Benchmarks (LoCoMo, LongMemEval, BEAM) are sanity checks only; scores are self-reported
and not comparable across systems.

## Four layers (layer 1 matters most)

1. Data classification and storing as chunks. 2. Rules for what to access. 3. Retrieving exactly what the prompt
needs. 4. Ingestion: what to add for output quality.

## Repository layout

- `pmg/`: `embed.py`/`ann.py`/`bench_llm.py` (kits, run on the user's machine), `store.py` (SQLite + FTS5 chunks, slot keys, events), `rules.py` + `rules.default.json`, `classify.py`,
  `llm.py`, `mcp_server.py` (works on mcp 1.x FastMCP and 2.x MCPServer), `proxy.py` (stdlib OpenAI-compatible),
  `dashboard.py` + `web/index.html`, `cli.py`, `config.py`, `textutil.py`, `ledger.py` (time/tokens/ops per stage).
- `tests/`: unit and interface tests (119 passing). `CONTRIBUTING.md`, `docs/HOW_IT_WORKS.md` (diagrams also in README). `docs/INTEGRATION.md`. `legacy/`: the original chat app.
- `experiments/e1_topology_router/`, `e2_fingerprint_cascade/` and `s1_scale/`, `s2_term_pruning/`, `s3_hot_path/`, `e8_supersede/`, `e11_neighbours/`: PROTOCOL.md, engine.py, run.py,
  diagnose.py, RESULTS.md, DIAGNOSTICS.md (E2 reuses the E1 gym; both have an `engine.py`, so load one by path).

## Commands

- Tests: `python3 -m unittest discover -s tests`
- E1 full run: `python3 experiments/e1_topology_router/run.py --sensitivity 1500` (about 1 minute)
- S1 scale run: `python3 experiments/s1_scale/run.py` (about 20 seconds)
- E2 full run: `python3 experiments/e2_fingerprint_cascade/run.py` (about 45 seconds; numpy is available)
- The cloud workspace has **no network for pip/npm**; use the standard library only. Heavy runs (real embeddings,
  benchmarks) must run on the user's machine.

## Git rules (standing instructions from the user)

- Push directly to `main`; no new branch, no PR.
- Commit author: name `sseraladen-svg`, email `sseraladen@gmail.com`, so commits count on the contribution graph.
- Session hook requires committer `Claude <noreply@anthropic.com>`:
  `GIT_AUTHOR_NAME=sseraladen-svg GIT_AUTHOR_EMAIL=sseraladen@gmail.com GIT_COMMITTER_NAME=Claude GIT_COMMITTER_EMAIL=noreply@anthropic.com git commit ...`
- End commit messages with the attribution trailers given by the session.
- Do not commit `build/` or `*.egg-info/` (gitignored).

## Experiment rules

- Every idea (borrowed or ours) enters the design only if it passes a **pre-registered** test against a strong baseline.
  Write the protocol and pass/fail rule before running; tune on validation seeds, evaluate once on unseen test seeds;
  report CIs; record any change made before the full run.
- Report failures plainly. Do not call a result a win if recall is not equal.
- Synthetic-gym results are not evidence about real embeddings or real conversations.

## Architecture decisions so far

- Keep: relative score cutoff (P1b) instead of fixed top-k (about 50% fewer tokens at similar recall on the
  synthetic gym; needs confirming on real data).
- Planned: three-level lossless storage; an append-only raw log with chunk byte offsets (idea kept from the user's
  MicroTQ sketch, which has no question-to-ID step and so does not solve retrieval); cheap-first ingestion;
  information-per-token packing; ADD/UPDATE/DELETE/NOOP ingestion;
  waste-driven learning loop (waste = tokens loaded but never used); memory is data, not instructions.
- Dropped: topology-aware routing (E1 failed); flat SimHash fingerprint scan + rerank as the first stage (E2 failed:
  at N=50k it needed about 20% of the store as shortlist to reach 0.95 overlap and was no faster than exact search).
  A sublinear index (buckets or a graph) is still open and would be a new, separately registered experiment.

## Status

- Done and pushed to main: package restructure, MCP server, proxy, dashboard, CLI, docs, CI, cost ledger, E1, E2.
- Layer 1 storage done: append-only raw log (`raw` table, every non-secret message kept verbatim, linked to chunks),
  gists as a fallback when a chunk does not fit the budget, `memory_expand` tool, in-place DB upgrade, retrieval time
  in the dashboard. `forget` also deletes the linked raw messages (user-deletable).
- Safety (tests in `tests/test_safety.py`): instruction-hijack text and secrets are refused by every door
  (`classify.unsafe_reason`, patterns live in code, not the editable rules); memories over 400 chars are refused;
  rendering is one line per memory. Residual risk: a poisoned model could still store a harmless-looking but false
  fact or a polite standing instruction via `memory_remember`; the dashboard lets the user review and delete.
- Concurrency (tests in `tests/test_concurrency.py`): writers take the lock first (`BEGIN IMMEDIATE`); rules file is
  written atomically. Threads and separate processes tested.
- Hot path (tests in `tests/test_hot_path.py`): running token total via SQL triggers (`meta` table), usage counters and
  events buffered and flushed every 25 requests / 2 s / on stats(), list() and exit (a crash can lose up to 25 requests of
  statistics, never memories). Word pruning stays opt-in (`Memory.common_df`, 2000 tested).
- `pmg bench FILE` (pmg/bench.py, docs/BENCHMARKS.md): real-data measurement of tokens loaded vs recall for top-k, relative
  cutoff and the product policy; adapters for LoCoMo and LongMemEval are written from the known layouts and NOT yet run
  on the real files (the cloud workspace cannot download them). The user runs it on their machine.
- Waste estimate (`pmg/waste.py`, proxy only): after each reply the proxy checks whether the loaded *matched* chunks had
  >=30% of their key words echoed in the reply; counters live in the `meta` table and `stats()` reports `echo_percent`.
  This is an ESTIMATE (a fact can be used without being repeated, and the reverse), never validated against real model
  answers. Validate it on the user's machine before using it to tune rules. Standing instructions are not counted.
- The MCP path has no reply to look at, so waste is not measured there.
- Known weakness: keyword (FTS5) retrieval finds paraphrases poorly (hit@3 = 17% on a small test). Embeddings and
  hybrid retrieval are needed.

## Experiment log

| ID | Question | Result |
|---|---|---|
| E1 | Does topology (H0/MST) routing cut tokens vs score-only routers at equal recall? | FAIL. At R=0.90: P0 599 tok / 0.891, P1b 298 / 0.883, P2 387 / 0.891. Tuned gap was 0.6 so clusters did nothing; relative cutoff is the useful part. |
| S1 | Does retrieval cost stay flat as the store grows (real `Memory.retrieve`, FTS5)? | FAIL. Median 4.0 / 5.6 / 34.2 ms and p95 5.4 / 10.6 / 72.4 ms at 1k / 10k / 100k chunks. Tokens injected stayed flat (about 125-139, max 168 of 400). About 63% of the time is the FTS5 query (OR over all query words, so common words scan long lists), the rest is ranking and the usage-counter write on every retrieval. Candidate fixes (separate registered experiment): drop very common terms from the query, move the usage write off the hot path. |
| S2 | Does dropping query words found in >2000 chunks keep latency flat at 100k without losing details? | FAIL on the growth rule only: median 2.8 / 4.4 / 14.9 ms (1k / 10k / 100k) with pruning vs 2.4 / 5.3 / 41.7 off; p95 at 100k 22.5 vs 92.7 ms; recall identical (0.737 vs 0.737); growth 10k->100k 3.4x (limit 3x). Per the pre-set rule it is NOT adopted: `Memory.common_df` stays 0 (opt-in). The remaining 15 ms at 100k is the FTS query on rare words, ranking and the usage write. |
| S3 | Does the real request path (`log=True`, which S1/S2 did not time) stay fast with a running token total, batched writes and pruning? | FAIL on growth only: median 1.7 / 3.1 / 13.9 ms and p95 19.4 ms at 100k vs baseline 3.1 / 7.5 / 60.1 ms (p95 102); recall equal (0.736 vs 0.733); no events lost; totals exact; growth 10k->100k 4.4x (limit 3x). S1 and S2 had understated cost: the logged path summed every chunk per request (O(N)). Per the rule the two safe changes stay; pruning stays off. Ablation without pruning: 1.6 / 4.4 / 33.2 ms. |
| E8 / E8b / E8c | Can a cheap rule (no LLM) replace an outdated note when only the trailing value changes? | E8 FAIL (2/100 replaced: rule counted the changed month as a difference). E8b FAIL (0.42; month-only changes rejected; 0 false replacements). **E8c PASS** (seed 903, value run treated as a unit, identical prefix + "is/are/was/to/at/be" cue): 0.95 of 100 tail-numeric updates replaced (the 5 misses are the gym re-sending the old message after the update, i.e. last-write-wins), 0 false replacements over 250 distractor pairs (other entity, other attribute, sprint 3/4, year slots, week slots), no collateral loss. Adopted: `Memory.supersede = True` by default; the replaced message stays in the raw log. Not handled: textual values (need LLM slot keys) and values with units. Templated data: real phrasing is messier. |
| E3 | Does the relative cutoff load >=10% fewer tokens than top-k at equal recall on real data (LoCoMo, 1981 questions, keyword search only)? | NOT ADOPTED. The script printed PASS (14% vs top-10) but that compared against a top-k with higher recall (0.618 vs 0.594). Interpolating the top-k curve gives about 305 tokens at 0.594 vs cutoff 310: no saving (cutoff 0.3: ~3%, cutoff 0.7: none). Cutoff and top-k sit on the same curve on real data; the synthetic-gym 50% saving did not transfer. Main finding: keyword recall is low (top-20 only 0.684, 706 tokens); loading 1-3% of full history (20555 tokens). Product policy: 218 tokens, recall 0.559. Next: embeddings run. |
| E5 / E6 | On real LoCoMo (1981 questions, all-MiniLM-L6-v2), do embeddings or hybrid (RRF) beat keyword search at equal tokens? And does an IVF index keep exact-search overlap while scanning little? | FAIL for both embeddings and hybrid. Keyword top-10 359 tok / 0.618; emb top-10 295 / 0.428; emb top-20 591 / 0.518; hybrid top-10 314 / 0.549 (keyword reaches 0.549 at about 205 tokens). Embeddings were WORSE than keywords, and RRF fusion pulled keyword down. Code alignment (chunk id = index+1) reviewed, no bug found, but not independently verified. One small model only. Embedding path 30 ms vs 7 ms. IVF (76 lists, pooled ~5.8k vectors): overlap@10 0.905 at 7.3% scanned, 0.960 at 12.6%, 0.984 at 23.5%; says nothing yet about scaling. Likely cause of low recall for every policy: LoCoMo evidence turns are short and often not similar to the question (multi-hop, temporal). Idea (unregistered): load neighbouring turns around a hit. |
| E11 | Does loading the turn before/after each keyword hit beat plain top-k per token (LoCoMo, 1981 q)? | PASS on LoCoMo, FAIL on LongMemEval: not adopted. top-2 +-1: 203 tok / 0.595 recall vs plain top-k 308 tok at that recall (34% saving); top-3 +-1: 297 / 0.650 vs 527 (44%); top-1 +-1 3%; top-5 +-1 (476 / 0.709) is above the top-k curve (cannot compare). Also beats the product policy (218 / 0.559). First printed verdict was a validate bug (baseline included the +-1 rows); fixed, tested, disclosed in the protocol. Implemented OPT-IN as `Memory.neighbours = N` (default 0; raw turn before/after the top N matches, same source, safety-checked, inside the budget; tests/test_neighbours.py). LongMemEval (500 q): FAIL, 0 of 4 (-33% to -132%; long turns make neighbours expensive). Stays OFF by default; dataset-specific. |
| E3b | Same cutoff rule on real LongMemEval (500 q, keyword) | PASS here: cutoff 0.5 loads 2565 tok / 0.792 vs plain top-k 3009 (15% saving); cutoff 0.3 4761 / 0.855 vs about 6160 (about 23%); cutoff 0.7 1093 / 0.627 vs about 986 (worse). Mixed with LoCoMo (FAIL, -2%), no bootstrap: stays NOT adopted as a proven win; it was never worse than top-k at 0.3/0.5 on either dataset. Other LongMemEval notes: product policy 375 tok / 0.675 (top-k needs about 1270 for that recall, but the product budget skips long chunks and needed turns are short user turns, so this may be a length artifact); no abstention: unanswerable questions still load 200-6400 tokens (400 for product). |
| E4 | Can a cheap word-statistics rule abstain on vague questions? | NOT ADOPTED. Vague and one-topic-word short questions look identical in word statistics; `Memory.evidence_rule` stays None (opt-in). See experiments/e4_abstain. |
| E2 | Does a SimHash fingerprint cascade match exact dense retrieval with far less compute? | FAIL at N=50k: overlap@10 0.51 and recall -0.128 vs exact with the best grid point (256 bits, shortlist 320; 3.8% of bytes, 2.6x faster). Reaching 0.95 overlap needed a shortlist of about 10,000 (23% of bytes) and was no faster than exact. Vectors are random-projected TF-IDF, not real embeddings. |

## Next steps

(One command for the user: `pmg validate locomo10.json [--embeddings st:all-MiniLM-L6-v2] [--llm]` writes pmg-validation.md with the E3 verdict. Kits ready, untested on real data: `pmg bench FILE [--embeddings http|st:MODEL] [--ann]` for E3/E5/E6; `pmg bench-llm FILE` for E7/E9/E10 and the echo check. All need the user's machine/model.)

0. (LoCoMo keyword and embedding runs DONE: E3, E5, E6 not adopted; see log.) E11 passed LoCoMo but failed LongMemEval (stays opt-in). Both real datasets done for keyword search; apply the E3 rule: the relative cutoff counts as
   adopted only if it loads at least 10% fewer tokens than the best top-k at recall within 0.01 (check with a bootstrap).
   Latency at 100k is now 14 ms with pruning (33 ms without); the remaining growth is the FTS5 OR query itself. A real fix
   for goals 2 and 14 is a different first stage (inverted index with top-term selection, or embeddings plus an ANN
   index), to be tested on real data.
1. Real-data check of the relative cutoff on LoCoMo/LongMemEval with a real embedding model (user's machine).
2. Vague-question abstention (P1b injects about 920 tokens on questions needing nothing).
   Also open: a sublinear first stage (buckets or a graph) for goals 2 and 14, tested on real embeddings.
3. Hybrid keyword + embedding retrieval (paraphrases); validate the echo estimate against real replies; ADD/UPDATE/DELETE/NOOP ingestion.

## How to work with this user

- They want concrete answers and finished work, not repeated process advice. If they already said something, do not
  ask again.
- Keep replies plain and short. They are on the free plan with limited context, so avoid long recaps.
- Describe outcomes in terms of what the user would actually see and use, not only metrics.
- Their project notes also live in the shared memory store (`/areas/ai-memory-layer-idea.md`).
