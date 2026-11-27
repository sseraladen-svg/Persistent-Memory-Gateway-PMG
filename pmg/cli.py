"""The `pmg` command line."""
from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser

from . import __version__, rules as rules_mod
from .llm import from_env
from .store import Memory


def _print_chunks(chunks):
    if not chunks:
        print("Nothing stored yet.")
    for c in chunks:
        print(f"#{c['id']:<4} {c['kind']:<10} {c['text']}")


def cmd_add(args):
    memory = Memory()
    if args.kind:
        cid = memory.add(args.kind, " ".join(args.text))
    else:
        cid = memory.ingest(" ".join(args.text), from_env())
    print(f"Stored as #{cid}." if cid else "Not stored: nothing durable found, or it looked like a secret or an instruction aimed at the model. "
          "Use --kind to store it as-is.")
    return 0 if cid else 1


def cmd_search(args):
    result = Memory().retrieve(" ".join(args.query), args.budget, log=False)
    for c in result["chunks"]:
        print(f"#{c['id']:<4} {c['kind']:<10} {c['tokens']:>3} tok  {c['text']}")
    print(f"\n{len(result['chunks'])} chunks, {result['tokens']} of {result['budget']} tokens")
    return 0


def cmd_list(args):
    _print_chunks(Memory().list(limit=args.limit, kind=args.kind))
    return 0


def cmd_forget(args):
    ok = Memory().forget(args.id)
    print("Forgotten." if ok else "No chunk with that id.")
    return 0 if ok else 1


def cmd_stats(_args):
    s = Memory().stats()
    print(f"Chunks:          {s['chunks']}  {s['kinds']}")
    print(f"Stored size:     {s['stored_tokens']} tokens")
    print(f"Requests served: {s['requests']}")
    if s["saved_percent"] is not None:
        print(f"Avg injected:    {s['avg_injected_tokens']} tokens ({s['saved_percent']}% less than loading everything)")
    return 0


def cmd_rules(_args):
    problems = rules_mod.validate(rules_mod.load())
    print("Rules are valid." if not problems else "Problems:\n- " + "\n- ".join(problems))
    from . import config
    print(f"File: {config.rules_path()}")
    return 1 if problems else 0


def cmd_dashboard(args):
    from .dashboard import make_server
    server = make_server(Memory(), args.host, args.port)
    url = f"http://{args.host}:{server.server_address[1]}"
    print(f"PMG dashboard: {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    return 0


def cmd_proxy(args):
    from .proxy import make_server
    upstream = args.upstream or os.environ.get("PMG_UPSTREAM_URL")
    if not upstream:
        print("Set the real API with --upstream or PMG_UPSTREAM_URL, e.g. https://openrouter.ai/api/v1", file=sys.stderr)
        return 2
    server = make_server(upstream, Memory(), from_env(), args.host, args.port)
    print(f"PMG proxy on http://{args.host}:{server.server_address[1]}/v1  ->  {upstream}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    return 0


def cmd_mcp(args):
    from .mcp_server import run
    run(http=args.http, host=args.host, port=args.port)
    return 0


def cmd_bench(args):
    from . import bench
    try:
        cases = bench.load_dataset(args.file, args.format)
    except (OSError, ValueError) as err:
        print(f"Could not read {args.file}: {err}", file=sys.stderr)
        return 2
    embedder = None
    if args.embeddings:
        from . import embed
        embedder = embed.from_spec(args.embeddings)
    report = bench.run(cases, args.limit, embedder=embedder, ann=args.ann)
    print(bench.format_report(report))
    if args.json:
        import json
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1)
    return 0


def cmd_bench_llm(args):
    from . import bench, bench_llm
    complete = from_env()
    if complete is None:
        print("Set PMG_LLM_BASE_URL and PMG_LLM_MODEL (and PMG_LLM_KEY if needed) so questions can be answered.", file=sys.stderr)
        return 2
    try:
        cases = bench.load_dataset(args.file, args.format)
    except (OSError, ValueError) as err:
        print(f"Could not read {args.file}: {err}", file=sys.stderr)
        return 2
    try:
        conds = [x.strip() for x in args.conditions.split(",")] if args.conditions else None
        report = bench_llm.run(cases, complete, args.limit, args.max_history_tokens, conds)
    except (RuntimeError, OSError) as err:
        print(f"\nStopped: {err}", file=sys.stderr)
        return 1
    print(bench_llm.format_report(report))
    if args.json:
        import json
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1)
    return 0


