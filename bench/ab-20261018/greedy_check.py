"""Greedy fingerprint: fixed prompts at temperature 0 (DFlash is lossless under greedy verify), prints a sha256 of each
reply. Any difference from the stock fingerprint means the hardware/engine changed the maths. Usage: greedy_check.py <label>"""
import hashlib, json, os, sys, time, urllib.request
BASE = os.environ.get("QWEN_BASE", "http://127.0.0.1:10011")
PROMPTS = [
    "Write a Python function that parses an ISO 8601 duration like P3DT4H5M into seconds, with five unit tests.",
    "Explain in 120 words why a token-bucket rate limiter needs an injected clock for testing.",
    "List the first 40 prime numbers separated by commas, then their sum.",
]
out = {"label": sys.argv[1] if len(sys.argv) > 1 else "x", "hashes": [], "tps": []}
for p in PROMPTS:
    body = {"model": "qwen3.8-27b", "messages": [{"role": "user", "content": p}], "max_tokens": 600, "temperature": 0,
            "top_k": 1, "seed": 1, "chat_template_kwargs": {"enable_thinking": False}, "cache_prompt": False}
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        j = json.load(r)
    text = j["choices"][0]["message"]["content"]
    out["hashes"].append(hashlib.sha256(text.encode()).hexdigest()[:16])
    out["tps"].append(round(j.get("timings", {}).get("predicted_per_second", 0), 2))
print(json.dumps(out))
