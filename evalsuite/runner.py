"""arc-llm-lab runner: runs the 100-task suite against Claude Code (claude-qwen) or Codex (codex-qwen), unattended.
Usage:  python runner.py --agent claude|codex [--run NAME] [--cap 32768] [--ids a,b] [--cats coding,tool] [--limit N]
Resumable: re-running with the same --run skips tasks already recorded in results/<run>.jsonl.
Each task gets a fresh workspace, a hard timeout, and a hidden checker run AFTER the agent exits."""
import argparse, json, os, re, shutil, subprocess, sys, threading, time, traceback, urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tasks as SUITE

GOV = r"C:\AI\governor"
BIN = os.environ.get("QWEN_BIN", os.path.join(os.environ.get("USERPROFILE", ""), "bin"))  # where claude-qwen.cmd / codex-qwen.cmd live
NOWIN = 0x08000000  # CREATE_NO_WINDOW

def jload(p):
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}

def running(): return jload(os.path.join(GOV, "running.json"))
def status(): return jload(os.path.join(GOV, "public", "status.json"))

def metrics(port):
    try:
        txt = urllib.request.urlopen("http://127.0.0.1:%s/metrics" % port, timeout=3).read().decode()
    except Exception:
        return {}
    out = {}
    for l in txt.splitlines():
        if l.startswith("llamacpp:"):
            p = l.split()
            try: out[p[0][9:]] = float(p[1])
            except Exception: pass
    return out

class Sampler(threading.Thread):
    """Samples governor status every 5 s: VRAM, loaded ctx, reloads, processing."""
    def __init__(self):
        super().__init__(daemon=True); self.stop = False
        self.min_free = None; self.max_used = None; self.ctx = set(); self.starts = set(); self.samples = 0
    def run(self):
        while not self.stop:
            s = status(); r = running()
            if s:
                self.samples += 1
                f, u = s.get("vram_free_gib"), s.get("vram_used_gib")
                if f is not None: self.min_free = f if self.min_free is None else min(self.min_free, f)
                if u is not None: self.max_used = u if self.max_used is None else max(self.max_used, u)
                if s.get("n_ctx"): self.ctx.add(s["n_ctx"])
            if r.get("started"): self.starts.add(r["started"])
            time.sleep(5)

def kill_tree(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NOWIN)

def agent_cmd(agent, ws, last):
    if agent == "claude":
        return ('"%s\\claude-qwen.cmd" -p --output-format json --max-turns 40 --permission-mode acceptEdits '
                '--allowedTools "Bash Read Edit Write Glob Grep"') % BIN
    return ('"%s\\codex-qwen.cmd" exec --skip-git-repo-check -s workspace-write -c approval_policy="never" --ephemeral --json '
            '-C "%s" -o "%s" -') % (BIN, ws, last)

