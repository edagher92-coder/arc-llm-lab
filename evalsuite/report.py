"""Summarise results/*.jsonl into report.md + summary.json.
Headline metric: successfully completed tasks per minute (passes / total agent wall-clock minutes).
Tiering per category (pass rate across runs): >=90% AUTONOMOUS, 60-89% SUPERVISED, <60% ESCALATE.
Per task: passes in every run -> autonomous; passes in some -> supervised; passes in none -> escalate."""
import json, os, sys, glob, statistics
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tasks as SUITE

def refine(r):
    """Split 'wrong_result' into a near-miss when the correct answer appears in the agent's final message but was not saved."""
    import re
    if r.get("passed") or r.get("failure") != "wrong_result": return r
    m = re.search(r"expected=['\"]?([^'\"\s]+)", r.get("reason") or "")
    if m and "answer.txt=''" in (r.get("reason") or "") and m.group(1) in (r.get("final") or ""):
        r["failure"] = "answer_not_saved"
    return r

def load(runs=None):
    recs = []
    for p in sorted(glob.glob(os.path.join(HERE, "results", "*.jsonl"))):
        run = os.path.basename(p)[:-6]
        if runs and run not in runs: continue
        if not runs and (run.startswith("smoke") or run.startswith("sustained")): continue
        last = {}
        for l in open(p, encoding="utf-8"):
            try: r = json.loads(l)
            except Exception: continue
            if "step" in r: continue  # sustained-session records are reported separately
            last[r["id"]] = refine(r)  # latest attempt per task wins
        recs += list(last.values())
    return recs

def tier(rate):
    return "AUTONOMOUS" if rate >= 0.9 else "SUPERVISED" if rate >= 0.6 else "ESCALATE"

def pct(x): return "%.0f%%" % (100 * x)

def summarise(recs):
    runs = defaultdict(list)
    for r in recs: runs[r["run"]].append(r)
    S = {"runs": {}, "categories": {}, "tasks": {}}
    for run, rs in sorted(runs.items()):
        n = len(rs); ok = sum(r["passed"] for r in rs); wall = sum(r["wall_s"] for r in rs) / 60
        tp = [r["wall_s"] for r in rs if r["passed"]]
        gen = sum(r.get("srv_gen_tok") or 0 for r in rs); gens = sum(r.get("srv_gen_s") or 0 for r in rs)
        S["runs"][run] = dict(agent=rs[0]["agent"], cap=rs[0]["cap"], tasks=n, passed=ok, pass_rate=ok / n if n else 0,
                              total_min=round(wall, 1), completed_per_min=round(ok / wall, 3) if wall else 0,
                              median_pass_s=round(statistics.median(tp), 1) if tp else None,
                              p90_pass_s=round(sorted(tp)[int(0.9 * (len(tp) - 1))], 1) if tp else None,
                              failures=dict(Counter(r["failure"] for r in rs if not r["passed"])),
                              vram_min_free_gib=min([r["vram_min_free_gib"] for r in rs if r.get("vram_min_free_gib") is not None] or [None]) if any(r.get("vram_min_free_gib") is not None for r in rs) else None,
                              model_reloads=sum(bool(r.get("model_reloaded")) for r in rs),
                              context_overflows=sum(r.get("failure") == "context_overflow" for r in rs),
                              avg_gen_tok_s=round(gen / gens, 1) if gens else None,
                              by_cat={c: dict(n=len([r for r in rs if r["cat"] == c]), passed=sum(r["passed"] for r in rs if r["cat"] == c)) for c in SUITE.CATS})
    for c in SUITE.CATS:
        rs = [r for r in recs if r["cat"] == c]
        if not rs: continue
        rate = sum(r["passed"] for r in rs) / len(rs)
        S["categories"][c] = dict(attempts=len(rs), pass_rate=round(rate, 3), tier=tier(rate),
                                  median_s=round(statistics.median([r["wall_s"] for r in rs]), 1))
    byid = defaultdict(list)
    for r in recs: byid[r["id"]].append(r)
    for t in SUITE.TASKS:
        rs = byid.get(t["id"], [])
        if not rs: continue
        k = sum(r["passed"] for r in rs)
        S["tasks"][t["id"]] = dict(cat=t["cat"], runs=len(rs), passed=k,
                                   tier="AUTONOMOUS" if k == len(rs) else "SUPERVISED" if k else "ESCALATE",
                                   results={r["run"]: ("PASS" if r["passed"] else (r["failure"] or "fail")) for r in rs},
                                   reasons={r["run"]: r["reason"][:160] for r in rs if not r["passed"]})
    return S

