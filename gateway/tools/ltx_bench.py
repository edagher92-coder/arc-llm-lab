"""Benchmark harness for ComfyUI video workflows (LTX-2.5 on the Arc Pro B60). Standard library only.

It talks to a ComfyUI that is ALREADY RUNNING (it never starts or kills one), submits one API-format workflow, waits for it by
polling (no websocket) and appends one JSON line to a results file.

Run one job:
  python ltx_bench.py ..\\workflows\\ltx25_t2v.json --url http://127.0.0.1:8188 --set prompt="a red kettle on a stove" \\
      --set width=960 --set height=544 --set seconds=4 --set seed=1 --variant baseline --flags "--reserve-vram 1.0" --results bench.jsonl
Print the commands for a list of variants (nothing is started):
  python ltx_bench.py --matrix [matrix.json] [--shell cmd|powershell]
Self test (in-process fake server, no ComfyUI needed):
  python ltx_bench.py --selftest

The workflow file is either a gateway workflow ({"meta": ..., "prompt": <graph with {{placeholders}}>}) or a bare API graph. Placeholders
are filled from --set key=value exactly like the gateway's fill_graph (a value that is a whole placeholder keeps its type: 960 is an int).
Defaults from meta.params are applied for anything not set, and a missing seed becomes a random one. "seconds" is turned into "frames"
(8n+1) when the workflow declares a frames placeholder and no frames value was given.

What is recorded (see run_one):
  wall_s            POST /prompt until /history shows the prompt finished (success or error)
  first_progress_s  POST /prompt until /queue first lists the prompt as running (a polling stand-in for "first progress")
  exec_s            execution_start to execution_success timestamps from /history, when the build provides them
  node_timings      per-node seconds from /history message timestamps, when the build provides them; otherwise parsed from --comfy-log
                    (ComfyUI only reports a node's duration over its websocket and in its console, not in /history on every build)
  host_ram_*        peak host memory in MB, only when psutil is installed (system-wide delta, or the --pid process tree)
  vram_min_free_mb  lowest torch_vram_free seen in /system_stats while polling (a coarse peak-VRAM stand-in)
"""
import argparse, copy, json, os, random, re, shlex, sys, threading, time, urllib.error, urllib.request

PH = re.compile(r"\{\{(\w+)\}\}")
FULL_PH = re.compile(r"^\{\{(\w+)\}\}$")
HERE = os.path.dirname(os.path.abspath(__file__))

try:                                                          # reuse the gateway's own substitution when it imports cleanly
    sys.path.insert(0, os.path.dirname(HERE))
    from video import fill_graph as _gw_fill, snap_frames as _gw_snap, VideoError as BenchError
except Exception:                                             # standalone fallback: same behaviour
    _gw_fill = _gw_snap = None

    class BenchError(Exception):
        pass


def fill_graph(graph, vals):
    if _gw_fill:
        return _gw_fill(graph, vals)

    def sub(x):
        if isinstance(x, dict):
            return {k: sub(v) for k, v in x.items()}
        if isinstance(x, list):
            return [sub(v) for v in x]
        if isinstance(x, str):
            m = FULL_PH.match(x)
            if m:
                if m.group(1) not in vals:
                    raise BenchError("workflow needs a value for %s" % m.group(1))
                return vals[m.group(1)]
            return PH.sub(lambda mm: str(vals.get(mm.group(1), mm.group(0))), x)
        return x
    return sub(copy.deepcopy(graph))


def snap_frames(n):
    """LTX wants 8k+1 frames."""
    if _gw_snap:
        return _gw_snap(n, "8n+1")
    return max(9, int(round((n - 1) / 8.0)) * 8 + 1)


def coerce(s):
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d*\.\d+", s):
        return float(s)
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    return s


def parse_sets(items):
    out = {}
    for it in items or []:
        k, sep, v = it.partition("=")
        if not sep or not k.strip():
            raise BenchError("--set wants key=value, got %r" % it)
        out[k.strip()] = coerce(v)
    return out


def placeholders(graph):
    return set(PH.findall(json.dumps(graph)))


