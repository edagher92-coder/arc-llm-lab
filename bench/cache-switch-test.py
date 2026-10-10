"""Does a long agent prompt survive a short 'phone' chat on the single slot? (host-RAM prompt cache + checkpoints)
A: ~30K-token prompt -> B: short unrelated chat -> A + small suffix. Reports prompt tokens re-processed and time."""
import json, os, random, time, urllib.request
BASE = os.environ.get("LOCAL_QWEN_URL", "http://127.0.0.1:8090/v1") + "/chat/completions"
KEY = os.environ.get("LOCAL_QWEN_KEY") or open(os.environ.get("LOCAL_QWEN_KEY_FILE", r"C:\AI\llama-swap\api-key.txt")).read().strip()
MODEL = "qwen3.8-27b"
random.seed(7)
words = "def class return import self value list dict range len print for while if else try except with open file data index".split()
code = "\n".join("    " + " ".join(random.choice(words) for _ in range(12)) for _ in range(2600))  # ~30K tokens
def call(msgs):
    body = json.dumps({"model": MODEL, "messages": msgs, "max_tokens": 8, "temperature": 0,
                       "chat_template_kwargs": {"enable_thinking": False}}).encode()
    req = urllib.request.Request(BASE, data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    t = time.time(); r = json.loads(urllib.request.urlopen(req, timeout=900).read()); dt = time.time() - t
    tm = r.get("timings", {}); u = r.get("usage", {})
    return dict(wall_s=round(dt, 2), prompt_n=tm.get("prompt_n"), cache_n=tm.get("cache_n"), prompt_ms=tm.get("prompt_ms"),
                prompt_tokens=u.get("prompt_tokens"))
A = [{"role": "system", "content": "You are a code reviewer."}, {"role": "user", "content": "Review this file:\n" + code + "\nSay OK."}]
res = {}
res["1_agent_cold"] = call(A)
res["2_phone_chat"] = call([{"role": "user", "content": "What is the capital of Australia? One word."}])
res["3_agent_resume"] = call(A + [{"role": "assistant", "content": "OK"}, {"role": "user", "content": "Now list one issue."}])
print(json.dumps(res, indent=1))
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "cache-switch-result.json")
os.makedirs(os.path.dirname(out), exist_ok=True); json.dump(res, open(out, "w"), indent=1)
