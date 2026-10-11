"""Video queue tests: plain asserts against mock llama-swap and a mock ComfyUI subprocess. Run: python tests/test_video.py"""
import json, os, socket, sys, tempfile, threading, time, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, D)
import video
TMP = tempfile.mkdtemp(prefix="vidtest-"); PY = sys.executable; HERE = os.path.dirname(os.path.abspath(__file__))
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

class Swap:
    """llama-swap stand-in: /running, /api/models/unload/<id>, and the model server's /slots on the same port."""
    def __init__(self, loaded=True, busy=False):
        self.loaded, self.busy, self.unloads = loaded, busy, 0; me = self; self.port = free_port()
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def send(self, o):
                b = json.dumps(o).encode(); self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
            def do_GET(self):
                if self.path.startswith("/running"): return self.send({"running": [{"model": "m", "state": "ready", "proxy": "http://127.0.0.1:%d" % me.port}] if me.loaded else []})
                if self.path.startswith("/slots"): return self.send([{"id": 0, "is_processing": me.busy}])
                self.send({})
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0)); self.rfile.read(n)
                if self.path.startswith("/api/models/unload/"): me.loaded = False; me.unloads += 1
                self.send({})
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), H); threading.Thread(target=self.srv.serve_forever, daemon=True).start()
    def close(self): self.srv.shutdown()

WF = {"meta": {"description": "test", "est_minutes": "1", "fps": 24, "frames_rule": "8n+1", "params": {
        "prompt": {"type": "str", "required": True}, "negative": {"type": "str", "default": "blurry"},
        "width": {"type": "int", "default": 768, "min": 256, "max": 1280, "multiple_of": 32}, "height": {"type": "int", "default": 512, "min": 256, "max": 720, "multiple_of": 32},
        "frames": {"type": "int", "default": 97, "min": 9, "max": 241}, "seed": {"type": "int"}, "image": {"type": "image"}}},
      "prompt": {"1": {"class_type": "T", "inputs": {"text": "{{prompt}} | {{negative}}", "w": "{{width}}", "h": "{{height}}", "n": "{{frames}}", "seed": "{{seed}}"}}}}

# A staged workflow: "staged" names two stage graphs kept in wf/stages/ (so they never show up as workflows of their own).
ENC = {"meta": {"label": "encoding"}, "prompt": {"1": {"class_type": "ENC_CLASS", "inputs": {"prompt": "{{prompt}}", "negative": "{{negative}}", "name": "cond"}}}}
SMP = {"meta": {"label": "sampling"}, "prompt": {"1": {"class_type": "ElzLoadConditioning", "inputs": {"prompt": "{{prompt}}", "name": "cond", "w": "{{width}}", "n": "{{frames}}", "seed": "{{seed}}"}}}}

class Rig:
    def __init__(self, mode="ok", loaded=True, busy=False, quiet_s=0, timeout=60, killfile=True, staged=False, ntfy=None, enc_class="ElzSaveConditioning"):
        self.t = tempfile.mkdtemp(dir=TMP); self.swap = Swap(loaded, busy); self.port = free_port()
        os.makedirs(os.path.join(self.t, "wf")); json.dump(WF, open(os.path.join(self.t, "wf", "t2v.json"), "w"))
        if staged:
            os.makedirs(os.path.join(self.t, "wf", "stages"))
            json.dump({"meta": dict(WF["meta"], stages=["enc", "smp"]), "prompt": {}}, open(os.path.join(self.t, "wf", "staged.json"), "w"))
            json.dump(json.loads(json.dumps(ENC).replace("ENC_CLASS", enc_class)), open(os.path.join(self.t, "wf", "stages", "enc.json"), "w"))
            json.dump(SMP, open(os.path.join(self.t, "wf", "stages", "smp.json"), "w"))
        self.mode_file = os.path.join(self.t, "mode.txt"); open(self.mode_file, "w").write("MAX\n")
        self.comfy_log = os.path.join(self.t, "comfy-requests.log"); self.img_root = os.path.join(self.t, "shared"); os.makedirs(self.img_root)
        cfg = {"comfy_dir": self.t, "comfy_cmd": [PY, os.path.join(HERE, "mock_comfy.py"), str(self.port), mode, self.comfy_log], "comfy_url": "http://127.0.0.1:%d" % self.port,
               "workflows_dir": os.path.join(self.t, "wf"), "input_dir": os.path.join(self.t, "input"), "allowed_roots": [self.img_root], "job_timeout_s": timeout,
               "start_timeout_s": 20, "comfy_settle_s": 0.05, "poll_s": 0.1, "tick_s": 0.1, "llm": {"swap_url": "http://127.0.0.1:%d" % self.swap.port, "model_id": "m", "quiet_s": quiet_s,
               "governor_mode_file": self.mode_file, "unload_timeout_s": 10}}
        cfg.update(ntfy or {})
        self.kill = os.path.join(self.t, "KILL"); self.shared = []; self.cfgd = cfg
        self.q = video.Queue(video.Cfg(cfg, self.t), self.t, self.kill, share=lambda p: "https://x/%s" % os.path.basename(p))
        self.q.start()
    def wait(self, jid, states, secs=30):
        end = time.time() + secs
        while time.time() < end:
            j = self.q.get(jid)
            if j["state"] in states: return j
            time.sleep(0.1)
        raise AssertionError("job %s stuck in %s (wanted %s)" % (jid, self.q.get(jid)["state"], states))
    def mode(self): return open(self.mode_file).read().strip()
    def cond_dir(self, jid): return os.path.join(self.t, "video", "cond", jid)
    def log_lines(self): return open(self.comfy_log).read().splitlines() if os.path.exists(self.comfy_log) else []
    def prompts(self): return [l for l in self.log_lines() if l.startswith("prompt ")]
    def starts(self): return [l for l in self.log_lines() if l.startswith("start ")]
    def spy_http(self):
        """Record every ntfy POST (url, body, headers, timeout) while passing everything else to the real env.http. Returns the list."""
        posts, orig = [], self.q.env.http
        def http(method, url, body=None, headers=None, timeout=10):
            if "ntfy.test" in url:
                posts.append(dict(url=url, body=body, headers=dict(headers or {}), timeout=timeout)); return {}
            return orig(method, url, body, headers, timeout)
        self.q.env.http = http; return posts
    def settle(self, posts, n=1, secs=5):
        end = time.time() + secs
        while len(posts) < n and time.time() < end: time.sleep(0.05)
        time.sleep(0.6)                                          # a second POST, if there were going to be one, lands in this window
    def comfy_up(self):
        try: s = socket.create_connection(("127.0.0.1", self.port), 0.5); s.close(); return True
        except OSError: return False
    def close(self): self.q.stop(); self.swap.close()

def test_out_dir_elsewhere():
    t = tempfile.mkdtemp(dir=TMP); st = os.path.join(t, "fresh-state"); out = os.path.join(t, "clips")      # neither folder exists yet
    q = video.Queue(video.Cfg({"comfy_dir": t, "comfy_cmd": ["x"], "out_dir": out, "workflows_dir": t}, t), st)
    assert os.path.isdir(os.path.join(st, "video")) and os.path.isdir(out)
    with q.lock: q.jobs.append(dict(id="aaaaaaaa", workflow="w", params={}, state="done", created=time.time())); q._save()
    assert os.path.exists(os.path.join(st, "video", "jobs.json"))

