# How PMG works

This page follows one message in and one question out, and names the file that does each step. The diagrams are in
the [README](../README.md#how-it-works).

## The idea in one paragraph

An AI model forgets everything between chats, and pasting the whole history back in is slow and costly. PMG keeps the
history itself, outside the model, in a small local database. When you ask something, it looks up the few notes that
matter and adds only those to the prompt, inside a fixed token budget. Because the budget is fixed, the cost of a
request does not grow as your memory grows.

## Saving: a message goes in

1. **Secret check** (`classify.contains_secret`, patterns in `rules.json`). API keys, passwords and card numbers are
   not stored anywhere, not even in the raw log.
2. **Raw log** (`Memory.log_raw`, table `raw`). The message is appended word for word. Nothing is ever rewritten.
3. **Classify** (`classify.py`). Trigger phrases in `rules.json` decide whether the message is a `behavior` (standing
   instruction), a `preference` or a `fact`. If you configure an LLM it can classify with more nuance, but its answer is
   checked and the rules take over on any problem. If nothing durable is found, no chunk is made and the raw message
   stays in the log.
4. **Safety check** (`classify.unsafe_reason`). Text that reads like an instruction aimed at the model ("ignore previous
   instructions...") and anything over 400 characters is refused as a chunk. The patterns live in code, not in the
   editable rules, so a bad rules file cannot switch them off.
5. **Update, don't stack** (`Memory.add`). Four cases are handled:
   - an exact duplicate is merged;
   - a fact with a slot key such as `user.city` replaces the older value;
   - if a new note matches an old one except for its trailing value (a date, a number), the old chunk is replaced
     (`textutil.replaces`; tested at 95 of 100 with no wrong replacements, on synthetic data);
   - otherwise a new chunk is inserted.
   The replaced text is still in the raw log.
6. **Gist** (`textutil.make_gist`). Each chunk gets a summary of about 12 words, kept with it.
7. **Link.** The chunk and its raw message point to each other, so the original can always be found.

The whole save happens inside one database transaction that takes the write lock first, so several programs can save
at once.

## Asking: a question comes out

1. **Standing instructions first** (`Memory.retrieve`). Chunks of kinds marked always-load come first, up to 40% of
   the budget.
2. **Informative words.** Stop words are dropped (`textutil.unique_keywords`).
3. **Search.** SQLite's FTS5 index ranks chunks by BM25 on stemmed words, so "run" finds "running". The top 30 are kept.
4. **Score** = BM25 x kind weight x recency decay x importance. Recency decay is per kind (a `fact` fades more slowly than
   a passing `context` note, for example).
5. **Pack into the budget.** Chunks are added in score order until the token budget (default 400) or the chunk limit
   (default 6) is reached. If a chunk does not fit whole but its gist does, the gist is added and marked, for example
   `(#12 short)`. The model can then call `memory_expand` to read the original.
6. **Render** (`store.format_chunks`). One compact block. Each memory is forced onto one line, so stored text can never
   start a new section such as `Follow:`.
7. **Record** (`ledger.py`). Time, tokens and operations per stage are measured. Usage counters are buffered and written
   in batches, so the request itself does no slow writes.

Through the proxy there is one more step: after the model replies, `waste.py` checks whether the loaded notes were
repeated in the reply. This is an estimate, shown in the dashboard. It has not been checked against real model answers.

## Why these choices

| Choice | Reason |
|---|---|
| One SQLite file, keyword search | No services to run. Keyword search beat the one embedding model we tried (see the README results). |
| Fixed token budget | Cost per request does not depend on how much is stored. |
| Raw log underneath, gists on top | Compact loading without ever losing detail. |
| LLM only classifies and tunes | The model you chat with is never changed or routed by PMG. |
| Safety patterns in code | A stored memory is data, never an instruction. |

## Opt-in behaviors

Set on the `Memory` object; all are off by default because their tests did not pass on every dataset.

- `neighbours = N`: also load the raw message before and after the top N matches (`Memory._add_neighbours`). It cut
  tokens 34% to 44% on LoCoMo and cost more on LongMemEval.
- `common_df`: drop query words found in very many chunks (faster at 100,000 chunks).
- `evidence_rule`: load nothing unless the matches share informative words.

## Where each part lives

| Part | File |
|---|---|
| Database, saving, retrieval, supersede, neighbours | `pmg/store.py` |
| Classification and safety checks | `pmg/classify.py` |
| Rules loading and atomic writes | `pmg/rules.py`, `pmg/config.py` |
| Word handling, gists, outdated-note rule | `pmg/textutil.py` |
| MCP server (stdio and HTTP) | `pmg/mcp_server.py` |
| OpenAI-compatible proxy | `pmg/proxy.py` |
| Dashboard | `pmg/dashboard.py`, `pmg/web/index.html` |
| Waste estimate | `pmg/waste.py` |
| Timing and token ledger | `pmg/ledger.py` |
| Benchmarks, answer test, embeddings, index check | `pmg/bench.py`, `pmg/bench_llm.py`, `pmg/embed.py`, `pmg/ann.py` |
