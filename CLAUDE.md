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

- `pmg/`: `store.py` (SQLite + FTS5 chunks, slot keys, events), `rules.py` + `rules.default.json`, `classify.py`,
  `llm.py`, `mcp_server.py` (works on mcp 1.x FastMCP and 2.x MCPServer), `proxy.py` (stdlib OpenAI-compatible),
  `dashboard.py` + `web/index.html`, `cli.py`, `config.py`, `textutil.py`, `ledger.py` (time/tokens/ops per stage).
- `tests/`: unit and interface tests (41 passing). `docs/INTEGRATION.md`. `legacy/`: the original chat app.
- `experiments/e1_topology_router/`: PROTOCOL.md, gym.py, engine.py, run.py, diagnose.py, RESULTS.md, DIAGNOSTICS.md.

## Commands

- Tests: `python3 -m unittest discover -s tests`
- E1 full run: `python3 experiments/e1_topology_router/run.py --sensitivity 1500` (about 1 minute)
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
- Planned: three-level lossless storage; multi-resolution chunks (binary fingerprint + full embedding); cheap-first
  cascade with early exit; information-per-token packing; cheap-first ADD/UPDATE/DELETE/NOOP ingestion;
  waste-driven learning loop (waste = tokens loaded but never used); memory is data, not instructions.
- Dropped: topology-aware routing (E1 failed). Inspirations from neuromorphic photonics (event-driven sparsity ->
  cascade) and DNA (binary similarity fingerprints) are untested ideas, not commitments.

## Status

- Done and pushed to main: package restructure, MCP server, proxy, dashboard, CLI, docs, CI, cost ledger, E1.
- Known weakness: keyword (FTS5) retrieval finds paraphrases poorly (hit@3 = 17% on a small test). Embeddings and
  hybrid retrieval are needed.

## Experiment log

| ID | Question | Result |
|---|---|---|
| E1 | Does topology (H0/MST) routing cut tokens vs score-only routers at equal recall? | FAIL. At R=0.90: P0 599 tok / 0.891, P1b 298 / 0.883, P2 387 / 0.891. Tuned gap was 0.6 so clusters did nothing; relative cutoff is the useful part. |

## Next steps

1. E2: does a cheap binary-fingerprint cascade match full-embedding recall with less compute? (write protocol first)
2. Real-data check of the relative cutoff on LoCoMo/LongMemEval with a real embedding model (user's machine).
3. Vague-question abstention (P1b injects about 920 tokens on questions needing nothing).
4. Layer 1 three-level storage; integrate the cost ledger into the server and dashboard; hybrid retrieval.

## How to work with this user

- They want concrete answers and finished work, not repeated process advice. If they already said something, do not
  ask again.
- Keep replies plain and short. They are on the free plan with limited context, so avoid long recaps.
- Describe outcomes in terms of what the user would actually see and use, not only metrics.
- Their project notes also live in the shared memory store (`/areas/ai-memory-layer-idea.md`).
