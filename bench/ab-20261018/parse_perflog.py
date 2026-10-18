"""Groups GGML_VK_PERF_LOGGER blocks (one per graph compute) by graph signature and sums GPU time per group.
Usage: python parse_perflog.py <server stderr log> <rounds> [wall_ms_per_round]"""
import re, sys, collections
path, rounds = sys.argv[1], int(float(sys.argv[2]))
wall = float(sys.argv[3]) if len(sys.argv) > 3 else None
text = open(path, encoding="utf-8", errors="replace").read()
blocks = text.split("Vulkan Timings:")[1:]
groups = collections.OrderedDict()
op_line = re.compile(r"^(.+?): (\d+) x ([0-9.e+]+) us = ([0-9.e+]+) us", re.M)
for b in blocks:
    b = b.split("----------------")[0]
    ops = op_line.findall(b)
    tot = re.search(r"Total time: ([0-9.e+]+) us", b)
    if not ops or not tot:
        continue
    total = float(tot.group(1))
    n_ops = sum(int(o[1]) for o in ops)
    mm = sum(int(o[1]) for o in ops if o[0].startswith("MUL_MAT"))
    gdn = sum(int(o[1]) for o in ops if "GATED_DELTA" in o[0])
    fa = sum(int(o[1]) for o in ops if "FLASH_ATTN" in o[0])
    key = f"ops~{round(n_ops, -1)} mm={mm} gdn={gdn} fa={fa}"
    g = groups.setdefault(key, {"count": 0, "us": 0.0, "ops": collections.Counter()})
    g["count"] += 1
    g["us"] += total
    for name, cnt, avg, t in ops:
        g["ops"][name.split(" ")[0] if not name.startswith("MUL_MAT") else name[:60]] += float(t)
print(f"blocks parsed: {sum(g['count'] for g in groups.values())}, rounds: {rounds}")
grand = 0
for k, g in sorted(groups.items(), key=lambda kv: -kv[1]["us"]):
    per_round = g["us"] / rounds / 1000
    grand += per_round
    print(f"\n[{k}] graphs={g['count']} ({g['count']/rounds:.2f}/round)  GPU {g['us']/1e6:.2f} s total = {per_round:.1f} ms/round")
    for name, t in g["ops"].most_common(8):
        print(f"    {name:60s} {t/rounds/1000:7.2f} ms/round")
print(f"\nGPU total {grand:.1f} ms/round" + (f" vs wall {wall:.1f} ms/round -> host/sync gap {wall-grand:.1f} ms/round" if wall else ""))
