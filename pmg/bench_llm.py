"""`pmg bench-llm`: does the model still answer correctly with PMG's memory, and what does that cost?

For each question, a real model answers under five conditions: no memory, the whole history (cut to the most recent
`max_history_tokens`), PMG's relative cutoff (0.5), PMG's product policy, and PMG's cutoff with every chunk reduced to
its short form. An answer is correct if the expected answer appears in it (or word overlap F1 >= 0.5).

It also checks the waste estimate (pmg.waste) against ground truth: for chunks the cutoff policy loaded, how often does
"echoed in the reply" agree with "was actually needed"?
"""
from __future__ import annotations

import os
import sys
import re
import statistics
import tempfile

from . import bench, waste
from .store import chunk_cost
from .textutil import est_tokens, make_gist

CONDITIONS = ("no memory", "full history", "cutoff 0.5", "product (budget 400)", "cutoff 0.5, short forms")
PROMPT = ("Answer the question in one short sentence, using only the memory below when it helps. If the memory does not "
          "contain the answer, say you do not know.\n\nMemory:\n{memory}\n\nQuestion: {question}\nAnswer:")


def _norm(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


def is_correct(reply: str, answers: list[str]) -> bool:
    rep, rep_set = " ".join(_norm(reply)), set(_norm(reply))
    for a in answers:
        toks = _norm(a)
        if not toks:
            continue
        if " ".join(toks) in rep:
            return True
        common = len(rep_set & set(toks))
        if common:
            p, r = common / max(1, len(rep_set)), common / len(toks)
            if 2 * p * r / (p + r) >= 0.5:
                return True
    return False


def _memory_block(lines: list[str]) -> str:
    return "\n".join(f"- {' '.join(t.split())}" for t in lines) or "(nothing)"


def run(cases: list[dict], complete, limit: int = 30, max_history_tokens: int = 12000) -> dict:
    acc = {c: {"correct": [], "prompt_tokens": []} for c in CONDITIONS}
    echo_pairs, asked, empty, calls = [], 0, 0, 0
    pick = bench.POLICIES["cutoff 0.5"]
    for case in cases:
        messages = case["messages"]
        with tempfile.TemporaryDirectory(prefix="pmg-benchllm-") as d:
            saved = os.environ.get("PMG_DATA")
            try:
                m = bench._build_store(messages, d)
                for q in case["questions"]:
                    if asked >= limit or not q.get("answers"):
                        continue
                    asked += 1
                    print(f"question {asked}/{limit}", file=sys.stderr, flush=True)
                    cands = m.candidates(q["q"], bench.POOL)
                    chosen = pick(cands)
                    history, used = [], 0
                    for text in reversed(messages):
                        if used + chunk_cost(text) > max_history_tokens:
                            break
                        history.append(text); used += chunk_cost(text)
                    product = m.retrieve(q["q"], log=False)
                    memory = {
                        "no memory": [],
                        "full history": list(reversed(history)),
                        "cutoff 0.5": [c[1] for c in chosen],
                        "product (budget 400)": [c["text"] for c in product["chunks"]],
                        "cutoff 0.5, short forms": [make_gist(c[1]) or c[1] for c in chosen],
                    }
                    reply_for_echo = ""
                    for cond, lines in memory.items():
                        prompt = PROMPT.format(memory=_memory_block(lines), question=q["q"])
                        reply = complete(prompt) or ""
                        calls += 1; empty += not reply.strip()
                        acc[cond]["correct"].append(is_correct(reply, q["answers"]))
                        acc[cond]["prompt_tokens"].append(est_tokens(prompt))
                        if cond == "cutoff 0.5":
                            reply_for_echo = reply
                    needed = {n + 1 for n in q.get("needed", [])}
                    for cid, text, _ in chosen:
                        e, t = waste.echoed_tokens([{"text": text, "tokens": chunk_cost(text), "why": "match"}], reply_for_echo)
                        echo_pairs.append((e > 0, cid in needed))
            finally:
                if saved is None:
                    os.environ.pop("PMG_DATA", None)
                else:
                    os.environ["PMG_DATA"] = saved
        if asked >= limit:
            break
    rows = [{"condition": c, "accuracy": statistics.mean(a["correct"]), "mean_prompt_tokens": statistics.mean(a["prompt_tokens"])}
            for c, a in acc.items() if a["correct"]]
    tp = sum(e and n for e, n in echo_pairs); fp = sum(e and not n for e, n in echo_pairs)
    fn = sum((not e) and n for e, n in echo_pairs); tn = sum((not e) and (not n) for e, n in echo_pairs)
    return {"questions": asked, "rows": rows, "empty_replies": empty, "calls": calls,
            "echo_check": {"loaded_chunks": len(echo_pairs), "echoed_and_needed": tp, "echoed_not_needed": fp,
                           "needed_not_echoed": fn, "neither": tn,
                           "agreement": (tp + tn) / len(echo_pairs) if echo_pairs else None}}


def format_report(rep: dict) -> str:
    out = [f"{rep['questions']} questions answered under each condition.", "",
           f"{'condition':<28}{'accuracy':>10}{'prompt tokens':>16}"]
    out += [f"{r['condition']:<28}{r['accuracy']:>10.3f}{r['mean_prompt_tokens']:>16.0f}" for r in rep["rows"]]
    e = rep["echo_check"]
    if e["loaded_chunks"]:
        out += ["", f"Waste estimate versus ground truth over {e['loaded_chunks']} loaded chunks (cutoff 0.5): "
                    f"echoed and needed {e['echoed_and_needed']}, echoed but not needed {e['echoed_not_needed']}, "
                    f"needed but not echoed {e['needed_not_echoed']}, neither {e['neither']}; "
                    f"agreement {e['agreement']:.2f}."]
    if rep.get("calls") and rep.get("empty_replies", 0) / rep["calls"] > 0.2:
        out += ["", f"WARNING: {rep['empty_replies']} of {rep['calls']} model replies were empty. The accuracy numbers above "
                    "are not trustworthy; try another model."]
    out += ["", "Accuracy uses answer containment or word-overlap F1 >= 0.5, not a model judge."]
    return "\n".join(out)