def test_templates():
    vals, files = video.resolve_params(WF, {"prompt": "a fox", "seconds": 5, "width": 1000, "height": 9999, "seed": -1}, None)
    assert vals["frames"] == 121, vals                       # 5 s * 24 fps + 1 = 121 = 8*15+1
    assert vals["width"] == 992 and vals["height"] == 704, vals     # clamped (max 720) and snapped to a multiple of 32
    assert isinstance(vals["seed"], int) and vals["negative"] == "blurry" and not files
    g = video.fill_graph(WF["prompt"], vals); i = g["1"]["inputs"]
    assert i["w"] == 992 and isinstance(i["w"], int) and i["text"] == "a fox | blurry" and WF["prompt"]["1"]["inputs"]["w"] == "{{width}}"
    for bad, msg in (({}, "required"), ({"prompt": "x", "bogus": 3}, "does not take")):
        try: video.resolve_params(WF, bad, None); raise AssertionError("accepted %r" % bad)
        except video.VideoError as e: assert msg in str(e), e

def test_image_roots():
    r = Rig()
    try:
        out = os.path.join(TMP, "outside.png"); open(out, "wb").write(b"x")
        try: r.q.submit("t2v", {"prompt": "x", "image": out}); raise AssertionError("outside image accepted")
        except video.VideoError as e: assert "outside" in str(e)
        ok = os.path.join(r.img_root, "a.png"); open(ok, "wb").write(b"x")
        jid, pos, est = r.q.submit("t2v", {"prompt": "x", "image": ok}); assert pos == 1
        try: r.q.submit("nope", {"prompt": "x"}); raise AssertionError
        except video.VideoError as e: assert "unknown workflow" in str(e)
    finally: r.close()

def test_lifecycle():
    r = Rig()
    try:
        jid, pos, est = r.q.submit("t2v", {"prompt": "a fox", "seconds": 2}); j = r.wait(jid, ("done", "failed"))
        assert j["state"] == "done", j
        assert r.swap.unloads == 1 and not r.swap.loaded                       # the LLM was unloaded
        assert j["links"] == ["https://x/clip_00001.mp4"] and open(j["files_out"][0], "rb").read() == b"FAKEMP4DATA"
        time.sleep(0.5); assert not r.comfy_up()                                # ComfyUI was killed
        assert r.mode() == "MAX" and not os.path.exists(r.q.lock_path)          # governor handed back
        sent = [l for l in open(r.comfy_log) if l.startswith("prompt ")][0]
        assert "{{" not in sent and "a fox | blurry" in sent and '"n": 49' in sent, sent    # 2 s * 24 + 1 = 49
    finally: r.close()

def test_waits_for_busy_llm():
    r = Rig(busy=True, quiet_s=0)
    try:
        jid, _, _ = r.q.submit("t2v", {"prompt": "x"}); time.sleep(1.2)
        j = r.q.get(jid); assert j["state"] == "waiting" and r.swap.unloads == 0 and r.mode() == "MAX", j
        r.swap.busy = False; r.q.last_busy = 0
        assert r.wait(jid, ("done", "failed"))["state"] == "done"
    finally: r.close()

def test_quiet_window():
    r = Rig(busy=False, quiet_s=3)
    try:
        jid, _, _ = r.q.submit("t2v", {"prompt": "x"}); r.q.last_busy = time.time(); time.sleep(1.0)
        assert r.q.get(jid)["state"] == "waiting" and r.swap.unloads == 0     # idle for under quiet_s
        assert r.wait(jid, ("done", "failed"), 20)["state"] == "done"
    finally: r.close()

def test_comfy_error_and_crash():
    for mode, word in (("error", "OOM on XPU"), ("crash", "crashed")):
        r = Rig(mode=mode)
        try:
            jid, _, _ = r.q.submit("t2v", {"prompt": "x"}); j = r.wait(jid, ("done", "failed"))
            assert j["state"] == "failed" and word in j["error"], j
            time.sleep(0.5); assert not r.comfy_up() and r.mode() == "MAX"
        finally: r.close()

def test_cancel_running():
    r = Rig(mode="hang")
    try:
        jid, _, _ = r.q.submit("t2v", {"prompt": "x"}); r.wait(jid, ("running",))
        assert "cancel requested" in r.q.cancel_job(jid); j = r.wait(jid, ("cancelled", "failed"))
        assert j["state"] == "cancelled" and "interrupt" in open(r.comfy_log).read()
        time.sleep(0.5); assert not r.comfy_up() and r.mode() == "MAX"
    finally: r.close()

def test_timeout():
    r = Rig(mode="hang", timeout=1)
    try:
        jid, _, _ = r.q.submit("t2v", {"prompt": "x"}); j = r.wait(jid, ("failed", "done"), 30)
        assert j["state"] == "failed" and "exceeded" in j["error"], j; time.sleep(0.5); assert not r.comfy_up()
    finally: r.close()

def test_kill_switch():
    r = Rig(busy=True)
    try:
        jid, _, _ = r.q.submit("t2v", {"prompt": "x"}); time.sleep(0.5); open(r.kill, "w").write("1")
        j = r.wait(jid, ("failed",)); assert "KILLED" in j["error"] and r.swap.unloads == 0
    finally: r.close()

def test_queue_cap_and_cancel_queued():
    r = Rig(busy=True)
    try:
        r.q.cfg.max_queue = 2; a, _, _ = r.q.submit("t2v", {"prompt": "a"}); b, _, _ = r.q.submit("t2v", {"prompt": "b"})
        try: r.q.submit("t2v", {"prompt": "c"}); raise AssertionError("cap ignored")
        except video.VideoError as e: assert "full" in str(e)
        assert "cancel" in r.q.cancel_job(b) and r.q.cancel_job("zzzz") == "no such job"
    finally: r.close()

def test_crash_recovery():
    r = Rig(busy=True); r.q.stop()
    j = dict(id="deadbeef", workflow="t2v", params={}, files={}, state="running", created=time.time())
    r.q.jobs.append(j); r.q._save(); open(r.q.lock_path, "w").write("BALANCED"); open(r.mode_file, "w").write("OFF\n")
    q2 = video.Queue(r.q.cfg, r.t, r.kill)
    assert q2.get("deadbeef")["state"] == "failed" and r.mode() == "BALANCED" and not os.path.exists(q2.lock_path)
    r.swap.close()

def test_lock_keeps_first_mode():
    r = Rig(busy=True); r.q.stop()
    r.q._take_gpu(); r.q._take_gpu()                       # a second take must not record OFF as the mode to restore
    assert r.q._lock_read()["mode"] == "MAX" and r.mode() == "OFF"; r.q._restore_mode(); assert r.mode() == "MAX"
    r.swap.close()

class FakeServer:
    """Captures @server.tool functions so the MCP tools can be called directly."""
    def __init__(self): self.tools = {}
    def tool(self, name, description=""):
        def deco(f): self.tools[name] = f; return f
        return deco

def tools_for(r):
    """Swap the rig's Queue for the one video.register() builds from the same config, and return the captured MCP tools."""
    r.q.stop(); srv = FakeServer()
    r.q = video.register(srv, {"video": r.cfgd}, r.t, r.t, r.kill, share_fn=lambda p: "https://x/%s" % os.path.basename(p)); return srv.tools

