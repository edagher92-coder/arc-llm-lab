import json, urllib.request, urllib.error, time
key = open(r"C:\AI\llama-swap\api-key.txt").read().strip()
text = "".join("def helper_%d(x):\n    return x * %d + 1\n\n" % (i, i) for i in range(9000))  # ~100k+ tokens
def post(path, body, hdr):
    r = urllib.request.Request("http://127.0.0.1:8090" + path, data=json.dumps(body).encode(), headers=hdr)
    t = time.time()
    try:
        resp = urllib.request.urlopen(r, timeout=300); return resp.status, resp.read()[:300].decode(errors="replace"), round(time.time() - t, 1)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:400].decode(errors="replace"), round(time.time() - t, 1)
h = {"Content-Type": "application/json", "Authorization": "Bearer " + key}
print("OpenAI :", post("/v1/chat/completions", {"model": "qwen3.8-27b:code", "max_tokens": 20, "messages": [{"role": "user", "content": text + "\nSay OK."}]}, h))
h2 = dict(h, **{"x-api-key": key, "anthropic-version": "2023-06-01"})
print("Anthropic:", post("/v1/messages", {"model": "qwen3.8-27b:code", "max_tokens": 20, "messages": [{"role": "user", "content": text + "\nSay OK."}]}, h2))
