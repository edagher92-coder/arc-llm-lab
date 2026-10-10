"""Tool-bundle cache test: does a chat that switches tool bundle A -> B -> A get A back from the host-RAM prompt cache?
Qwen's template writes <tools> first, so each bundle is a different prompt prefix. Synthetic schemas sized like real bundles."""
import json, os, time, urllib.request
BASE = os.environ.get("LOCAL_QWEN_URL", "http://127.0.0.1:8090/v1") + "/chat/completions"
KEY = os.environ.get("LOCAL_QWEN_KEY") or open(os.environ.get("LOCAL_QWEN_KEY_FILE", r"C:\AI\llama-swap\api-key.txt")).read().strip()
def tool(prefix, i):
    return {"type": "function", "function": {"name": f"{prefix}_action_{i}", "description": f"{prefix} tool {i}: " + "performs a specific operation on the target resource and returns a structured result. " * 6,
            "parameters": {"type": "object", "properties": {f"arg{j}": {"type": "string", "description": "argument value used by the operation, see the tool description for the accepted format " * 2} for j in range(5)}, "required": ["arg0"]}}}
A = [tool("core", i) for i in range(18)]      # ~7-8K tokens
B = A + [tool("browser", i) for i in range(8)] # core + browser bundle
SYS = {"role": "system", "content": "You are a helpful assistant on a home PC."}
def call(tools, msgs):
    body = json.dumps({"model": "qwen3.8-27b", "messages": msgs, "tools": tools, "max_tokens": 8, "temperature": 0,
                       "chat_template_kwargs": {"enable_thinking": False}}).encode()
    req = urllib.request.Request(BASE, data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    t = time.time(); r = json.loads(urllib.request.urlopen(req, timeout=600).read()); dt = time.time() - t
    tm = r.get("timings", {})
    return dict(wall_s=round(dt, 2), prompt_tokens=r.get("usage", {}).get("prompt_tokens"), processed=tm.get("prompt_n"), from_cache=tm.get("cache_n"))
m1 = [SYS, {"role": "user", "content": "Say hi."}]
res = {}
res["1_bundle_A_cold"] = call(A, m1)
res["2_bundle_B_switch"] = call(B, m1 + [{"role": "assistant", "content": "Hi."}, {"role": "user", "content": "Now open a web page."}])
res["3_bundle_A_again_new_chat"] = call(A, [SYS, {"role": "user", "content": "What time is it?"}])
res["4_bundle_A_continue"] = call(A, m1 + [{"role": "assistant", "content": "Hi."}, {"role": "user", "content": "Thanks."}])
print(json.dumps(res, indent=1))
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "bundle-cache-result.json")
os.makedirs(os.path.dirname(out), exist_ok=True); json.dump(res, open(out, "w"), indent=1)
