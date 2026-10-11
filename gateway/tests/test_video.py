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

class Rig:
    def __init__(self, mode="ok", loaded=True, busy=False, quiet_s=0, timeout=60, killfile=True):
        self.t = tempfile.mkdtemp(dir=TMP); self.swap = Swap(loaded, busy); self.port = free_port()
        os.makedirs(os.path.join(self.t, "wf")); json.dump(WF, open(os.path.join(self.t, "wf", "t2v.json"), "w"))
        self.mode_file = os.path.join(self.t, "mode.txt"); open(self.mode_file, "w").write("MAX\n")
        self.comfy_log = os.path.join(self.t, "comfy-requests.log"); self.img_root = os.path.join(self.t, "shared"); os.makedirs(self.img_root)
        cfg = {"comfy_dir": self.t, "comfy_cmd": [PY, os.path.join(HERE, "mock_comfy.py"), str(self.port), mode, self.comfy_log], "comfy_url": "http://127.0.0.1:%d" % self.port,
               "workflows_dir": os.path.join(self.t, "wf"), "input_dir": os.path.join(self.t, "input"), "allowed_roots": [self.img_root], "job_timeout_s": timeout,
               "start_timeout_s": 20, "poll_s": 0.1, "tick_s": 0.1, "llm": {"swap_url": "http://127.0.0.1:%d" % self.swap.port, "model_id": "m", "quiet_s": quiet_s,
               "governor_mode_file": self.mode_file, "unload_timeout_s": 10}}
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

if __name__ == "__main__":
    fails = 0
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            t0 = time.time()
            try: f(); print("ok   %-32s %.1fs" % (n, time.time() - t0))
            except Exception: fails += 1; print("FAIL %s" % n); traceback.print_exc()
    print("%d failed" % fails); sys.exit(1 if fails else 0)