def test_sidecar_and_result():
    r = Rig()
    try:
        jid, _, _ = r.q.submit("t2v", {"prompt": "a fox", "seconds": 2, "seed": 7}); j = r.wait(jid, ("done", "failed")); assert j["state"] == "done", j
        side = j["files_out"][0] + ".json"; m = json.load(open(side))
        assert m["seed"] == 7 and m["workflow"] == "t2v" and m["params"]["prompt"] == "a fox" and m["clip"] == "clip_00001.mp4" and m["render_s"] >= 0 and m["job_id"] == jid, m
        mt = os.path.getmtime(side); res = r.q.result(jid); r.q.result(jid); r.q.status(jid); assert os.path.getmtime(side) == mt     # written once, not per call
        assert res["clips"] == ["clip_00001.mp4"] and res["links"] == ["https://x/clip_00001.mp4"], res
        assert res["meta"]["seed"] == 7 and res["meta"]["workflow"] == "t2v" and res["meta"]["seconds"] is not None and res["meta"]["wall_s"] is not None and "files_out" not in json.dumps(res)
        st = r.q.status(jid); assert st["state"] == "done" and st["clips"] == ["clip_00001.mp4"] and "queue_position" not in st and st["elapsed_s"] >= 0, st
    finally: r.close()

def test_result_failed_unknown_pending():
    r = Rig(mode="error")
    try:
        jid, _, _ = r.q.submit("t2v", {"prompt": "x"}); r.wait(jid, ("failed",))
        res = r.q.result(jid); assert res["state"] == "failed" and "OOM" in res["error"] and "clips" not in res, res
        assert r.q.result("zzzz") is None and r.q.status("zzzz") is None
    finally: r.close()
    r = Rig(busy=True)
    try:
        a, _, _ = r.q.submit("t2v", {"prompt": "a"}); b, _, _ = r.q.submit("t2v", {"prompt": "b"}); time.sleep(0.5)
        assert r.q.result(b)["state"] in ("queued", "waiting") and "video_status" in r.q.result(b)["note"]
        st = r.q.status(b); assert st["queue_position"] == 2 and st["eta_min"] == 2.0 and "clips" not in st, st      # est_minutes "1" per job
        assert r.q.status(a)["queue_position"] == 1
    finally: r.close()

def test_mcp_tools():
    r = Rig()
    try:
        t = tools_for(r)
        assert {"video_workflows", "video_generate", "video_status", "video_result", "video_queue", "video_cancel"} <= set(t)
        assert t["video_result"]("zzzz") == "no such job" and t["video_status"]("zzzz") == "no such job" and json.loads(t["video_queue"]()) == []
        t0 = time.time(); out = t["video_generate"]("a fox", seconds=2); assert time.time() - t0 < 2, "video_generate blocked"      # returns at once
        g = json.loads(out); assert g["position"] == 1 and g["workflow"] == "t2v" and g["est_minutes"] == "1", out
        q = json.loads(t["video_queue"]()); assert [x["id"] for x in q] == [g["job_id"]] and q[0]["state"] != "done"
        assert json.loads(t["video_status"](g["job_id"]))["job_id"] == g["job_id"]
        assert json.loads(t["video_result"](g["job_id"]))["state"] != "done"
        r.wait(g["job_id"], ("done",)); res = json.loads(t["video_result"](g["job_id"]))
        assert res["clips"] == ["clip_00001.mp4"] and res["links"] and res["meta"]["workflow"] == "t2v", res
        assert json.loads(t["video_queue"]())[0]["state"] == "done" and t["video_cancel"](g["job_id"]) == "already done"
        assert t["video_generate"]("x", workflow="nope").startswith("Not queued")
    finally: r.close()

def test_seconds_snap_and_bad_params():
    wf = {"meta": {"fps": 25, "params": {"prompt": {"type": "str"}, "seconds": {"type": "int", "default": 4, "min": 2, "max": 10}, "seed": {"type": "int"}, "cfg": {"type": "float", "min": 1, "max": 9}}}, "prompt": {}}
    v, _ = video.resolve_params(wf, {"prompt": "x", "seconds": 4}, None); assert v["seconds"] == 3.84 and round(v["seconds"] * 25 + 1) == 97, v
    wf["meta"]["fps"] = 24; v, _ = video.resolve_params(wf, {"prompt": "x", "seconds": 4}, None); assert v["seconds"] == 4.0
    for bad in ({"seconds": "abc"}, {"cfg": float("inf")}, {"cfg": float("nan")}, {"cfg": "x"}, {"seed": float("inf")}, {"seed": "zz"}):
        try: video.resolve_params(wf, dict(bad, prompt="x"), None); raise AssertionError("accepted %r" % bad)
        except video.VideoError: pass
    assert video.resolve_params(wf, {"prompt": "x", "seed": 2 ** 40}, None)[0]["seed"] == 2 ** 32 - 1
    assert video.resolve_params(wf, {"prompt": "x", "seed": -5}, None)[0]["seed"] in range(0, 2 ** 31)      # negative = random

def test_recover_kills_comfy_pid():
    r = Rig(busy=True); r.q.stop(); killed = []
    r.q.jobs.append(dict(id="cafebabe", workflow="t2v", params={}, files={}, state="running", created=time.time())); r.q._save()
    json.dump({"mode": "LEAN", "pid": 4242}, open(r.q.lock_path, "w")); open(r.mode_file, "w").write("OFF\n")
    env = video.Env(); env.kill_pid = killed.append
    q2 = video.Queue(r.q.cfg, r.t, r.kill, env=env)
    assert killed == [4242] and r.mode() == "LEAN" and not os.path.exists(q2.lock_path); r.swap.close()

def test_refuses_existing_comfy_and_empty_output():
    r = Rig(); srv = video.Env()
    try:                                                       # something already answers on comfy_url
        import subprocess
        p = subprocess.Popen([PY, os.path.join(HERE, "mock_comfy.py"), str(r.port), "ok", r.comfy_log]); time.sleep(1.0)
        jid, _, _ = r.q.submit("t2v", {"prompt": "x"}); j = r.wait(jid, ("failed", "done"))
        assert j["state"] == "failed" and "already running" in j["error"], j
        p.kill(); p.wait()
    finally: r.close()
    r = Rig()
    try:
        r.q.env.http_orig = r.q.env.http
        def http(method, url, body=None, headers=None, timeout=10):
            o = r.q.env.http_orig(method, url, body, headers, timeout)
            if "/history/" in url and o: o = {k: dict(v, outputs={}) for k, v in o.items()}
            return o
        r.q.env.http = http
        jid, _, _ = r.q.submit("t2v", {"prompt": "x"}); j = r.wait(jid, ("failed", "done"))
        assert j["state"] == "failed" and "no output files" in j["error"], j; time.sleep(0.5); assert r.mode() == "MAX"
    finally: r.close()

def test_gpu_lock_blocks_mode_change():
    import approvals
    r = Rig(); old = approvals.GPU_BUSY
    try:
        approvals.GPU_BUSY = lambda: os.path.exists(r.q.lock_path)
        open(r.q.lock_path, "w").write("MAX")
        assert approvals.GPU_BUSY() is True
        os.remove(r.q.lock_path); assert approvals.GPU_BUSY() is False
    finally: approvals.GPU_BUSY = old; r.close()

