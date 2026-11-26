"""Optional embeddings for `pmg bench` (never needed for normal use). Needs numpy.

  --embeddings http            an OpenAI-compatible /embeddings endpoint:
                                 PMG_EMBED_BASE_URL (e.g. http://localhost:11434/v1), PMG_EMBED_MODEL, PMG_EMBED_KEY
  --embeddings st:<model>      sentence-transformers, e.g. st:all-MiniLM-L6-v2 (pip install sentence-transformers)
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Callable

Embedder = Callable[[list], "object"]  # list of texts -> 2-D numpy array (rows are unit-length)


def _np():
    try:
        import numpy as np
    except ImportError as err:
        raise SystemExit("Embedding policies need numpy: pip install numpy") from err
    return np


def _unit(rows):
    np = _np()
    a = np.asarray(rows, dtype="float32")
    norms = np.linalg.norm(a, axis=1, keepdims=True)
    return a / np.where(norms == 0, 1, norms)


def from_spec(spec: str) -> Embedder:
    if spec == "http":
        base, model = os.environ.get("PMG_EMBED_BASE_URL"), os.environ.get("PMG_EMBED_MODEL")
        if not base or not model:
            raise SystemExit("Set PMG_EMBED_BASE_URL and PMG_EMBED_MODEL (and PMG_EMBED_KEY if needed).")
        key = os.environ.get("PMG_EMBED_KEY", "")

        def embed(texts):
            out = []
            for i in range(0, len(texts), 64):
                body = json.dumps({"model": model, "input": [t[:8000] for t in texts[i:i + 64]]}).encode()
                headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})}
                req = urllib.request.Request(base.rstrip("/") + "/embeddings", data=body, headers=headers)
                with urllib.request.urlopen(req, timeout=120) as r:
                    out += [d["embedding"] for d in sorted(json.load(r)["data"], key=lambda d: d["index"])]
            return _unit(out)

        return embed
    if spec.startswith("st:"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as err:
            raise SystemExit("pip install sentence-transformers") from err
        model = SentenceTransformer(spec[3:])
        return lambda texts: _unit(model.encode(texts, batch_size=64, show_progress_bar=False))
    raise SystemExit(f"Unknown embeddings spec '{spec}'. Use 'http' or 'st:<model>'.")
