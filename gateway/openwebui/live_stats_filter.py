"""
title: Live stats
author: arc-llm-lab
description: Shows speed, context use and drafter acceptance under every reply (read-only, from llama-server /metrics and /slots).
version: 0.1.0
"""
import json, time, urllib.request
from pydantic import BaseModel, Field

GOV = r"C:\AI\governor"


def _port():
    try:
        return int(json.load(open(GOV + r"\running.json", encoding="utf-8-sig")).get("port", 10001))
    except Exception:
        return 10001


def _metrics():
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/metrics" % _port(), timeout=2) as r:
            m = {}
            for line in r.read().decode().splitlines():
                if line.startswith("llamacpp:") and "{" not in line:
                    k, v = line.split(" ", 1)
                    m[k[9:]] = float(v)
            return m
    except Exception:
        return {}


def _slot():
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/slots" % _port(), timeout=2) as r:
            return json.loads(r.read())[0]
    except Exception:
        return {}


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=10, description="Run after other filters")
        enabled: bool = Field(default=True)

    def __init__(self):
        self.valves = self.Valves()
        self._start = {}

    def inlet(self, body: dict, __metadata__: dict = None) -> dict:
        self._start[(__metadata__ or {}).get("chat_id") or "-"] = (time.time(), _metrics())
        return body

    async def outlet(self, body: dict, __event_emitter__=None, __metadata__: dict = None) -> dict:
        if not self.valves.enabled or not __event_emitter__:
            return body
        t0, m0 = self._start.pop((__metadata__ or {}).get("chat_id") or "-", (None, {}))
        m1, s = _metrics(), _slot()
        d = lambda k: (m1[k] - m0[k]) if (k in m0 and k in m1 and m1[k] >= m0[k]) else None
        gen, gens = d("tokens_predicted_total"), d("tokens_predicted_seconds_total")
        pt, ps = d("prompt_tokens_total"), d("prompt_seconds_total")
        dr, ac = d("spec_decode_num_draft_tokens_total"), d("spec_decode_num_accepted_tokens_total")
        nt = s.get("next_token") or {}
        nt = nt[0] if isinstance(nt, list) and nt else nt
        used = (s.get("n_prompt_tokens") or 0) + ((nt or {}).get("n_decoded") or 0)
        parts = []
        if gen and gens:
            parts.append("⚡ %.1f tok/s, %d tokens" % (gen / gens, gen))
        if pt and ps:
            parts.append("read %s new prompt tokens at %.0f tok/s" % (format(int(pt), ","), pt / ps))
        if s.get("n_ctx"):
            parts.append("context %s / %s (%d%%)" % (format(used, ","), format(s["n_ctx"], ","), 100 * used // s["n_ctx"]))
        if dr:
            parts.append("draft accepted %d%%" % (100 * ac // dr))
        if t0:
            parts.append("%.1f s" % (time.time() - t0))
        if parts:
            await __event_emitter__({"type": "status", "data": {"description": " · ".join(parts), "done": True}})
        return body
