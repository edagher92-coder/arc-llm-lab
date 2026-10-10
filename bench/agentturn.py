import json, sys, time, urllib.request, random
# Simulates agentic coding turns at depth: ~30k context, then turns that each add ~3k tokens of "tool output" and generate ~400 tokens.
port = sys.argv[1] if len(sys.argv) > 1 else "18080"
tag = sys.argv[2] if len(sys.argv) > 2 else "run"
random.seed(11)
def block(n, seed):
    random.seed(seed)
    return "\n".join(f"def helper_{seed}_{i}(x, y):\n    \"\"\"Helper {i}.\"\"\"\n    total = x * {random.randint(2,99)} + y - {random.randint(1,50)}\n    return total if total > {random.randint(0,999)} else -total\n" for i in range(n))
msgs = [{"role": "user", "content": "Context module:\n```python\n" + block(int(__import__("os").environ.get("NF","590")), 1) + "\n```\nReply OK."}]
body = {"model": "qwen3.8-27b", "messages": msgs, "max_tokens": 8, "temperature": 0.6, "top_p": 0.95, "top_k": 20,
        "chat_template_kwargs": {"enable_thinking": False}}
def call(b):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=json.dumps(b).encode(), headers={"Content-Type": "application/json"})
    t = time.time(); r = json.load(urllib.request.urlopen(req, timeout=1800)); return r, time.time() - t
r, dt = call(body)
print(json.dumps({"tag": tag, "run": "warm-30k", "wall_s": round(dt, 1), "prompt_n": r["timings"]["prompt_n"], "pp_tps": round(r["timings"]["prompt_per_second"], 1)}))
msgs.append({"role": "assistant", "content": r["choices"][0]["message"]["content"]})
tot = 0
for turn in range(3):
    msgs.append({"role": "user", "content": f"Tool output (file part {turn}):\n```python\n" + block(60, 100 + turn) +
                 "\n```\nWrite a new function that validates and sums AUD invoice line items (Decimal, GST 10%) with 2 pytest tests. Code only."})
    body = dict(body, messages=msgs, max_tokens=400)
    r, dt = call(body); tm = r["timings"]; tot += dt
    print(json.dumps({"tag": tag, "run": f"turn{turn+1}", "wall_s": round(dt, 1), "new_prompt": tm.get("prompt_n"), "cache_n": tm.get("cache_n"),
                      "pp_tps": round(tm.get("prompt_per_second", 0), 1), "gen_n": tm.get("predicted_n"), "tg_tps": round(tm.get("predicted_per_second", 0), 2)}))
    msgs.append({"role": "assistant", "content": r["choices"][0]["message"]["content"]})
print(json.dumps({"tag": tag, "three_turns_wall_s": round(tot, 1)}))

