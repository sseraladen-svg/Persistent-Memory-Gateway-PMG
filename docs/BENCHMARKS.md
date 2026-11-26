# Measuring PMG on real data

`pmg bench` answers one question on data you choose: **how many tokens does PMG load per question, and does it still
load the messages the question needs?** It needs no extra packages and no network.

```bash
pmg bench path/to/dataset.json              # format is detected automatically
pmg bench locomo10.json --limit 300         # stop after 300 questions
pmg bench data.json --json results.json     # also save the numbers
```

## What it does

Each message in a conversation becomes one chunk in a throw-away store. For every question it compares these ways of
choosing what to load, on the same keyword matches:

| Policy | Meaning |
|---|---|
| `top-k` | always load the k best matches |
| `cutoff b` | load matches scoring at least b times the best score (up to 20) |
| `product (budget 400)` | what PMG does today: rules, weights and a 400-token budget |

It reports mean tokens loaded, the share of the full history that is, recall (the share of needed messages loaded),
median time, and the tokens loaded for questions that have no answer in the history (the right amount is zero).

## Datasets

- **LoCoMo** (`locomo10.json`, from the snap-research/locomo repository): evidence turns are the needed messages.
  Questions whose evidence cannot be mapped (the unanswerable category) are skipped and counted.
- **LongMemEval** (a `longmemeval_*.json` file): turns marked `has_answer` are the needed messages; question ids ending
  in `_abs` are treated as unanswerable.
- **Generic**: `{"cases": [{"messages": ["..."], "questions": [{"q": "...", "needed": [0, 3]}]}]}`. A question may give
  `"answers": ["text"]` instead of `needed` (recall is then 1 if any answer text is in what was loaded), or
  `"abstain": true` for a question with no answer.

The LoCoMo and LongMemEval readers are written from the published file layouts and tested on small samples in the
same layout; they have not yet been run against the real files. If a file does not load, send the error.

## Reading the result

- Compare policies at similar recall, not at similar tokens. A policy that loads fewer tokens but loses needed
  messages has not saved anything.
- This is keyword search only. Questions that rephrase the message (paraphrases) will score low until embeddings are
  added; that is a known weakness, and this is how to measure it.
- Numbers here are for your data and this machine. They are not comparable with published benchmark scores, which
  use different methods.

## Embeddings, index check and answer accuracy

- `pmg bench FILE --embeddings http` uses an OpenAI-compatible endpoint (`PMG_EMBED_BASE_URL`, `PMG_EMBED_MODEL`,
  `PMG_EMBED_KEY`); `--embeddings st:all-MiniLM-L6-v2` uses sentence-transformers. Needs numpy. Adds embedding and
  hybrid rows, which show whether paraphrases are found.
- `--ann` adds an IVF check: how much of the exact nearest-neighbour answer is kept, and how much is scanned.
- `pmg bench-llm FILE --limit 30` asks a real model each question with no memory, full history, cutoff, product
  policy and short forms, and reports accuracy and prompt tokens. It also checks the reply-echo waste estimate.
  It makes API calls; these paths were tested only with fake models.
