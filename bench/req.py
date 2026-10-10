import json, sys, time, urllib.request
port = sys.argv[1] if len(sys.argv) > 1 else "18080"
tag = sys.argv[2] if len(sys.argv) > 2 else "run"
prompt = ("Write a Python function `merge_intervals(intervals)` that merges overlapping and touching half-open integer "
          "intervals [start, end). Validate input strictly, do not mutate the argument, and include 3 pytest tests. "
          "Then briefly explain complexity.")
body = {"model": "qwen3.8-27b", "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 700, "temperature": 0.6, "top_p": 0.95, "top_k": 20,
        "chat_template_kwargs": {"enable_thinking": False}}
req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=json.dumps(body).encode(),
                             headers={"Content-Type": "application/json"})
t = time.time()
r = json.load(urllib.request.urlopen(req, timeout=600))
dt = time.time() - t
tm = r.get("timings", {})
out = {"tag": tag, "wall_s": round(dt, 1), "prompt_n": tm.get("prompt_n"), "pp_tps": round(tm.get("prompt_per_second", 0), 1),
       "gen_n": tm.get("predicted_n"), "tg_tps": round(tm.get("predicted_per_second", 0), 2),
       "draft_n": tm.get("draft_n"), "draft_accepted": tm.get("draft_n_accepted"),
       "head": r["choices"][0]["message"]["content"][:300]}
print(json.dumps(out, indent=1))