def _tokens_at_recall(topk, recall):
    """Tokens a plain top-k needs for this recall, by linear interpolation on the top-k curve (None if outside it)."""
    pts = sorted((r["recall"], r["mean_tokens"]) for r in topk)
    for (r0, t0), (r1, t1) in zip(pts, pts[1:]):
        if r0 <= recall <= r1 and r1 > r0:
            return t0 + (recall - r0) / (r1 - r0) * (t1 - t0)
    return None


def cmd_validate(args):
    """One command for the user's machine: runs every real-data check that is possible and writes one report."""
    from . import bench, bench_llm
    try:
        cases = bench.load_dataset(args.file, args.format)
    except (OSError, ValueError) as err:
        print(f"Could not read {args.file}: {err}", file=sys.stderr)
        return 2
    out = ["# PMG validation report", "", f"File: {args.file}", ""]
    embedder = None
    if args.embeddings:
        from . import embed
        embedder = embed.from_spec(args.embeddings)
    rep = bench.run(cases, args.limit, embedder=embedder, ann=bool(embedder))
    out += ["## Retrieval (E3, E5, E6)", "", "```", bench.format_report(rep), "```", ""]
    rows = rep["rows"]
    import re
    topk = [r for r in rows if re.fullmatch(r"top-\d+", r["policy"])]  # plain top-k only, not the "+-1" rows
    cut = next((r for r in rows if r["policy"] == "cutoff 0.5"), None)
    if topk and cut:
        # Compare on the top-k curve: tokens a fixed top-k would need for the cutoff's recall (linear interpolation),
        # because the k grid is coarse and a plain "nearest k" comparison can show a false win.
        pts = sorted((r["recall"], r["mean_tokens"]) for r in topk)
        need = None
        for (r0, t0), (r1, t1) in zip(pts, pts[1:]):
            if r0 <= cut["recall"] <= r1 and r1 > r0:
                need = t0 + (cut["recall"] - r0) / (r1 - r0) * (t1 - t0)
        if need is None:
            out.append("E3 rule: cannot compare (cutoff recall is outside the top-k curve).")
        else:
            saving = 1 - cut["mean_tokens"] / need
            out.append(f"E3 rule (cutoff loads >=10% fewer tokens than top-k at the same recall, interpolated): "
                       f"{'PASS' if saving >= 0.10 else 'FAIL'} (cutoff {cut['mean_tokens']:.0f} tokens vs top-k {need:.0f} at recall {cut['recall']:.3f}; saving {saving:.0%}; no bootstrap).")
        out.append("")
    wins, lines = 0, []
    for r in (r for r in rows if r["policy"].endswith("+-1")):
        need = _tokens_at_recall(topk, r["recall"])
        if need is None:
            lines.append(f"  {r['policy']}: cannot compare (recall {r['recall']:.3f} outside the top-k curve)")
            continue
        saving = 1 - r["mean_tokens"] / need
        wins += saving >= 0.10
        lines.append(f"  {r['policy']}: {r['mean_tokens']:.0f} tokens at recall {r['recall']:.3f}; plain top-k needs {need:.0f}; saving {saving:.0%}")
    if lines:
        out += ["E11 (neighbour turns; PASS if at least 2 of 4 settings save >=10% at equal recall):", *lines,
                f"E11 verdict: {'PASS' if wins >= 2 else 'FAIL'} ({wins} of {len(lines)} settings; point estimates).", ""]
    complete = from_env()
    if args.llm and complete is not None:
        try:
            llm = bench_llm.run(cases, complete, args.llm_limit)
        except (RuntimeError, OSError) as err:
            print(f"\nStopped the answer test: {err}", file=sys.stderr)
            return 1
        out += ["## Answer accuracy and echo check (E7, E9, E10)", "", "```", bench_llm.format_report(llm), "```", ""]
    elif args.llm:
        out += ["## Answer accuracy", "", "Skipped: set PMG_LLM_BASE_URL and PMG_LLM_MODEL (and PMG_LLM_KEY).", ""]
    text = "\n".join(out)
    print(text)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"\nWrote {args.out}. Paste it back into the chat.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pmg", description="Persistent Memory Gateway: a memory layer for AI tools.")
    p.add_argument("--version", action="version", version=f"pmg {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("add", help="remember something (classified by the rules, or stored as-is with --kind)")
    s.add_argument("text", nargs="+"); s.add_argument("--kind"); s.set_defaults(func=cmd_add)

    s = sub.add_parser("search", help="show what would be loaded for a message")
    s.add_argument("query", nargs="+"); s.add_argument("--budget", type=int, default=0); s.set_defaults(func=cmd_search)

    s = sub.add_parser("list", help="list stored chunks")
    s.add_argument("--limit", type=int, default=50); s.add_argument("--kind"); s.set_defaults(func=cmd_list)

    s = sub.add_parser("forget", help="delete a chunk by id")
    s.add_argument("id", type=int); s.set_defaults(func=cmd_forget)

    sub.add_parser("stats", help="size and token savings").set_defaults(func=cmd_stats)
    sub.add_parser("rules", help="validate rules.json and show its location").set_defaults(func=cmd_rules)

    s = sub.add_parser("bench", help="measure tokens loaded and recall on a dataset (LoCoMo, LongMemEval or generic JSON)")
    s.add_argument("file"); s.add_argument("--format", default="auto", choices=["auto", "generic", "locomo", "longmemeval"])
    s.add_argument("--limit", type=int, default=0, help="stop after this many questions"); s.add_argument("--json")
    s.add_argument("--embeddings", help="add embedding and hybrid rows: 'http' or 'st:<model>' (needs numpy)")
    s.add_argument("--ann", action="store_true", help="with --embeddings, also check an IVF index against exact search")
    s.set_defaults(func=cmd_bench)

    s = sub.add_parser("bench-llm", help="answer questions with a real model under each memory policy (costs API calls)")
    s.add_argument("file"); s.add_argument("--format", default="auto", choices=["auto", "generic", "locomo", "longmemeval"])
    s.add_argument("--limit", type=int, default=30, help="questions to ask (each costs about 5 model calls)")
    s.add_argument("--max-history-tokens", type=int, default=12000); s.add_argument("--json")
    s.add_argument("--conditions", help="comma-separated subset to run, e.g. 'full history,product (budget 400)' (fewer calls per question)")
    s.set_defaults(func=cmd_bench_llm)

    s = sub.add_parser("validate", help="run all real-data checks on a dataset and write one report to paste back")
    s.add_argument("file"); s.add_argument("--format", default="auto", choices=["auto", "generic", "locomo", "longmemeval"])
    s.add_argument("--limit", type=int, default=0); s.add_argument("--embeddings"); s.add_argument("--llm", action="store_true")
    s.add_argument("--llm-limit", type=int, default=30); s.add_argument("--out", default="pmg-validation.md")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("dashboard", help="open the local dashboard")
    s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8787)
    s.add_argument("--no-browser", action="store_true"); s.set_defaults(func=cmd_dashboard)

    s = sub.add_parser("proxy", help="run the OpenAI-compatible memory proxy")
    s.add_argument("--upstream"); s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8766); s.set_defaults(func=cmd_proxy)

    s = sub.add_parser("mcp", help="run the MCP server (stdio by default)")
    s.add_argument("--http", action="store_true"); s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765); s.set_defaults(func=cmd_mcp)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
