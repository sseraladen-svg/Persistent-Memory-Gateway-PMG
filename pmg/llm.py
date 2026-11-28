"""Optional offline model used only to classify messages and tune rules, never to chat.

Any OpenAI-compatible endpoint works (Ollama, OpenRouter, a hosted API):
  PMG_LLM_BASE_URL   e.g. http://localhost:11434/v1
  PMG_LLM_MODEL      e.g. llama3.1:8b
  PMG_LLM_KEY        optional bearer token
"""
from __future__ import annotations

import json
import time
import os
import urllib.error
import urllib.request
from typing import Callable, Optional

Completer = Callable[[str], str]


def from_env() -> Optional[Completer]:
    base, model = os.environ.get("PMG_LLM_BASE_URL"), os.environ.get("PMG_LLM_MODEL")
    if not base or not model:
        return None
    key = os.environ.get("PMG_LLM_KEY", "")

    def complete(prompt: str) -> str:
        body = json.dumps({
            "model": model, "temperature": 0, "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=body, headers=headers)
        for attempt in range(6):  # free tiers rate-limit: wait and retry instead of losing a long run
            try:
                with urllib.request.urlopen(req, timeout=float(os.environ.get("PMG_LLM_TIMEOUT", "60"))) as response:
                    return json.load(response)["choices"][0]["message"].get("content") or ""  # some models return null
            except urllib.error.HTTPError as err:
                if err.code not in (429, 500, 502, 503, 504) or attempt == 5:
                    try:
                        detail = err.read().decode("utf-8", "replace")[:500]
                    except Exception:
                        detail = ""
                    raise RuntimeError(f"The model server answered HTTP {err.code}: {detail or err.reason}") from err
            except urllib.error.URLError:
                if attempt == 5:
                    raise
            time.sleep(2 ** (attempt + 1))

    return complete
