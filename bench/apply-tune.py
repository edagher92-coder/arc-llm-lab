import json, shutil, time
p = r"C:\AI\governor\profiles.json"
shutil.copy(p, p + ".bak-before-tune-" + time.strftime("%H%M"))
c = json.load(open(p, encoding="utf-8-sig"))
for k in ("default", "turbo"):
    v = c["variants"][k]
    args = [a for a in v["extra_args"]]
    for flag, val in (("-ub", "256"), ("-ctkd", "q8_0"), ("-ctvd", "q8_0")):
        if flag in args:
            args[args.index(flag) + 1] = val
        else:
            args += [flag, val]
    v["extra_args"] = args
    v["ctx_max"] = 65536
    v["kv_kib_per_token"] = 64.5
v = c["variants"]["default"]; v["base_gib"] = 17.15
c["variants"]["turbo"]["base_gib"] = 16.77
json.dump(c, open(p, "w", encoding="utf-8"), indent=2)
print({k: (x.get("base_gib"), x.get("kv_kib_per_token"), x.get("ctx_max"), " ".join(x.get("extra_args", []))) for k, x in c["variants"].items() if k in ("default", "turbo")})