def load_workflow(path):
    w = json.load(open(path, encoding="utf-8-sig"))
    if isinstance(w.get("prompt"), dict):
        return w.get("meta") or {}, w["prompt"]
    return {}, w                                              # a bare API graph


def build_values(meta, graph, sets):
    """--set values, then meta defaults, then a random seed, then frames from seconds. Returns the values dict."""
    vals = dict(sets)
    for name, p in (meta.get("params") or {}).items():
        if name not in vals and "default" in p:
            vals[name] = p["default"]
    needed = placeholders(graph)
    if "seed" in needed and vals.get("seed") in (None, "", -1):
        vals["seed"] = random.randint(0, 2 ** 31 - 1)
    if "frames" in needed and "frames" not in vals and vals.get("seconds"):
        vals["frames"] = snap_frames(float(vals["seconds"]) * float(meta.get("fps", 24)) + 1)
    elif "frames" in vals:
        vals["frames"] = snap_frames(float(vals["frames"]))
    missing = sorted(n for n in needed if n not in vals)
    if missing:
        raise BenchError("missing values for: %s (pass --set name=value)" % ", ".join(missing))
    return vals


# ---------- HTTP ----------
def http(method, url, body=None, timeout=10):
    req = urllib.request.Request(url, data=(json.dumps(body).encode() if body is not None else None),
                                 headers={"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            t = r.read()
    except urllib.error.HTTPError as e:                       # ComfyUI answers 400 with a JSON body for a rejected prompt
        t = e.read()
    t = t.strip()
    try:
        return json.loads(t) if t[:1] in (b"{", b"[") else {}
    except ValueError:
        return {}


def wait_ready(url, seconds):
    """Poll /system_stats until ComfyUI answers (the gateway does the same instead of fixed sleeps). Returns (seconds waited, stats)."""
    t0 = time.time()
    while True:
        try:
            s = http("GET", url + "/system_stats", timeout=3)
            if s:
                return time.time() - t0, s
        except Exception:
            pass
        if time.time() - t0 >= seconds:
            raise BenchError("ComfyUI did not answer /system_stats within %s s" % seconds)
        time.sleep(0.5)


def vram_free_mb(stats):
    devs = (stats or {}).get("devices") or []
    if not devs:
        return None
    d = devs[0]
    v = d.get("torch_vram_free", d.get("vram_free"))
    return round(v / 2 ** 20, 1) if isinstance(v, (int, float)) else None


# ---------- host RAM (optional) ----------
class RamSampler(threading.Thread):
    def __init__(self, pid=None, every=0.5):
        super().__init__(daemon=True)
        self.pid, self.every, self.peak, self.base, self.stop_ev = pid, every, 0, 0, threading.Event()
        try:
            import psutil
            self.ps = psutil
        except ImportError:
            self.ps = None

    def _now(self):
        ps = self.ps
        if self.pid:
            try:
                p = ps.Process(self.pid)
                return sum(x.memory_info().rss for x in [p] + p.children(recursive=True))
            except Exception:
                return 0
        return ps.virtual_memory().used

    def run(self):
        if not self.ps:
            return
        self.base = self.peak = self._now()
        while not self.stop_ev.wait(self.every):
            self.peak = max(self.peak, self._now())

    def result(self):
        if not self.ps:
            return {}
        self.stop_ev.set()
        mb = lambda b: round(b / 2 ** 20, 1)
        return {"host_ram_peak_mb": mb(self.peak), "host_ram_delta_mb": mb(self.peak - self.base), "host_ram_scope": "process-tree" if self.pid else "system-used"}


# ---------- timings ----------
def history_timings(entry, graph):
    """Pull execution timing out of a /history entry. Messages are [name, data]; build-dependent, so every field is optional."""
    msgs = ((entry or {}).get("status") or {}).get("messages") or []
    ts = lambda d: (d or {}).get("timestamp")
    start = next((ts(m[1]) for m in msgs if m and m[0] == "execution_start"), None)
    end = next((ts(m[1]) for m in msgs if m and m[0] in ("execution_success", "execution_error")), None)
    out = {}
    if start is not None and end is not None:
        out["exec_s"] = round((end - start) / 1000.0, 2)
    cached = next((m[1].get("nodes") for m in msgs if m and m[0] == "execution_cached" and isinstance(m[1], dict)), None)
    if cached is not None:
        out["cached_nodes"] = len(cached)
    steps = [(str(m[1].get("node")), ts(m[1])) for m in msgs if m and isinstance(m[1], dict) and m[1].get("node") is not None and ts(m[1]) is not None]
    nodes = []
    for i, (nid, t) in enumerate(steps):
        nxt = steps[i + 1][1] if i + 1 < len(steps) else end
        if nxt is not None:
            nodes.append({"node": nid, "class": ((graph.get(nid) or {}).get("class_type")), "s": round((nxt - t) / 1000.0, 2)})
    if nodes:
        out["node_timings"] = nodes
    return out


SAMPLER_LINE = re.compile(r"(\d+)/(\d+) \[(\d+:\d+(?::\d+)?)<[^,\]]*, +([\d.]+)(s/it|it/s)\]")


def parse_log(text):
    """Optional: read ComfyUI's console log. 'Prompt executed in N seconds' and the last progress-bar line of each bar."""
    out = {"prompt_executed_s": [float(x) for x in re.findall(r"Prompt executed in ([\d.]+) seconds", text)]}
    bars = {}
    for m in SAMPLER_LINE.finditer(text):
        bars[m.group(2)] = {"steps": int(m.group(2)), "elapsed": m.group(3), "rate": "%s %s" % (m.group(4), m.group(5))}
    if bars:
        out["progress_bars"] = list(bars.values())
    return out


# ---------- one run ----------
def run_one(url, graph, meta, label="", variant="", flags="", sets=None, timeout=3600, poll=1.0, ready_s=0, pid=None, comfy_log="",
            free_after=False, workflow_path=""):
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "label": label, "variant": variant, "flags": flags, "url": url,
           "workflow": os.path.basename(workflow_path), "status": "error"}
    vals = build_values(meta, graph, sets or {})
    rec["params"] = {k: (v if not isinstance(v, str) or len(v) <= 80 else v[:77] + "...") for k, v in vals.items()}
    filled = fill_graph(graph, vals)
    if ready_s:
        rec["ready_s"], stats = wait_ready(url, ready_s)
        rec["ready_s"] = round(rec["ready_s"], 2)
    else:
        stats = http("GET", url + "/system_stats", timeout=10)
    dev = ((stats or {}).get("devices") or [{}])[0]
    rec.update({"device": dev.get("name"), "comfyui_version": (stats.get("system") or {}).get("comfyui_version"), "vram_free_before_mb": vram_free_mb(stats)})
    log_off = os.path.getsize(comfy_log) if comfy_log and os.path.exists(comfy_log) else 0
    ram = RamSampler(pid)
    ram.start()
    t0 = time.time()
    r = http("POST", url + "/prompt", {"prompt": filled, "client_id": "ltx-bench"}, timeout=30)
    rec["submit_s"] = round(time.time() - t0, 3)
    pidp = r.get("prompt_id")
    if not pidp or r.get("node_errors"):
        rec["error"] = "rejected: %s" % json.dumps(r)[:400]
        rec.update(ram.result())
        return rec
    rec["prompt_id"], first, vmin, entry = pidp, None, None, None
    while time.time() - t0 < timeout:
        try:
            q = http("GET", url + "/queue", timeout=10)
            if first is None and any(len(x) > 1 and x[1] == pidp for x in (q.get("queue_running") or [])):
                first = time.time() - t0
            v = vram_free_mb(http("GET", url + "/system_stats", timeout=10))
            if v is not None:
                vmin = v if vmin is None else min(vmin, v)
            h = http("GET", "%s/history/%s" % (url, pidp), timeout=10)
            if pidp in h:
                entry = h[pidp]
                break
        except Exception as e:
            rec["poll_error"] = repr(e)[:200]
        time.sleep(poll)
    wall = time.time() - t0
    rec["wall_s"] = round(wall, 2)
    if first is None and entry is not None:
        first = 0.0                                           # finished between two polls: no better estimate than "immediately"
    rec["first_progress_s"] = round(first, 2) if first is not None else None
    rec["vram_min_free_mb"] = vmin
    if entry is None:
        rec["error"] = "timeout after %s s" % timeout
        try:
            http("POST", url + "/interrupt", {}, timeout=10)
        except Exception:
            pass
    else:
        st = entry.get("status") or {}
        rec["status"] = st.get("status_str") or ("success" if entry.get("outputs") else "unknown")
        if rec["status"] == "error":
            msgs = [m for m in st.get("messages", []) if m and m[0] == "execution_error"]
            rec["error"] = json.dumps(msgs[-1][1])[:400] if msgs else "execution failed"
        rec.update(history_timings(entry, filled))
        outs = []
        for node in (entry.get("outputs") or {}).values():
            for key in ("videos", "gifs", "images", "audio"):
                outs += [f.get("filename") for f in node.get(key) or [] if isinstance(f, dict) and f.get("filename")]
        rec["outputs"] = outs
    rec.update(ram.result())
    if comfy_log and os.path.exists(comfy_log):
        try:
            with open(comfy_log, "rb") as f:
                f.seek(log_off)
                rec["log"] = parse_log(f.read().decode("utf-8", "replace"))
        except OSError:
            pass
    if free_after:                                            # what the gateway does before it kills ComfyUI
        t1 = time.time()
        try:
            http("POST", url + "/free", {"unload_models": True, "free_memory": True}, timeout=60)
            rec["free_s"] = round(time.time() - t1, 2)
            rec["vram_free_after_mb"] = vram_free_mb(http("GET", url + "/system_stats", timeout=10))
        except Exception as e:
            rec["free_error"] = repr(e)[:200]
    return rec


def append_result(path, rec):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")


# ---------- matrix ----------
BASE_FLAGS = ["--listen", "127.0.0.1", "--port", "8188", "--disable-auto-launch", "--reserve-vram", "1.0", "--use-pytorch-cross-attention",
              "--preview-method", "none", "--disable-all-custom-nodes", "--disable-partner-nodes", "--disable-metadata"]
BASE_ENV = {"SYCL_CACHE_PERSISTENT": "1", "UR_L0_ENABLE_RELAXED_ALLOCATION_LIMITS": "1", "UR_L0_USE_RELAXED_ALLOCATION_LIMITS": "1", "ZES_ENABLE_SYSMAN": "1"}
DEFAULT_MATRIX = {
    "workflow": "gateway\\workflows\\ltx25_t2v.json", "url": "http://127.0.0.1:8188", "results": "bench-results.jsonl",
    "comfy": "python_embeded\\python.exe -s ComfyUI\\main.py --windows-standalone-build",
    "base_flags": BASE_FLAGS, "base_env": BASE_ENV,
    "params": {"prompt": "a slow dolly shot of a red kettle on a gas stove, steam rising, morning light", "seed": 1, "seconds": 4, "width": 768, "height": 416},
    "variants": [
        {"name": "baseline"},
        {"name": "no-relaxed-alloc", "env_remove": ["UR_L0_ENABLE_RELAXED_ALLOCATION_LIMITS", "UR_L0_USE_RELAXED_ALLOCATION_LIMITS"]},
        {"name": "no-sysman", "env_remove": ["ZES_ENABLE_SYSMAN"]},
        {"name": "no-persistent-cache", "env_remove": ["SYCL_CACHE_PERSISTENT"]},
        {"name": "lowvram-reference", "flags_add": ["--lowvram"]},
        {"name": "daily-960x544", "params": {"width": 960, "height": 544, "seconds": 4}},
        {"name": "hero-960x544", "params": {"width": 960, "height": 544, "seconds": 5}},
    ]}


def variant_plan(m, v):
    flags = [f for f in m.get("base_flags", BASE_FLAGS)]
    drop = set(v.get("flags_remove") or [])
    flags = [f for f in flags if f not in drop] + list(v.get("flags_add") or [])
    env = dict(m.get("base_env", BASE_ENV))
    for k in v.get("env_remove") or []:
        env.pop(k, None)
    env.update(v.get("env") or {})
    params = dict(m.get("params") or {})
    params.update(v.get("params") or {})
    return flags, env, params


def q(shell, s):
    s = str(s)
    if shell == "powershell":
        return "'%s'" % s.replace("'", "''")
    return '"%s"' % s.replace('"', "'") if re.search(r"[\s&|<>^]", s) else s


def matrix_text(m, shell="cmd"):
    """The exact commands to run for each variant. Nothing is started here."""
    out = ["# Run each variant in turn. Stop ComfyUI between variants (a fresh process each time), and run every variant twice:",
           "# the first run is a cold start, the second is warm. Terminal A starts ComfyUI (open a NEW terminal for each variant so removed",
           "# env vars do not linger), terminal B runs the benchmark.", ""]
    for v in m["variants"]:
        flags, env, params = variant_plan(m, v)
        out.append("# ---- variant: %s" % v["name"])
        out.append("# terminal A (from the ComfyUI portable folder)")
        for k in sorted(env):
            out.append(("$env:%s = '%s'" % (k, env[k])) if shell == "powershell" else 'set "%s=%s"' % (k, env[k]))
        out.append("%s %s" % (m.get("comfy", "python main.py"), " ".join(q(shell, f) for f in flags)))
        sets = " ".join("--set %s=%s" % (k, q(shell, val)) for k, val in params.items())
        out.append("# terminal B")
        out.append("python gateway\\tools\\ltx_bench.py %s --url %s --variant %s --flags %s %s --ready-s 300 --free-after --results %s" % (
            q(shell, m["workflow"]), m.get("url", "http://127.0.0.1:8188"), v["name"], q(shell, " ".join(flags)), sets, q(shell, m.get("results", "bench-results.jsonl"))))
        out.append("")
    return "\n".join(out)


# ---------- self test ----------
def _fake_server(mode="ok"):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    state = {"prompts": {}, "freed": 0, "posted": []}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, obj, code=200):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            now = time.time()
            if self.path.startswith("/system_stats"):
                return self.send({"system": {"comfyui_version": "0.39-fake"}, "devices": [{"name": "fake xpu", "torch_vram_free": (8 if state["prompts"] else 20) * 2 ** 30}]})
            if self.path.startswith("/queue"):
                run = [[0, pid, {}, {}, []] for pid, p in state["prompts"].items() if p["run_at"] <= now < p["done_at"]]
                return self.send({"queue_running": run, "queue_pending": []})
            if self.path.startswith("/history/"):
                pid = self.path.split("/")[-1]
                p = state["prompts"].get(pid)
                if not p or now < p["done_at"]:
                    return self.send({})
                if mode == "error":
                    return self.send({pid: {"outputs": {}, "status": {"status_str": "error", "messages": [["execution_error", {"exception_message": "OOM"}]]}}})
                return self.send({pid: {"outputs": {"9": {"videos": [{"filename": "clip.mp4", "type": "output"}]}}, "status": {"status_str": "success", "messages": [
                    ["execution_start", {"prompt_id": pid, "timestamp": 1000}], ["execution_cached", {"nodes": ["1", "2"], "timestamp": 1001}],
                    ["executing_fake", {"node": "5", "timestamp": 1100}], ["executing_fake", {"node": "9", "timestamp": 2100}],
                    ["execution_success", {"prompt_id": pid, "timestamp": 3100}]]}}})
            self.send({}, 404)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path == "/prompt":
                state["posted"].append(body)
                if "{{" in json.dumps(body["prompt"]):
                    return self.send({"error": "unfilled", "node_errors": {"1": "x"}}, 400)
                pid = "p%d" % (len(state["prompts"]) + 1)
                state["prompts"][pid] = {"run_at": time.time() + 0.3, "done_at": time.time() + (30 if mode == "hang" else 0.9)}
                return self.send({"prompt_id": pid, "node_errors": {}})
            if self.path == "/free":
                state["freed"] += 1
                return self.send({})
            if self.path == "/interrupt":
                return self.send({})
            self.send({}, 404)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, state