def test_restore_even_if_kill_fails():
    r = Rig()
    try:
        def boom(proc): raise RuntimeError("taskkill failed")
        r.q.env.kill_tree = boom
        jid, _, _ = r.q.submit("t2v", {"prompt": "x"}); r.wait(jid, ("done", "failed")); time.sleep(0.5)
        assert r.mode() == "MAX" and not os.path.exists(r.q.lock_path); r.q.proc and r.q.proc.kill()
    finally: r.close()

def test_fav_persists_survives_retention_and_sidecar():
    r = Rig()
    try:
        jid, _, _ = r.q.submit("t2v", {"prompt": "keep me", "seconds": 2}); j = r.wait(jid, ("done",))
        assert not j.get("fav") and r.q.set_fav("zzzzzzzz", True) is False
        assert r.q.set_fav(jid, True) is True and r.q.get(jid)["fav"] is True
        side = json.load(open(j["files_out"][0] + ".json")); assert side["fav"] is True and side["job_id"] == jid       # the sidecar carries it too
        r.q.stop(); r.q.cfg.keep_jobs = 10
        with r.q.lock:
            for i in range(14): r.q.jobs.append(dict(id="%08x" % (i + 1), workflow="t2v", params={}, files={}, state="done", created=time.time() + i + 1))
            r.q._save()
        saved = [x["id"] for x in json.load(open(r.q.jobs_path))]
        assert jid in saved and len(saved) == 11, saved                                  # the 10 newest plus the favourite, which is older than all of them
        assert [x["id"] for x in r.q.favourites()] == [jid]
        assert r.q.set_fav(jid, False) and not r.q.get(jid)["fav"] and json.load(open(j["files_out"][0] + ".json"))["fav"] is False
        with r.q.lock: r.q._save()
        assert jid not in [x["id"] for x in json.load(open(r.q.jobs_path))]            # once unstarred it ages out like any other job
        r.q.set_fav(jid, True)
        assert video.Queue(r.q.cfg, r.t, r.kill).get(jid)["fav"] is True                 # survives a restart
    finally: r.close()

NTFY = {"ntfy_url": "https://ntfy.test", "ntfy_topic": "elz-video-xyz", "ntfy_click_base": "https://gw.example/"}

def test_ntfy_one_post_per_finished_job():
    r = Rig(ntfy=NTFY)
    try:
        posts = r.spy_http()
        jid, _, _ = r.q.submit("t2v", {"prompt": "a secret fox", "seconds": 2}); assert r.wait(jid, ("done",))["state"] == "done"; r.settle(posts)
        assert len(posts) == 1, posts; p = posts[0]
        assert p["url"] == "https://ntfy.test/elz-video-xyz" and p["timeout"] == 5, p
        h = p["headers"]; assert h["Title"].startswith("Video ready") and h["Tags"] and h["Priority"] == "default" and h["X-Click"] == "https://gw.example/approvals/studio#job=" + jid, h
        assert "secret fox" not in p["body"] and "secret fox" not in json.dumps(h) and jid in p["body"], p       # no prompt unless asked
    finally: r.close()

def test_ntfy_one_post_per_failed_job_and_none_for_cancelled():
    r = Rig(mode="error", ntfy=NTFY)
    try:
        posts = r.spy_http()
        jid, _, _ = r.q.submit("t2v", {"prompt": "a secret fox"}); assert r.wait(jid, ("failed",))["state"] == "failed"; r.settle(posts)
        assert len(posts) == 1 and posts[0]["headers"]["Title"].startswith("Video failed") and posts[0]["headers"]["Priority"] == "high", posts
        assert "OOM" not in posts[0]["body"] and "secret fox" not in posts[0]["body"], posts[0]          # error text can echo inputs: not sent
    finally: r.close()
    r = Rig(mode="hang", ntfy=NTFY)
    try:
        posts = r.spy_http()
        jid, _, _ = r.q.submit("t2v", {"prompt": "x"}); r.wait(jid, ("running",)); r.q.cancel_job(jid); assert r.wait(jid, ("cancelled",))["state"] == "cancelled"; time.sleep(0.8)
        assert posts == [], posts
    finally: r.close()

def test_ntfy_include_prompt_and_unconfigured_and_fail_soft():
    r = Rig(ntfy=dict(NTFY, ntfy_include_prompt=True))
    try:
        posts = r.spy_http()
        jid, _, _ = r.q.submit("t2v", {"prompt": "a red kettle", "seconds": 2}); r.wait(jid, ("done",)); r.settle(posts)
        assert len(posts) == 1 and "a red kettle" in posts[0]["body"], posts
    finally: r.close()
    for cfg in ({}, {"ntfy_url": "https://ntfy.test"}, {"ntfy_topic": "t"}):          # unconfigured or half configured: nothing leaves the PC
        r = Rig(ntfy=cfg)
        try:
            posts = r.spy_http(); jid, _, _ = r.q.submit("t2v", {"prompt": "x", "seconds": 2}); r.wait(jid, ("done",)); time.sleep(0.6); assert posts == [], (cfg, posts)
        finally: r.close()
    r = Rig(ntfy=NTFY)
    try:
        orig = r.q.env.http
        def boom(method, url, body=None, headers=None, timeout=10):
            if "ntfy.test" in url: raise OSError("ntfy unreachable")
            return orig(method, url, body, headers, timeout)
        r.q.env.http = boom
        jid, _, _ = r.q.submit("t2v", {"prompt": "x", "seconds": 2}); j = r.wait(jid, ("done", "failed")); time.sleep(0.6)
        assert j["state"] == "done" and r.q.get(jid)["state"] == "done" and r.mode() == "MAX"      # a dead ntfy never fails the job
    finally: r.close()

def test_staged_two_processes_one_lease():
    r = Rig(staged=True)
    try:
        spy = []; orig_popen, orig_kill = r.q.env.popen, r.q.env.kill_tree
        def popen(cmd, cwd, env, log_path):
            spy.append(("popen", r.mode(), env.get("ELZ_COND_DIR"), [p.poll() is not None for p in procs])); p = orig_popen(cmd, cwd, env, log_path); procs.append(p); return p
        def kill_tree(proc): spy.append(("kill",)); return orig_kill(proc)
        procs = []; r.q.env.popen, r.q.env.kill_tree = popen, kill_tree
        jid, _, _ = r.q.submit("staged", {"prompt": "a fox", "seconds": 2}); j = r.wait(jid, ("done", "failed"))
        assert j["state"] == "done" and j["progress"] == 100.0, j
        pr = r.prompts(); assert len(pr) == 2 and "ElzSaveConditioning" in pr[0] and "ElzLoadConditioning" not in pr[0] and "ElzLoadConditioning" in pr[1], pr      # stage order
        assert "a fox" in pr[0] and "a fox" in pr[1] and "{{" not in "".join(pr) and '"n": 49' in pr[1]                  # placeholders filled in both stages
        st = r.starts(); assert len(st) == 2 and st[0] != st[1], st                                                      # two different ComfyUI processes
        kinds = [x[0] for x in spy]; assert kinds[:3] == ["popen", "kill", "popen"], spy                                    # killed between the stages, not before
        assert spy[0][1] == spy[2][1] == "OFF", spy                                                                      # the LLM never got the GPU back in between
        assert spy[0][2] == spy[2][2] == r.cond_dir(jid) and spy[2][3] == [True], spy                                    # same hand-over folder; process 1 was already dead
        end = time.time() + 5                                                                                            # the worker restores the mode after the job's terminal state
        while time.time() < end and (r.mode() != "MAX" or os.path.exists(r.q.lock_path)): time.sleep(0.05)
        assert r.swap.unloads == 1 and r.mode() == "MAX" and not os.path.exists(r.q.lock_path)                          # one lease, handed back at the end
        time.sleep(0.5); assert not r.comfy_up() and not os.path.exists(r.cond_dir(jid)), "cond file must be deleted on success"
        assert len([x for x in r.q.jobs if x["workflow"] == "staged"]) == 1 and open(j["files_out"][0], "rb").read() == b"FAKEMP4DATA"
        assert "enc" not in video.load_workflows(r.q.cfg.workflows_dir)                                                  # stage graphs are not workflows of their own
    finally: r.close()

