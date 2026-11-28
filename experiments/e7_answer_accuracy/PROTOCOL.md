# E7: does answering from PMG's memory keep accuracy while sending far fewer tokens?

Status: protocol written **before the run**. The rule is fixed.

## Question

A real model is asked LoCoMo questions with three kinds of memory in its prompt: the full history (capped at 12,000
tokens), PMG's cutoff 0.5 policy, and PMG's product setting (budget 400). Does PMG's memory answer as well as the full
history?

## Setup (fixed)

- Data: `locomo10.json`, questions that have an answer. Every 130th such question, 15 questions in all
  (`--limit 15 --stride 130`), so the sample covers all 10 conversations.
- Model: one free OpenRouter model, `inclusionai/ling-3.2-flash:free`, temperature 0, 300 max tokens. Same model for every
  condition.
- Conditions: `full history`, `cutoff 0.5`, `product (budget 400)`. Command:
  `pmg bench-llm locomo10.json --limit 15 --stride 130 --conditions "full history,cutoff 0.5,product (budget 400)"`
- Correct = the gold answer appears in the reply, or word-overlap F1 with it is at least 0.5. No model judge. This
  is strict for long replies and will under-count correct answers for every condition equally.

## Validity (the run counts only if all hold)

1. Fewer than 20% of model replies are empty (the report prints a WARNING otherwise).
2. The full-history condition scores at least 0.30. If the model cannot answer even with everything in front of it, the
   test says nothing about memory, and the verdict is INVALID, not FAIL.

## Pass / fail (only for a valid run)

- **PASS (provisional)**: product accuracy is at least full-history accuracy minus 0.10, and product prompt tokens are at
  most 5% of full-history prompt tokens.
- **FAIL**: otherwise.
- With 15 questions one answer is 6.7 points, so any result is a first signal. Adopting it as evidence needs at least
  100 questions on a model that passes validity. A PASS here is reported as "provisional", never as proof.

## Also reported (not part of the verdict)

- Cutoff 0.5 accuracy and tokens, for comparison.
- The echo-estimate check (agreement between the proxy's waste estimate and ground truth).
- Per-condition accuracy differences are shown with the number of questions, not as percentages alone.

## Amendment (added before any run; the rules above are unchanged)

The model is a setup parameter, not part of the rule. A local model served through an OpenAI-compatible endpoint
(Ollama, LM Studio, llama.cpp) may be used instead of the free OpenRouter model. Every run is reported with its model
name and context size, and the same validity and pass/fail rules apply. A local model has no daily request cap, so the
evidence run (at least 100 questions: `--limit 100 --stride 20`) becomes possible. `PMG_LLM_TIMEOUT` (seconds, default
60) was added for slow local models.

## Amendment 2 (added before any run; the rules above are unchanged)

A run with fewer than 15 questions is a **smoke test**: it shows that the setup works and what the numbers look like, and it
carries **no verdict** (neither PASS nor FAIL nor INVALID). The verdict rules apply only to runs of at least 15
questions. The conditions may be run in separate commands on the same questions (same `--limit` and `--stride`) and their
results combined, for machines that cannot run the long full-history prompt together with the others.