def markdown(S):
    L = ["# arc-llm-lab: agent reliability report", ""]
    L += ["## Runs", "", "| Run | Agent | Ctx cap | Pass | Completed/min | Median pass time | p90 | Min free VRAM | Reloads | Ctx overflows | Gen tok/s |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for run, x in S["runs"].items():
        L.append("| %s | %s | %dk | %d/%d (%s) | **%.2f** | %ss | %ss | %s GB | %d | %d | %s |" % (run, x["agent"], x["cap"] // 1024, x["passed"], x["tasks"], pct(x["pass_rate"]), x["completed_per_min"],
                 x["median_pass_s"], x["p90_pass_s"], x["vram_min_free_gib"], x["model_reloads"], x["context_overflows"], x["avg_gen_tok_s"]))
    L += ["", "## Categories (all runs)", "", "| Category | Attempts | Pass rate | Median time | Tier |", "|---|---|---|---|---|"]
    for c, x in S["categories"].items():
        L.append("| %s | %d | %s | %ss | **%s** |" % (c, x["attempts"], pct(x["pass_rate"]), x["median_s"], x["tier"]))
    L += ["", "## Failure reasons", ""]
    for run, x in S["runs"].items():
        L.append("- %s: %s" % (run, ", ".join("%s %d" % kv for kv in sorted(x["failures"].items(), key=lambda kv: -kv[1])) or "none"))
    for tname in ("ESCALATE", "SUPERVISED"):
        L += ["", "## Tasks — %s" % tname, ""]
        for i, x in S["tasks"].items():
            if x["tier"] == tname:
                L.append("- `%s` (%s): %s%s" % (i, x["cat"], ", ".join("%s=%s" % kv for kv in x["results"].items()),
                                               ("  — " + "; ".join(v for v in x["reasons"].values() if v)) if x["reasons"] else ""))
    return "\n".join(L) + "\n"

def sustained_md():
    L = []
    for p in sorted(glob.glob(os.path.join(HERE, "results", "sustained-*.jsonl"))):
        rs = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
        if not rs: continue
        run = os.path.basename(p)[:-6]; ok = sum(r["passed"] for r in rs); wall = sum(r["wall_s"] for r in rs)
        probe = [r for r in rs if r["step"] == 10]
        # new_test_passed = only this step's own hidden test (older result files do not have it, so it is optional).
        has_new = any("new_test_passed" in r for r in rs); new_ok = sum(bool(r.get("new_test_passed")) for r in rs)
        L += ["", "### %s — %d/%d steps passed (cumulative tests)%s, %.1f min, peak prompt %d tokens, compactions %d, overflow errors %d, reloads %d, memory probe %s" % (
            run, ok, len(rs), (", %d/%d own-step tests passed" % (new_ok, len(rs))) if has_new else "", wall / 60, max(r["peak_prompt_tok"] for r in rs), max(r["compactions_total"] for r in rs),
            sum(r["overflow_error"] for r in rs), sum(r["model_reloaded"] for r in rs), ("PASS" if probe and probe[0]["passed"] else "FAIL" if probe else "n/a")), "",
            "| Step | Rules | Pass (cumulative) | This step's own test | Time | Peak prompt | Server ctx | Compactions | Failure |", "|---|---|---|---|---|---|---|---|---|"]
        for r in rs:
            nt = "-" if "new_test_passed" not in r else ("PASS" if r["new_test_passed"] else "FAIL")
            L.append("| %d | v%d | %s | %s | %ss | %d | %s | %d | %s |" % (r["step"], r["rules"], "PASS" if r["passed"] else "FAIL", nt, r["wall_s"], r["peak_prompt_tok"], r["srv_n_ctx"], r["compactions_total"], r["failure"] or ""))
    return ("\n## Sustained sessions (48K-64K)\n" + "\n".join(L) + "\n") if L else ""

if __name__ == "__main__":
    runs = sys.argv[1].split(",") if len(sys.argv) > 1 else None
    S = summarise(load(runs))
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump(S, open(os.path.join(HERE, "results", "summary.json"), "w"), indent=1)
    md = markdown(S) + sustained_md()
    open(os.path.join(HERE, "results", "report.md"), "w", encoding="utf-8").write(md)
    print(md)