def test_staged_progress_maps_across_stages_and_cancel_cleans_up():
    r = Rig(mode="hang_smp", staged=True)
    try:
        jid, _, _ = r.q.submit("staged", {"prompt": "x"}); end = time.time() + 30
        while time.time() < end and not str(r.q.get(jid).get("note", "")).startswith("stage 2 of 2: sampling"): time.sleep(0.05)
        j = r.q.get(jid); assert j["state"] == "running" and 15 <= j["progress"] < 100, j                              # stage 1 owns 0-15, stage 2 starts at 15
        assert os.path.isfile(os.path.join(r.cond_dir(jid), "cond.safetensors"))
        assert "cancel requested" in r.q.cancel_job(jid); j = r.wait(jid, ("cancelled", "failed")); assert j["state"] == "cancelled", j
        time.sleep(0.5); assert not r.comfy_up() and not os.path.exists(r.cond_dir(jid)) and r.mode() == "MAX" and "interrupt" in open(r.comfy_log).read()
        assert len(r.prompts()) == 2
    finally: r.close()

def test_staged_cancel_in_stage_one_skips_stage_two():
    r = Rig(mode="hang", staged=True)
    try:
        jid, _, _ = r.q.submit("staged", {"prompt": "x"}); r.wait(jid, ("running",)); time.sleep(0.5)
        r.q.cancel_job(jid); assert r.wait(jid, ("cancelled",))["state"] == "cancelled"; time.sleep(0.5)
        assert len(r.prompts()) == 1 and len(r.starts()) == 1 and "ElzLoadConditioning" not in "".join(r.log_lines())
        assert not r.comfy_up() and not os.path.exists(r.cond_dir(jid)) and r.mode() == "MAX"
    finally: r.close()

def test_staged_failed_stage_one_never_starts_stage_two():
    r = Rig(mode="error", staged=True)
    try:
        jid, _, _ = r.q.submit("staged", {"prompt": "x"}); j = r.wait(jid, ("failed", "done"))
        assert j["state"] == "failed" and "OOM on XPU" in j["error"], j; time.sleep(0.5)
        assert len(r.prompts()) == 1 and len(r.starts()) == 1 and "ElzLoadConditioning" not in "".join(r.log_lines()), r.log_lines()
        assert not r.comfy_up() and not os.path.exists(r.cond_dir(jid)) and r.mode() == "MAX" and not os.path.exists(r.q.lock_path)       # the cond file the mock wrote is gone
    finally: r.close()

def test_staged_failed_stage_two_cleans_up():
    r = Rig(mode="error_smp", staged=True)
    try:
        jid, _, _ = r.q.submit("staged", {"prompt": "x"}); j = r.wait(jid, ("failed", "done"))
        assert j["state"] == "failed" and "OOM on XPU" in j["error"], j; time.sleep(0.5)
        assert len(r.prompts()) == 2 and len(r.starts()) == 2
        assert not r.comfy_up() and not os.path.exists(r.cond_dir(jid)) and r.mode() == "MAX"
    finally: r.close()

def test_staged_stage_one_without_cond_file_stops():
    r = Rig(staged=True, enc_class="SomethingElse")                                    # stage 1 "succeeds" but writes no conditioning
    try:
        jid, _, _ = r.q.submit("staged", {"prompt": "x"}); j = r.wait(jid, ("failed", "done"))
        assert j["state"] == "failed" and "conditioning file" in j["error"], j; time.sleep(0.5)
        assert len(r.prompts()) == 1 and not r.comfy_up()
    finally: r.close()

def test_staged_validation_and_orphan_cleanup():
    r = Rig(staged=True)
    try:
        os.remove(os.path.join(r.t, "wf", "stages", "smp.json"))
        try: r.q.submit("staged", {"prompt": "x"}); raise AssertionError("queued a workflow with a missing stage")
        except video.VideoError as e: assert "smp" in str(e) and "not found" in str(e), e
        json.dump({"meta": {"stages": ["x"]}, "prompt": {"1": {"class_type": "A", "inputs": {}}}}, open(os.path.join(r.t, "wf", "stages", "smp.json"), "w"))
        try: r.q.submit("staged", {"prompt": "x"}); raise AssertionError("nested stages accepted")
        except video.VideoError as e: assert "nest" in str(e), e
        for bad in ("../x", "a/b", "", "..", 5, "enc\n"):
            try: video.load_stage(r.q.cfg.workflows_dir, bad); raise AssertionError("accepted stage name %r" % (bad,))
            except video.VideoError: pass
        assert video.stage_names({"meta": {}}) == [] and video.stage_weights({}, 2) == [15.0, 85.0] and abs(sum(video.stage_weights({}, 3)) - 100) < 1e-9
        r.q.stop(); os.makedirs(r.cond_dir("deadbeef")); open(os.path.join(r.cond_dir("deadbeef"), "cond.safetensors"), "w").write("x")
        video.Queue(r.q.cfg, r.t, r.kill); assert not os.path.exists(r.cond_dir("deadbeef")), "orphan hand-over folder survived a restart"
    finally: r.close()

def test_unstaged_job_has_no_progress_and_no_cond_env():
    r = Rig(staged=True)
    try:
        envs = []; orig = r.q.env.popen
        r.q.env.popen = lambda cmd, cwd, env, lp: (envs.append(dict(env)), orig(cmd, cwd, env, lp))[1]
        jid, _, _ = r.q.submit("t2v", {"prompt": "x", "seconds": 2}); j = r.wait(jid, ("done",))
        assert "progress" not in j and envs == [{}] and not os.path.exists(r.cond_dir(jid)) and len(r.starts()) == 1, (j, envs)
    finally: r.close()


