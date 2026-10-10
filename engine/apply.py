import json, shutil, copy, time
p = r"C:\AI\governor\profiles.json"
shutil.copy(p, p + ".bak-before-intelfa-" + time.strftime("%H%M"))
c = json.load(open(p, encoding="utf-8-sig"))
c["exe"] = "C:/AI/llama.cpp/vulkan-intelfa/llama-server.exe"
v = c["variants"]
# big = previous default (q4_0 KV, ~200k context) kept as an option
big = copy.deepcopy(v["default"]); big["id"] = "qwen3.8-27b-big"; big["port"] = 10005
v["big"] = big
for k in ("default", "turbo"):
    v[k]["ctk"] = "f16"; v[k]["ctv"] = "f16"; v[k]["kv_kib_per_token"] = 64.5; v[k]["ctx_max"] = 65536
for name in ("MAX", "BALANCED"):
    c["profiles"][name]["ctx_min"] = 32768
json.dump(c, open(p, "w", encoding="utf-8"), indent=2)
print("exe:", c["exe"]); print({k: (x.get("ctk"), x.get("kv_kib_per_token"), x.get("ctx_max", x.get("fixed_ctx")), x.get("port")) for k, x in v.items()})
print({k: x["ctx_min"] for k, x in c["profiles"].items()})
