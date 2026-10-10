"""Build the GitHub Pages benchmark site (docs/index.html) from data/*.csv. Usage: python tools/build_site.py"""
import csv, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def rows(n): return list(csv.DictReader(open(os.path.join(ROOT, "data", n), encoding="utf-8")))

data = {
    "depth": rows("prompt-speed-vs-depth.csv"),
    "sweep": [r for r in rows("speculative-decoding-sweep.csv") if r["code_avg_tok_s"]],
    "gpus": rows("gpu-comparison.csv"),
    "vram": rows("vram-budget-64k.csv"),
    "turns": rows("agent-turns.csv"),
}
rel_path = os.path.join(ROOT, "data", "reliability-summary.json")
data["reliability"] = json.load(open(rel_path)) if os.path.exists(rel_path) else None

HTML = open(os.path.join(ROOT, "tools", "site_template.html"), encoding="utf-8").read()
out = HTML.replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")))
os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
open(os.path.join(ROOT, "docs", "index.html"), "w", encoding="utf-8").write(out)
open(os.path.join(ROOT, "docs", ".nojekyll"), "w").write("")
print("site -> docs/index.html", len(out), "bytes")