# ---------- Video / LLM mode switch ----------
def test_mode_switch_video_and_back():
    r = Rig()
    try:
        assert r.q.mode_get()["view"] == "llm" and r.mode() == "MAX"
        open(r.mode_file, "w").write("BALANCED\n")
        g = r.q.mode_set("video"); assert g["view"] == "video" and g["hold"] and r.mode() == "OFF", g
        r.q.mode_set("video"); assert r.mode() == "OFF" and r.q._hold()["prev"] == "BALANCED"       # twice does not overwrite what to return to
        g = r.q.mode_set("llm", warm=False); assert g["view"] == "llm" and not g["hold"] and r.mode() == "BALANCED" and not os.path.exists(r.q.hold_path), g
        open(r.mode_file, "w").write("OFF\n"); g = r.q.mode_set("llm", warm=False); assert r.mode() == "MAX"         # nothing remembered: the default LLM mode
        for bad in ("gpu", "", None):
            try: r.q.mode_set(bad); assert False, bad
            except video.VideoError: pass
    finally: r.close()

def test_mode_switch_refused_while_busy_and_unconfigured():
    r = Rig(busy=True, quiet_s=3600)                                 # the LLM never goes quiet, so the job stays queued/waiting
    try:
        jid, _, _ = r.q.submit("t2v", {"prompt": "x", "seconds": 2}); time.sleep(0.4)
        for t in ("video", "llm"):
            try: r.q.mode_set(t); assert False, "switched while a job was pending"
            except video.VideoError as e: assert "queued or rendering" in str(e), e
        assert r.mode() == "MAX"
        r.q.cancel_job(jid); r.wait(jid, ("cancelled",), 10)
        assert r.q.mode_set("video")["view"] == "video"
        r.q.cfg.mode_file = ""
        try: r.q.mode_set("llm"); assert False
        except video.VideoError as e: assert "not configured" in str(e)
    finally: r.close()

def test_video_mode_survives_a_job_and_llm_warms():
    r = Rig()
    try:
        open(r.mode_file, "w").write("LEAN\n"); r.q.mode_set("video")
        jid, _, _ = r.q.submit("t2v", {"prompt": "x", "seconds": 2}); r.wait(jid, ("done",)); time.sleep(0.5)
        assert r.mode() == "OFF" and r.q.mode_get()["hold"], r.mode()                                 # still in Video mode after the render
        assert not os.path.exists(r.q.lock_path)
        posts = []; orig = r.q.env.http
        r.q.env.http = lambda m, u, b=None, headers=None, timeout=10: (posts.append((u, b)), {})[1] if u.endswith("/v1/chat/completions") else orig(m, u, b, headers, timeout)
        r.q.mode_set("llm"); end = time.time() + 3
        while not posts and time.time() < end: time.sleep(0.05)
        assert r.mode() == "LEAN" and posts and posts[0][1]["max_tokens"] == 1 and posts[0][1]["model"] == "m", (r.mode(), posts)
    finally: r.close()

def test_manual_governor_change_ends_video_mode():
    r = Rig()
    try:
        r.q.mode_set("video"); open(r.mode_file, "w").write("MAX\n")
        assert r.q.mode_get()["hold"] is False and not os.path.exists(r.q.hold_path)
    finally: r.close()

# ---------- Drive copy ----------
def drive_rig(mode, **kw):
    d = tempfile.mkdtemp(dir=TMP); return Rig(ntfy=dict({"drive_dir": os.path.join(d, "Drive"), "drive_mode": mode}, **kw)), os.path.join(d, "Drive")

def wait_for(fn, secs=10):
    end = time.time() + secs
    while time.time() < end:
        v = fn()
        if v: return v
        time.sleep(0.05)
    raise AssertionError("condition not reached")

def test_drive_all_copies_clip_and_sidecar_atomically():
    r, d = drive_rig("all")
    try:
        jid, _, _ = r.q.submit("t2v", {"prompt": "a fox", "seconds": 2, "seed": 9}); r.wait(jid, ("done",))
        j = wait_for(lambda: r.q.get(jid).get("drive_path") and r.q.get(jid))
        month = time.strftime("%Y-%m", time.localtime(j["ended"])); mp4 = os.path.join(d, month, jid + "_clip_00001.mp4")
        assert j["drive_path"] == mp4 and j["drive_rel"] == "%s/%s_clip_00001.mp4" % (month, jid) and open(mp4, "rb").read() == b"FAKEMP4DATA"
        side = json.load(open(mp4 + ".json")); assert side["prompt"] == "a fox" and side["seed"] == 9 and side["params"]["frames"] == 49 and side["render_s"] >= 0 and side["job_id"] == jid, side
        assert not [f for f in os.listdir(os.path.join(d, month)) if f.endswith(".tmp")]
        t = os.path.getmtime(mp4); assert r.q.drive_sync(jid) is True and os.path.getmtime(mp4) == t          # idempotent: nothing is copied twice
    finally: r.close()

def test_drive_favourites_only_on_star_and_off_does_nothing():
    r, d = drive_rig("favourites")
    try:
        jid, _, _ = r.q.submit("t2v", {"prompt": "x", "seconds": 2}); r.wait(jid, ("done",)); time.sleep(0.6)
        assert not r.q.get(jid).get("drive_path") and not os.path.exists(d), "a non-favourite went to Drive"
        assert r.q.drive_sync(jid) is False
        r.q.set_fav(jid, True); j = wait_for(lambda: r.q.get(jid).get("drive_path") and r.q.get(jid))
        assert os.path.isfile(j["drive_path"]) and json.load(open(j["drive_path"] + ".json"))["fav"] is True
    finally: r.close()
    r, d = drive_rig("off")
    try:
        jid, _, _ = r.q.submit("t2v", {"prompt": "x", "seconds": 2}); r.wait(jid, ("done",)); time.sleep(0.6)
        r.q.set_fav(jid, True); time.sleep(0.4); assert not os.path.exists(d) and r.q.drive_sync(jid) is False
    finally: r.close()
    assert video.Cfg({"drive_dir": "x", "drive_mode": "bogus"}).drive_mode == "off" and video.Cfg({}).drive_mode == "off"

def test_drive_failure_never_fails_the_job():
    t = tempfile.mkdtemp(dir=TMP); blocker = os.path.join(t, "file"); open(blocker, "w").write("x")       # a file where the folder should be
    r = Rig(ntfy={"drive_dir": os.path.join(blocker, "sub"), "drive_mode": "all"})
    try:
        jid, _, _ = r.q.submit("t2v", {"prompt": "x", "seconds": 2}); j = r.wait(jid, ("done", "failed"))
        j = wait_for(lambda: r.q.get(jid).get("drive_error") and r.q.get(jid))
        assert j["state"] == "done" and not j.get("drive_path") and r.mode() == "MAX", j
    finally: r.close()

# ---------- sound levelling ----------
FAKE_FFMPEG = """#!%s
import sys
a = sys.argv[1:]
open(%r, "a").write(" ".join(a) + "\\n")
if "FAIL" in open(%r).read(): sys.stderr.write("boom"); sys.exit(1)
open(a[-1], "wb").write(b"LEVELLED")
"""
def ffmpeg_rig(fail=False, keep_raw=False):
    t = tempfile.mkdtemp(dir=TMP); log = os.path.join(t, "ff.log"); flag = os.path.join(t, "flag"); open(flag, "w").write("FAIL" if fail else "ok")
    exe = os.path.join(t, "ffmpeg"); open(exe, "w").write(FAKE_FFMPEG % (sys.executable, log, flag)); os.chmod(exe, 0o755)
    return Rig(ntfy={"ffmpeg_path": exe, "loudnorm": True, "keep_raw": keep_raw}), log