def selftest():
    import tempfile
    ok = []

    def check(name, cond):
        ok.append(bool(cond))
        print(("PASS " if cond else "FAIL ") + name)

    # placeholders and coercion
    check("coerce", [coerce(x) for x in ("5", "0.5", "true", "abc", "-1")] == [5, 0.5, True, "abc", -1])
    g = {"1": {"class_type": "A", "inputs": {"w": "{{width}}", "t": "x {{prompt}} y", "s": "{{seed}}", "f": "{{frames}}"}}}
    v = build_values({"fps": 24, "params": {"width": {"default": 768}}}, g, parse_sets(["prompt=hi", "seconds=4", "seed=-1"]))
    f = fill_graph(g, v)["1"]["inputs"]
    check("fill keeps int type", f["w"] == 768 and isinstance(f["w"], int) and f["t"] == "x hi y")
    check("seed randomised", isinstance(f["s"], int) and f["s"] >= 0)
    check("seconds -> frames 8n+1", f["f"] == 97 and f["f"] % 8 == 1)
    check("frames snapped", build_values({}, {"1": {"inputs": {"f": "{{frames}}"}}}, {"frames": 100})["frames"] % 8 == 1)
    try:
        build_values({}, g, {})
        check("missing value raises", False)
    except BenchError as e:
        check("missing value raises", "width" in str(e))
    try:
        parse_sets(["novalue"])
        check("bad --set raises", False)
    except BenchError:
        check("bad --set raises", True)
    # history timings and log parsing
    entry = {"status": {"messages": [["execution_start", {"timestamp": 0}], ["x", {"node": "1", "timestamp": 500}], ["x", {"node": "2", "timestamp": 2500}], ["execution_success", {"timestamp": 3000}]]}}
    t = history_timings(entry, {"1": {"class_type": "Enc"}})
    check("exec_s and node timings", t["exec_s"] == 3.0 and [n["s"] for n in t["node_timings"]] == [2.0, 0.5] and t["node_timings"][0]["class"] == "Enc")
    lg = parse_log("Prompt executed in 41.50 seconds\n100%|####| 8/8 [00:12<00:00,  1.52s/it]\n")
    check("log parse", lg["prompt_executed_s"] == [41.5] and lg["progress_bars"][0]["rate"] == "1.52 s/it")
    # full runs against the fake server
    with tempfile.TemporaryDirectory() as d:
        wf = os.path.join(d, "wf.json")
        json.dump({"meta": {"fps": 24, "params": {"width": {"default": 768}}}, "prompt": {"9": {"class_type": "Save", "inputs": {"w": "{{width}}", "p": "{{prompt}}", "n": "{{seed}}", "f": "{{frames}}"}}}}, open(wf, "w"))
        res = os.path.join(d, "r.jsonl")
        srv, st = _fake_server("ok")
        url = "http://127.0.0.1:%d" % srv.server_address[1]
        meta, graph = load_workflow(wf)
        rec = run_one(url, graph, meta, variant="t", sets={"prompt": "hello", "seconds": 2, "seed": 3}, poll=0.1, ready_s=5, free_after=True, workflow_path=wf)
        append_result(res, rec)
        row = json.loads(open(res).read().splitlines()[-1])
        check("run success + outputs", row["status"] == "success" and row["outputs"] == ["clip.mp4"])
        check("wall >= first progress >= 0", row["wall_s"] >= row["first_progress_s"] >= 0)
        check("exec_s and node timings from history", row["exec_s"] == 2.1 and [n["s"] for n in row["node_timings"]] == [1.0, 1.0])
        check("filled graph submitted", st["posted"][0]["prompt"]["9"]["inputs"] == {"w": 768, "p": "hello", "n": 3, "f": 49})
        check("free called + vram recorded", st["freed"] == 1 and row.get("vram_min_free_mb") == 8192.0 and row.get("device") == "fake xpu")
        check("one JSON line per run", len(open(res).read().splitlines()) == 1)
        srv.shutdown()
        srv, st = _fake_server("error")
        url = "http://127.0.0.1:%d" % srv.server_address[1]
        rec = run_one(url, graph, meta, sets={"prompt": "x", "seconds": 2}, poll=0.1)
        check("error status recorded", rec["status"] == "error" and "OOM" in rec["error"])
        srv.shutdown()
        srv, st = _fake_server("hang")
        url = "http://127.0.0.1:%d" % srv.server_address[1]
        rec = run_one(url, graph, meta, sets={"prompt": "x", "seconds": 2}, poll=0.1, timeout=1.0)
        check("timeout recorded", rec["status"] == "error" and "timeout" in rec["error"] and rec["first_progress_s"] is not None)
        srv.shutdown()
    # matrix
    txt = matrix_text(DEFAULT_MATRIX)
    check("matrix lists every variant", all(("variant: " + v["name"]) in txt for v in DEFAULT_MATRIX["variants"]))
    nr = txt.split("# ---- variant: no-relaxed-alloc")[1].split("# ---- variant:")[0]
    check("matrix env_remove honoured", "RELAXED" not in nr and "SYCL_CACHE_PERSISTENT" in nr)
    lv = txt.split("# ---- variant: lowvram-reference")[1].split("# ---- variant:")[0]
    check("matrix flags_add honoured", "--lowvram" in lv and "--lowvram" not in txt.split("# ---- variant: baseline")[1].split("# ---- variant:")[0])
    check("powershell form", "$env:SYCL_CACHE_PERSISTENT = '1'" in matrix_text(DEFAULT_MATRIX, "powershell"))
    n = len(ok) - sum(ok)
    print("%d checks, %d failed" % (len(ok), n))
    return 1 if n else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workflow", nargs="?", help="workflow JSON (gateway format or bare API graph)")
    ap.add_argument("--url", default="http://127.0.0.1:8188")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="fill a {{placeholder}} (repeatable)")
    ap.add_argument("--results", default="bench-results.jsonl", help="JSON-lines file to append to")
    ap.add_argument("--variant", default="", help="name recorded with the run")
    ap.add_argument("--flags", default="", help="the ComfyUI launch flags in use (recorded only)")
    ap.add_argument("--label", default="")
    ap.add_argument("--timeout", type=float, default=3600)
    ap.add_argument("--poll", type=float, default=1.0)
    ap.add_argument("--ready-s", type=float, default=0, help="wait up to N s for /system_stats first (records ready_s)")
    ap.add_argument("--pid", type=int, default=0, help="ComfyUI process id, for per-process host RAM (needs psutil)")
    ap.add_argument("--comfy-log", default="", help="ComfyUI console log to parse for timings (only text added during the run)")
    ap.add_argument("--free-after", action="store_true", help='POST /free {"unload_models":true,"free_memory":true} afterwards and time it')
    ap.add_argument("--matrix", nargs="?", const="", metavar="FILE", help="print the commands for each variant (built-in list if no file); runs nothing")
    ap.add_argument("--shell", choices=("cmd", "powershell"), default="cmd")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    try:
        if a.matrix is not None:
            m = json.load(open(a.matrix, encoding="utf-8-sig")) if a.matrix else DEFAULT_MATRIX
            print(matrix_text(m, a.shell))
            return 0
        if not a.workflow:
            ap.error("a workflow file is required (or use --matrix / --selftest)")
        meta, graph = load_workflow(a.workflow)
        rec = run_one(a.url.rstrip("/"), graph, meta, a.label, a.variant, a.flags, parse_sets(a.set), a.timeout, a.poll, a.ready_s, a.pid or None,
                      a.comfy_log, a.free_after, a.workflow)
    except (BenchError, OSError, ValueError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    append_result(a.results, rec)
    print(json.dumps({k: rec.get(k) for k in ("variant", "status", "wall_s", "first_progress_s", "exec_s", "host_ram_peak_mb", "vram_min_free_mb", "error")}))
    return 0 if rec["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