def parse_claude(out):
    """claude -p --output-format json prints one JSON object (last line)."""
    for line in reversed(out.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                j = json.loads(line)
                u = j.get("usage") or {}
                return dict(final=j.get("result") or "", turns=j.get("num_turns"), subtype=j.get("subtype"), is_error=bool(j.get("is_error")),
                            in_tok=u.get("input_tokens"), cached_tok=u.get("cache_read_input_tokens"), out_tok=u.get("output_tokens"))
            except Exception:
                pass
    return dict(final=out[-500:], turns=None, subtype="no_json", is_error=True)

def parse_codex(out, last):
    final = ""
    try: final = open(last, encoding="utf-8").read()
    except Exception: pass
    turns = 0; it = ct = ot = 0; err = None
    for line in out.splitlines():
        try: e = json.loads(line)
        except Exception: continue
        t = e.get("type", "")
        if t == "item.completed" and (e.get("item") or {}).get("type") in ("command_execution", "file_change", "mcp_tool_call"): turns += 1
        if t == "turn.completed":
            u = e.get("usage") or {}; it += u.get("input_tokens", 0) or 0; ct += u.get("cached_input_tokens", 0) or 0; ot += u.get("output_tokens", 0) or 0
        if t in ("error", "turn.failed"): err = json.dumps(e)[:300]
    return dict(final=final, turns=turns, subtype="error" if err else "ok", is_error=bool(err), error=err, in_tok=it, cached_tok=ct, out_tok=ot)

def classify(passed, timed_out, info, out, rc):
    if passed: return None
    blob = (out or "")[-20000:] + " " + (info.get("final") or "") + " " + (info.get("error") or "")
    if timed_out: return "timeout"
    if re.search(r"exceed_context_size|context size|context length|context window|prompt is too long", blob, re.I): return "context_overflow"
    if info.get("subtype") == "error_max_turns": return "max_turns"
    if re.search(r"ECONNREFUSED|connection refused|502 Bad Gateway|503|stream disconnected|API Error", blob): return "api_error"
    if info.get("is_error") or rc not in (0, None): return "agent_error"
    if (info.get("final") or "").strip().endswith("?"): return "asked_user"
    return "wrong_result"

def run_task(t, agent, run, cap, resdir):
    work = os.path.join(HERE, "work", run, t["id"])
    shutil.rmtree(work, ignore_errors=True)
    SUITE.materialize(t, work)
    meta = os.path.join(HERE, "work", run, "_meta"); os.makedirs(meta, exist_ok=True)
    pf = os.path.join(meta, t["id"] + ".prompt.txt"); open(pf, "w", encoding="utf-8").write(t["prompt"])
    last = os.path.join(meta, t["id"] + ".last.txt"); logf = os.path.join(meta, t["id"] + ".log")
    env = dict(os.environ, QWEN_CLIENT_CAP=str(cap))
    r0 = running(); port = r0.get("port", 10001); m0 = metrics(port)
    smp = Sampler(); smp.start()
    t0 = time.time(); timed_out = False
    with open(pf, "rb") as fin, open(logf, "wb") as fout:
        p = subprocess.Popen(agent_cmd(agent, work, last), cwd=work, stdin=fin, stdout=fout, stderr=subprocess.STDOUT, shell=True, env=env, creationflags=NOWIN)
        try:
            rc = p.wait(timeout=t["timeout"])
        except subprocess.TimeoutExpired:
            timed_out = True; kill_tree(p.pid); time.sleep(2); rc = None
    wall = round(time.time() - t0, 1)
    smp.stop = True
    out = open(logf, encoding="utf-8", errors="replace").read()
    info = parse_claude(out) if agent == "claude" else parse_codex(out, last)
    r1 = running(); m1 = metrics(r1.get("port", port))
    reloaded = len(smp.starts | {r0.get("started"), r1.get("started")} - {None}) > 1
    d = lambda k: (m1.get(k, 0) - m0.get(k, 0)) if m1.get(k, 0) >= m0.get(k, 0) else m1.get(k, 0)
    c0 = time.time()
    try:
        passed, why = t["check"](work)
    except Exception as e:
        passed, why = False, "checker exception: %r" % e
    rec = dict(run=run, agent=agent, cap=cap, suite=SUITE.SUITE_VERSION, id=t["id"], cat=t["cat"], passed=bool(passed), reason=(why or "")[:600],
               failure=classify(passed, timed_out, info, out, rc), wall_s=wall, check_s=round(time.time() - c0, 1), rc=rc, timed_out=timed_out,
               turns=info.get("turns"), subtype=info.get("subtype"), client_in_tok=info.get("in_tok"), client_cached_tok=info.get("cached_tok"), client_out_tok=info.get("out_tok"),
               srv_prompt_tok=d("prompt_tokens_total"), srv_cached_tok=d("prompt_tokens_cached_total"), srv_gen_tok=d("tokens_predicted_total"),
               srv_prompt_s=round(d("prompt_seconds_total"), 1), srv_gen_s=round(d("tokens_predicted_seconds_total"), 1),
               vram_min_free_gib=smp.min_free, vram_max_used_gib=smp.max_used, n_ctx=sorted(smp.ctx), model_reloaded=reloaded,
               final=(info.get("final") or "")[-400:], ended=datetime.now().isoformat(timespec="seconds"))
    with open(os.path.join(resdir, run + ".jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    if passed and not os.environ.get("EVAL_KEEP"):
        shutil.rmtree(work, ignore_errors=True)
    return rec

def interleave(ts):
    by = {}
    for t in ts: by.setdefault(t["cat"], []).append(t)
    out = []
    while any(by.values()):
        for c in SUITE.CATS:
            if by.get(c): out.append(by[c].pop(0))
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True, choices=["claude", "codex"])
    ap.add_argument("--run"); ap.add_argument("--cap", type=int, default=32768)
    ap.add_argument("--ids"); ap.add_argument("--cats"); ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    run = a.run or "%s-%dk" % (a.agent, a.cap // 1024)
    resdir = os.path.join(HERE, "results"); os.makedirs(resdir, exist_ok=True)
    done = set()
    rp = os.path.join(resdir, run + ".jsonl")
    if os.path.exists(rp):
        for l in open(rp, encoding="utf-8"):
            try: done.add(json.loads(l)["id"])
            except Exception: pass
    ts = SUITE.TASKS
    if a.ids: ts = [t for t in ts if t["id"] in a.ids.split(",")]
    if a.cats: ts = [t for t in ts if t["cat"] in a.cats.split(",")]
    ts = [t for t in interleave(ts) if t["id"] not in done]
    if a.limit: ts = ts[:a.limit]
    prog = os.path.join(resdir, run + ".progress.json")
    npass = 0
    for i, t in enumerate(ts, 1):
        json.dump(dict(run=run, current=t["id"], index=i, total=len(ts), passed_this_session=npass, pid=os.getpid(), time=datetime.now().isoformat(timespec="seconds")), open(prog, "w"))
        try:
            rec = run_task(t, a.agent, run, a.cap, resdir)
            npass += rec["passed"]
            print("[%d/%d] %-28s %s %6.1fs %s" % (i, len(ts), t["id"], "PASS" if rec["passed"] else "FAIL", rec["wall_s"], rec["failure"] or ""), flush=True)
        except Exception:
            traceback.print_exc()
    json.dump(dict(run=run, current=None, finished=True, passed_this_session=npass, total=len(ts), time=datetime.now().isoformat(timespec="seconds")), open(prog, "w"))

if __name__ == "__main__":
    main()