def test_loudnorm_replaces_clip_copies_video_and_keeps_raw_only_if_asked():
    r, log = ffmpeg_rig(keep_raw=True)
    try:
        jid, _, _ = r.q.submit("t2v", {"prompt": "x", "seconds": 2}); j = r.wait(jid, ("done",))
        p = j["files_out"][0]; assert open(p, "rb").read() == b"LEVELLED" and j["loudnorm"] is True, j
        assert open(p[:-4] + "_raw.mp4", "rb").read() == b"FAKEMP4DATA"
        cmd = open(log).read(); assert "-c:v copy" in cmd and "loudnorm=I=-16:TP=-1.5" in cmd, cmd
        assert not [f for f in os.listdir(os.path.dirname(p)) if f.endswith(".tmp")]
    finally: r.close()
    r, log = ffmpeg_rig(keep_raw=False)
    try:
        jid, _, _ = r.q.submit("t2v", {"prompt": "x", "seconds": 2}); j = r.wait(jid, ("done",)); p = j["files_out"][0]
        assert open(p, "rb").read() == b"LEVELLED" and not os.path.exists(p[:-4] + "_raw.mp4")
    finally: r.close()

def test_loudnorm_failure_is_soft_and_unset_means_untouched():
    r, log = ffmpeg_rig(fail=True)
    try:
        jid, _, _ = r.q.submit("t2v", {"prompt": "x", "seconds": 2}); j = r.wait(jid, ("done",)); p = j["files_out"][0]
        assert j["state"] == "done" and open(p, "rb").read() == b"FAKEMP4DATA" and not j.get("loudnorm") and os.path.exists(log)
    finally: r.close()
    r = Rig(ntfy={"ffmpeg_path": "/nonexistent/ffmpeg", "loudnorm": True})                                    # cannot even start
    try:
        jid, _, _ = r.q.submit("t2v", {"prompt": "x", "seconds": 2}); j = r.wait(jid, ("done",))
        assert open(j["files_out"][0], "rb").read() == b"FAKEMP4DATA"
    finally: r.close()
    r = Rig()
    try:
        jid, _, _ = r.q.submit("t2v", {"prompt": "x", "seconds": 2}); j = r.wait(jid, ("done",)); assert "loudnorm" not in j
    finally: r.close()

# ---------- interactive ComfyUI session ----------
def post_prompt(port, marker="ui"):
    """What ComfyUI's own UI (CueForge) does: submit a prompt straight to ComfyUI. Returns the prompt id."""
    import urllib.request
    g = {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "UI shot " + marker}}, "2": {"class_type": "RandomNoise", "inputs": {"noise_seed": 4242}}}
    req = urllib.request.Request("http://127.0.0.1:%d/prompt" % port, json.dumps({"prompt": g, "client_id": "ui-" + marker}).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=5))["prompt_id"]

def session_up(r, secs=20):
    r.q.session_start(); wait_for(lambda: r.q.session_info()["state"] == "ready", secs)

def test_session_lease_reuse_by_queue_jobs_and_stop():
    r = Rig()
    try:
        session_up(r)
        assert r.mode() == "OFF" and r.swap.unloads == 1 and r.comfy_up() and r.q.session_info()["active"], "the session must take the GPU like a job"
        for fn in (lambda: r.q.session_start(), lambda: r.q.mode_set("llm")):
            try: fn(); raise AssertionError("accepted during a session")
            except video.VideoBusy: pass
        jid, _, _ = r.q.submit("t2v", {"prompt": "x", "seconds": 2}); j = r.wait(jid, ("done", "failed"))
        assert j["state"] == "done" and len(r.starts()) == 1 and r.comfy_up() and r.mode() == "OFF", "a queue job must reuse ComfyUI and leave it running"
        assert r.q.session_info()["active"] and r.q.session_info()["idle_s"] is not None
        r.q.session_stop()
        assert not r.q.session_info()["active"] and r.mode() == "MAX" and not os.path.exists(r.q.lock_path)
        wait_for(lambda: not r.comfy_up(), 10)
    finally: r.close()

def test_session_refused_while_a_job_runs_and_stop_without_session_is_noop():
    r = Rig(mode="slow", quiet_s=0)
    try:
        assert r.q.session_stop()["active"] is False
        jid, _, _ = r.q.submit("t2v", {"prompt": "x", "seconds": 2}); r.wait(jid, ("starting", "running"))
        try: r.q.session_start(); raise AssertionError("session started during a job")
        except video.VideoBusy: pass
        r.wait(jid, ("done",))
    finally: r.close()

def test_session_auto_stops_when_idle_and_restores_llm():
    r = Rig(ntfy={"comfy_session_idle_min": 0.03, "comfy_session_watch_s": 0.1})
    try:
        session_up(r); assert r.mode() == "OFF"
        wait_for(lambda: not r.q.session_info()["active"], 15)
        assert r.mode() == "MAX" and not os.path.exists(r.q.lock_path)
    finally: r.close()

def test_session_activity_keeps_it_alive():
    r = Rig(ntfy={"comfy_session_idle_min": 0.05, "comfy_session_watch_s": 0.1})       # 3 s idle limit
    try:
        session_up(r); end = time.time() + 6
        while time.time() < end:
            post_prompt(r.port, str(time.time())); time.sleep(0.7)                        # history keeps growing: not idle
        assert r.q.session_info()["active"], "activity must reset the idle timer"
    finally: r.close()

def watcher_rig(**extra):
    t = tempfile.mkdtemp(dir=TMP); drive = os.path.join(t, "drive"); log = os.path.join(t, "ff.log"); flag = os.path.join(t, "flag"); open(flag, "w").write("ok")
    exe = os.path.join(t, "ffmpeg"); open(exe, "w").write(FAKE_FFMPEG % (sys.executable, log, flag)); os.chmod(exe, 0o755)
    cfg = {"comfy_session_watch_s": 0.2, "comfy_session_idle_min": 5, "ffmpeg_path": exe, "loudnorm": True, "drive_dir": drive, "drive_mode": "all"}; cfg.update(extra)
    return Rig(ntfy=cfg), drive

def test_session_watcher_levels_and_copies_cueforge_renders_once():
    r, drive = watcher_rig()
    try:
        session_up(r); pid = post_prompt(r.port, "a")
        j = wait_for(lambda: next((x for x in r.q.jobs if x.get("comfy_pid") == pid and x.get("drive_path")), None), 20)
        assert j["state"] == "done" and j["source"] == "comfy" and j["loudnorm"] is True and j["params"]["prompt"] == "UI shot a" and j["params"]["seed"] == 4242, j
        p = j["files_out"][0]; assert open(p, "rb").read() == b"LEVELLED" and p.startswith(r.q.out_dir)
        side = json.load(open(j["drive_path"] + ".json")); assert side["prompt"] == "UI shot a" and side["workflow_graph"]["2"]["inputs"]["noise_seed"] == 4242 and open(j["drive_path"], "rb").read() == b"LEVELLED"
        time.sleep(1.5); n = len([x for x in r.q.jobs if x.get("comfy_pid") == pid]); ff = open(os.path.join(os.path.dirname(drive), "ff.log")).read().count("\n")
        assert n == 1 and ff == 1, "a prompt id must be ingested once (jobs %d, ffmpeg runs %d)" % (n, ff)
        jid, _, _ = r.q.submit("t2v", {"prompt": "x", "seconds": 2}); r.wait(jid, ("done",)); time.sleep(1.0)
        assert len([x for x in r.q.jobs if x.get("source") == "comfy"]) == 1, "the queue's own render must not be ingested as a CueForge render"
    finally: r.close()

# ---- self-healing ComfyUI start (stalled spawn after the LLM exits) ----
class FakeClock:
    """Stands in for video.time: sleep() just advances the clock, so a 300 s start-up runs in microseconds."""
    def __init__(self): self.now = 1000.0
    def time(self): return self.now
    def sleep(self, s): self.now += s
class FakeProc:
    _n = 100
    def __init__(self): FakeProc._n += 1; self.pid = FakeProc._n; self.dead = False
    def poll(self): return 1 if self.dead else None
class StallEnv(video.Env):
    """plan: one entry per spawn: 'stall' (silent, never answers), 'slow' (writes to the log, answers only after answer_after s), 'ok' (writes, answers at once)."""
    def __init__(self, plan, clock, answer_after=10 ** 9):
        self.plan, self.clock, self.answer_after, self.spawns, self.kills, self.slept = list(plan), clock, answer_after, [], [], []
        self.up_at = None; self.log_path = None; self.write_log = False
    def http(self, method, url, body=None, headers=None, timeout=10):
        if "/system_stats" in url:
            if self.write_log: self.write_log = False; open(self.log_path, "ab").write(b"Starting ComfyUI\n")     # output appears after the spawn, as in real life
            if self.up_at is not None and self.clock.now >= self.up_at: return {"system": {}}
            raise OSError("refused")
        return {}
    def popen(self, cmd, cwd, env, log_path):
        kind = self.plan.pop(0); p = FakeProc(); p.kind = kind; self.spawns.append((p, dict(env)))
        open(log_path, "ab").close(); self.log_path = log_path
        if kind != "stall":
            self.write_log = True
            self.up_at = self.clock.now + (0 if kind == "ok" else self.answer_after)
        else: self.up_at = None
        return p
    def kill_tree(self, proc): proc.dead = True; self.kills.append(proc.pid)
    def sleep(self, secs): self.slept.append(secs)

def stall_rig(plan, answer_after=10 ** 9, **extra):
    t = tempfile.mkdtemp(dir=TMP); clock = FakeClock()
    cfg = dict({"comfy_dir": t, "comfy_cmd": ["x"], "workflows_dir": t, "start_timeout_s": 300, "comfy_stall_s": 45, "poll_s": 1}, **extra)
    env = StallEnv(plan, clock, answer_after); q = video.Queue(video.Cfg(cfg, t), t, env=env)
    return q, env, clock

def with_clock(clock, f):
    real = video.time; video.time = clock
    try: return f()
    finally: video.time = real

def test_popen_unbuffered_env():
    seen = {}
    class P(video.Env):
        pass
    import subprocess
    real = subprocess.Popen
    def fake(cmd, cwd=None, env=None, stdin=None, stdout=None, stderr=None): seen.update(env); seen["_stdin"] = stdin; return object()
    subprocess.Popen = fake
    try:
        log = os.path.join(TMP, "unbuf.log")
        P().popen(["x"], TMP, {"A": "1"}, log); assert seen["PYTHONUNBUFFERED"] == "1" and seen["A"] == "1", seen
        assert seen["_stdin"] is subprocess.DEVNULL, "ComfyUI must not inherit the MCP stdio pipe as stdin (it hung at start-up)"
        seen.clear(); P().popen(["x"], TMP, {"PYTHONUNBUFFERED": "0"}, log); assert seen["PYTHONUNBUFFERED"] == "0", seen      # an explicit value wins
    finally: subprocess.Popen = real

def test_stalled_spawn_restarts_once():
    q, env, clock = stall_rig(["stall", "ok"])
    with_clock(clock, q._start_comfy)
    assert len(env.spawns) == 2 and env.kills == [env.spawns[0][0].pid], (len(env.spawns), env.kills)
    assert q.proc is env.spawns[1][0] and q._lock_read()["pid"] == q.proc.pid          # the lock follows the respawned pid
    log = open(q.log_path).read(); assert "[gateway] ComfyUI produced no output in 45 s; restarting once" in log, log
    assert 45 <= clock.now - 1000 < 60, clock.now                                      # restarted at the stall mark, not at the deadline

def test_two_stalls_raise_no_third_spawn():
    q, env, clock = stall_rig(["stall", "stall", "ok"])
    try: with_clock(clock, q._start_comfy); raise AssertionError("two stalled spawns were accepted")
    except video.VideoError as e: assert "stalled" in str(e) and q.log_path in str(e), e
    assert len(env.spawns) == 2 and len(env.kills) == 2 and len(env.plan) == 1, "no third spawn"

def test_slow_but_logging_spawn_not_restarted():
    q, env, clock = stall_rig(["slow"], answer_after=200)                              # logs at once, answers after 200 s (< start_timeout_s)
    with_clock(clock, q._start_comfy); assert len(env.spawns) == 1 and env.kills == [] and "restarting" not in open(q.log_path).read()
    q, env, clock = stall_rig(["slow", "ok"])                                           # logs but never answers: waits the full start_timeout_s, no restart
    try: with_clock(clock, q._start_comfy); raise AssertionError
    except video.VideoError as e: assert "did not answer within 300 s" in str(e) and "stalled" not in str(e), e
    assert len(env.spawns) == 1 and env.kills == [] and clock.now - 1000 >= 300

def test_settle_after_unload_only():
    class Q(video.Queue):
        def _start_comfy(self, extra_env=None): self.order.append("start"); raise video.VideoError("stop here")
    for sess, want in ((False, [3.0]), (True, [])):
        t = tempfile.mkdtemp(dir=TMP); os.makedirs(os.path.join(t, "wf")); json.dump(WF, open(os.path.join(t, "wf", "t2v.json"), "w"))
        env = StallEnv([], FakeClock()); env.process_running = lambda n: False; env.http = lambda m, u, b=None, headers=None, timeout=10: {}
        q = Q(video.Cfg({"comfy_dir": t, "comfy_cmd": ["x"], "workflows_dir": os.path.join(t, "wf"), "llm": {"unload_timeout_s": 5}}, t), t, env=env)
        q.order = []; q._take_gpu = lambda: None; q._unload_llm = lambda: q.order.append("unload"); q._stop_comfy = lambda: None
        if sess: q.session = {"state": "ready"}
        jid, _, _ = q.submit("t2v", {"prompt": "x"}); q.run(jid)
        assert env.slept == want, (sess, env.slept)
        assert q.order == ([] if sess else ["unload", "start"]), q.order      # a reused session neither unloads nor starts
    assert video.Cfg({}).comfy_settle_s == 3.0 and video.Cfg({}).comfy_stall_s == 45.0 and video.Cfg({"comfy_settle_s": "bad"}).comfy_settle_s == 3.0

if __name__ == "__main__":
    fails = 0
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            t0 = time.time()
            try: f(); print("ok   %-32s %.1fs" % (n, time.time() - t0))
            except Exception: fails += 1; print("FAIL %s" % n); traceback.print_exc()
    print("%d failed" % fails); sys.exit(1 if fails else 0)
