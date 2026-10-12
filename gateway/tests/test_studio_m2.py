"""Studio Phase 2 / M2 back end: GPU counters, stage-timing history, history ETAs, /api/history, /api/dev/info, live previews.
Real approvals server + the video Rig from test_video (mock ComfyUI). Run: python tests/test_studio_m2.py"""
import hashlib, http.client, io, json, os, socket, struct, sys, tempfile, threading, time, traceback, urllib.request, urllib.error, base64
for _m in ("gateway", "approvals", "skills", "outbox", "agent", "studio", "studio_metrics", "video", "tts_server", "cc_notify", "tools_video_mcp", "tools_local_llm",
           "build_workflow", "test_video"):
    sys.modules.pop(_m, None)     # other test files in the same process may have imported these with their own port/state
_s = socket.socket(); _s.bind(("127.0.0.1", 0)); os.environ["GW_APPROVAL_PORT"] = str(_s.getsockname()[1]); _s.close()
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, D); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import approvals, studio, studio_metrics as sm, video
import test_video as tv

GIB = float(2 ** 30)
approvals.PIN_FILE = os.path.join(tv.TMP, "pin-m2.json")
salt = b"saltsalt"
json.dump({"salt": salt.hex(), "iterations": 1000, "hash": hashlib.pbkdf2_hmac("sha256", b"4321", salt, 1000).hex()}, open(approvals.PIN_FILE, "w"))
PORT = approvals.PORT
T = "/approvals/studio"
rig = tv.Rig(quiet_s=0)
GOV, RUN = os.path.join(rig.t, "status.json"), os.path.join(rig.t, "running.json")
json.dump({"profile": "MAX", "mode": "AUTO", "phase": "ready"}, open(GOV, "w"))
json.dump({"id": "qwen-test-model", "port": 1}, open(RUN, "w"))
CFG = {"video": {}, "studio": {"metrics": {"governor_status": GOV, "governor_running": RUN}}}
SAMPLER = sm.Sampler(gov_status=GOV, gov_running=RUN, cpu=sm.CpuProbe(reader=None), gpu=lambda: (12.5, 3.25), tick_fast=0.05, tick_idle=0.2, park_after=5, park_poll=0.2, ping_s=0.4)
studio.register(approvals, rig.q, rig.q.cfg, D, cfg=CFG, sampler=SAMPLER)
approvals.start(); time.sleep(0.3)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def call(method, path, body=None, cookie=None, port=None, headers=None):
    h = dict(headers or {"X-Requested-With": "approvals"})
    if cookie: h["Cookie"] = cookie
    data = json.dumps(body).encode() if body is not None else None
    if data is not None: h["Content-Type"] = "application/json"
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port or PORT, path), data=data, headers=h, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=10); return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


r_ = call("POST", "/approvals/login", {"pin": "4321"})
assert r_[0] == 200, r_
cookie = r_[2].get("Set-Cookie").split(";")[0]
ALLOW, IDP = "elz@example.com", free_port()


def ident_on():
    if approvals._ident["srv"] is None:
        ok, err = approvals.identity_configure(enabled=True, allow_logins=[ALLOW], listen="127.0.0.1:%d" % IDP)
        assert ok and not err, err


def idcall(method, path, login=None, cookie=None):
    c = http.client.HTTPConnection("127.0.0.1", IDP, timeout=5)
    c.putrequest(method, path)
    if login is not None: c.putheader("Tailscale-User-Login", login)
    c.putheader("X-Requested-With", "approvals")
    if cookie: c.putheader("Cookie", cookie)
    c.endheaders()
    r = c.getresponse(); out = (r.status, r.read(), r.headers); c.close()
    return out


def gws():
    ident_on()
    h = idcall("GET", T, login=ALLOW)[2]
    return next(v for k, v in h.items() if k.lower() == "set-cookie" and v.startswith("gws=")).split(";")[0]


def wait_for(fn, secs=5.0):
    end = time.time() + secs
    while time.time() < end:
        if fn(): return True
        time.sleep(0.02)
    return False


def fake_job(i, wf="t2v", total=100.0, w=768, h=512, frames=97, state="done", t0=1_000_000.0, phases=None):
    return {"id": "%08x" % i, "workflow": wf, "params": {"width": w, "height": h, "frames": frames}, "state": state, "created": t0 + i, "started": t0 + i, "ended": t0 + i + total}


# ---------------- 1. GPU counters ----------------
class FakePdh:
    """The reader's backend: scripted PDH arrays, with a log of calls."""
    def __init__(self):
        self.log, self.nh, self.util, self.mem, self.fail = [], 0, [], [], None
    def open(self): self.log.append("open")
    def add(self, path):
        self.nh += 1; self.log.append(("add", path, self.nh)); return self.nh
    def remove(self, h): self.log.append(("remove", h))
    def collect(self):
        self.log.append("collect")
        if self.fail: raise OSError(self.fail)
    def array(self, h):
        path = next(l[1] for l in self.log if isinstance(l, tuple) and l[0] == "add" and l[2] == h)
        return self.util if "GPU Engine" in path else self.mem
    def close(self): self.log.append("close")


def test_gpu_aggregate_sums_per_engine_and_takes_the_busiest():
    util = [("pid_1_luid_0x00000000_0x0000AAAA_phys_0_eng_0_engtype_3D", 30.0), ("pid_2_luid_0x00000000_0x0000AAAA_phys_0_eng_0_engtype_3D", 25.04),
            ("pid_2_luid_0x00000000_0x0000AAAA_phys_0_eng_1_engtype_Compute", 40.0),          # a different engine of the same adapter: not added to 3D
            ("pid_3_luid_0x00000000_0x0000BBBB_phys_0_eng_0_engtype_Copy", 20.0),
            ("pid_3_luid_0x00000000_0x0000BBBB_phys_0_eng_0_engtype_VideoEncode", 99.0),     # not one of the four engine types
            ("garbage", 100.0)]
    mem = [("luid_0x00000000_0x0000AAAA_phys_0", 5.5 * GIB), ("luid_0x00000000_0x0000BBBB_phys_0", 1 * GIB)]
    assert sm.gpu_aggregate(util, mem) == (55.0, 5.5), sm.gpu_aggregate(util, mem)             # 3D on adapter A = 30 + 25.04, rounded to one decimal
    over = [("pid_1_luid_0x0_0x1_phys_0_eng_0_engtype_3D", 80.0), ("pid_2_luid_0x0_0x1_phys_0_eng_0_engtype_3D", 70.0)]
    assert sm.gpu_aggregate(over, None) == (100.0, None)                                       # summed instances clamp to 100
    assert sm.gpu_aggregate(None, []) == (None, None) and sm.gpu_aggregate([("x", 1.0)], [("y", -1)]) == (None, None)


def test_pdh_reader_needs_two_collections_then_reads_and_readds_without_a_gap():
    be, now = FakePdh(), [1000.0]
    rd = sm.PdhReader(backend=be, clock=lambda: now[0], readd_s=60.0)
    be.util = [("pid_1_luid_0x0_0x1_phys_0_eng_0_engtype_3D", 41.0)]
    be.mem = [("luid_0x0_0x1_phys_0", 2 * GIB)]
    assert rd.read() == (None, None)                                                           # first collection only primes the rate counters
    assert be.log[:3] == ["open", ("add", sm.PDH_UTIL, 1), ("add", sm.PDH_MEM, 2)] and be.log.count("collect") == 1
    assert rd.read() == (41.0, 2.0)
    assert rd.read() == (41.0, 2.0) and be.log.count("open") == 1                              # one query, reused
    adds = lambda: [l for l in be.log if isinstance(l, tuple) and l[0] == "add"]
    assert len(adds()) == 2
    now[0] += 61                                                                               # instances come and go: re-add the wildcards
    be.util = [("pid_1_luid_0x0_0x1_phys_0_eng_0_engtype_3D", 50.0), ("pid_9_luid_0x0_0x1_phys_0_eng_0_engtype_3D", 5.0)]
    assert rd.read() == (55.0, 2.0) and len(adds()) == 4                                       # new pair added and primed; the old pair still answers
    assert not any(isinstance(l, tuple) and l[0] == "remove" for l in be.log)
    assert rd.read() == (55.0, 2.0)                                                            # new pair swapped in, old removed, no null in between
    assert [l for l in be.log if isinstance(l, tuple) and l[0] == "remove"] == [("remove", 1), ("remove", 2)]
    assert rd.read() == (55.0, 2.0) and len(adds()) == 4                                       # and not again before another 60 s
    now[0] += 61; rd.read(); rd.read()
    assert len(adds()) == 6
    be.fail = "boom"                                                                           # any error: query closed, error raised
    try: rd.read(); raise AssertionError("should raise")
    except OSError: pass
    assert be.log[-1] == "close"
    be.fail = None
    assert rd.read() == (None, None) and be.log.count("open") == 2                             # reopened, warming up again


def test_gpu_probe_null_off_windows_and_after_errors_then_disabled_once():
    if os.name != "nt":
        p = sm.GpuProbe()
        assert p.disabled and p() == (None, None)                                              # no PDH, no error
        assert sm.Sampler(gov_status="/nope", gov_running="/nope", cpu=sm.CpuProbe(reader=None)).sample()["gpu_util"] is None
    calls = []
    class R:
        def __init__(self, script): self.script = list(script)
        def read(self):
            calls.append(1); v = self.script.pop(0)
            if isinstance(v, Exception): raise v
            return v
    old = sys.stderr; sys.stderr = io.StringIO()
    try:
        p = sm.GpuProbe(R([OSError("a"), OSError("b"), (10.04, 1.234), OSError("c"), OSError("d"), OSError("e"), (1, 1)]))
        assert p() == (None, None) and p() == (None, None)                                     # errors give nulls
        assert p() == (10.0, 1.23) and p.errs == 0                                             # success resets the streak: one decimal, two decimals
        assert p() == (None, None) and p() == (None, None) and not p.disabled
        assert p() == (None, None) and p.disabled                                              # the third in a row disables it
        n = len(calls)
        assert p() == (None, None) and len(calls) == n                                         # never read again
        log = sys.stderr.getvalue()
    finally: sys.stderr = old
    assert log.count("GPU counters disabled") == 1 and log.count("\n") == 1, log               # logged once


def test_gpu_fields_in_points_hello_stats_and_slow_ring_means():
    assert sm.FIELDS[-2:] == ("gpu_util", "gpu_mem_gb") and sm.FIELDS[:8] == ("t", "cpu", "ram_used_gb", "ram_total_gb", "vram_used_gb", "gpu_owner", "queue", "tps")
    pts = [dict(dict.fromkeys(sm.FIELDS), t=60.0 + i, gpu_util=u, gpu_mem_gb=m) for i, (u, m) in enumerate([(10.0, 1.0), (None, 2.0), (30.0, None), (None, None)])]
    a = sm.average(pts, 60)
    assert a["gpu_util"] == 20.0 and a["gpu_mem_gb"] == 1.5 and list(a) == list(sm.FIELDS), a    # nulls skipped
    assert sm.average([dict(dict.fromkeys(sm.FIELDS), t=1.0)], 0)["gpu_util"] is None
    p = SAMPLER.sample()
    assert p["gpu_util"] == 12.5 and p["gpu_mem_gb"] == 3.25 and list(p) == list(sm.FIELDS), p
    s, b, _ = call("GET", T + "/api/stats", cookie=cookie)
    d = json.loads(b)
    assert s == 200 and d["fields"][-2:] == ["gpu_util", "gpu_mem_gb"], d["fields"]
    assert wait_for(lambda: json.loads(call("GET", T + "/api/stats", cookie=cookie)[1])["fast"])
    assert json.loads(call("GET", T + "/api/stats", cookie=cookie)[1])["fast"][-1]["gpu_util"] == 12.5
    assert sm.Sampler(gov_status="/nope", gov_running="/nope", gpu=lambda: (1 / 0)).sample()["gpu_util"] is None     # a broken probe is a null, never a crash


# ---------------- 2. stage-timing history ----------------
def hist_file(): return rig.q.hist_path
def hist_lines(): return [json.loads(l) for l in open(hist_file(), encoding="utf-8").read().splitlines() if l.strip()]


def test_a_real_job_appends_one_history_line():
    before = len(hist_lines()) if os.path.exists(hist_file()) else 0
    jid, _, _ = rig.q.submit("t2v", {"prompt": "history fox", "seconds": 2, "width": 320, "height": 256}); j = rig.wait(jid, ("done",))
    assert wait_for(lambda: len(hist_lines()) == before + 1)
    r = hist_lines()[-1]
    assert r["id"] == jid and r["workflow"] == "t2v" and r["ok"] is True and (r["w"], r["h"]) == (320, 256) and isinstance(r["frames"], int), r
    assert abs(r["t"] - j["ended"]) < 0.2 and 0 <= r["total_s"] <= 30 and isinstance(r["phases"], dict), r
    assert set(r) == {"t", "id", "workflow", "w", "h", "frames", "ok", "total_s", "phases"}, r
    recs, sm_ = rig.q.history("t2v", 50)
    assert recs[0]["id"] == jid and sm_["t2v"]["n"] >= 1                                       # newest first


def test_phase_seconds_come_from_phase_changes_and_ok_is_false_for_error_and_cancel():
    q = rig.q
    for state, ok in (("failed", False), ("cancelled", False), ("done", True)):
        j = fake_job(500 + len(state), state="running", t0=100.0); j["started"], j["ended"] = 95.0, None
        with q.lock: q.jobs.append(j)
        with q.lock:
            q._phase_mark(j["id"], "encode", 100.0); q._phase_mark(j["id"], "stage1", 102.5); q._phase_mark(j["id"], "stage1", 105.0)    # same phase again: no new interval
        q._set(j["id"], state=state, ended=110.0)
        r = hist_lines()[-1]
        assert r["id"] == j["id"] and r["ok"] is ok and r["total_s"] == 15.0 and r["t"] == 110.0, r
        assert r["phases"] == {"encode": 2.5, "stage1": 7.5}, r["phases"]                      # the last phase runs to the end time
        q._set(j["id"], note="again")                                                          # a later _set of a finished job writes nothing
        assert hist_lines()[-1]["id"] == j["id"]
    n = len(hist_lines()); j = fake_job(77, state="queued"); j["ended"] = None
    with q.lock: q.jobs.append(j)
    q.cancel_job(j["id"])                                                                      # cancelled before it started
    r = hist_lines()[-1]
    assert len(hist_lines()) == n + 1 and r["id"] == j["id"] and r["ok"] is False and r["phases"] == {}, r
    # _set(phase=...) on a live job feeds the same stopwatch
    k = fake_job(78, state="running"); k["ended"] = None
    with q.lock: q.jobs.append(k)
    q._set(k["id"], phase="encode"); time.sleep(0.05); q._set(k["id"], phase="load"); time.sleep(0.05); q._set(k["id"], state="done", ended=time.time())
    r = hist_lines()[-1]
    assert list(r["phases"]) == ["encode", "load"] and all(v >= 0 for v in r["phases"].values()), r


def test_history_cap_rewrites_atomically_at_600_to_500_lines():
    q = rig.q
    open(hist_file(), "w").write("".join(json.dumps({"t": float(i), "id": "%08x" % (9000 + i), "workflow": "cap", "ok": True, "total_s": 1.0, "phases": {}}) + "\n" for i in range(600)))
    q._hist_n = None
    q._hist_add(fake_job(1234, wf="cap"))                                                      # the 601st line trips the cap
    ls = hist_lines()
    assert len(ls) == 500 and ls[-1]["id"] == "%08x" % 1234 and ls[0]["id"] == "%08x" % (9000 + 101), (len(ls), ls[0]["id"])
    assert not os.path.exists(hist_file() + ".tmp") and q._hist_n == 500
    q._hist_add(fake_job(1235, wf="cap"))
    assert len(hist_lines()) == 501                                                            # appends again until it passes 600
    open(hist_file(), "a").write("{not json\n")                                                # a bad line is skipped on read, never fatal
    q._hist_n = None
    assert len(q.history_records()) == 501
    open(hist_file(), "w").write("".join(l + "\n" for l in open(hist_file()).read().splitlines() if l.startswith("{\"")))    # leave a clean file for the other tests
    q._hist_n = None


def test_a_history_write_failure_never_breaks_the_job():
    q = rig.q
    good, q.hist_path = q.hist_path, os.path.join(rig.t, "a-dir"); os.makedirs(q.hist_path, exist_ok=True)
    old = sys.stderr; sys.stderr = io.StringIO()
    try:
        j = fake_job(600, state="running"); j["ended"] = None
        with q.lock: q.jobs.append(j)
        q._set(j["id"], state="done", ended=time.time())                                       # the write fails; _set carries on
        err = sys.stderr.getvalue()
    finally: sys.stderr = old; q.hist_path = good
    assert q.get(j["id"])["state"] == "done" and "stage history write failed" in err, err
    assert q.history_records() is not None


def test_summary_maths_ok_only_last_50_and_medians():
    recs = [{"workflow": "a", "ok": True, "total_s": float(t), "w": 100, "h": 10, "frames": f, "phases": {"x": float(t) / 10}} for t, f in ((10, 10), (20, 20), (30, 30), (1000, 40))]
    recs.append({"workflow": "a", "ok": False, "total_s": 5000.0, "w": 1, "h": 1, "frames": 1, "phases": {"x": 9999.0}})      # failed: never counted
    recs.append({"workflow": "b", "ok": True, "total_s": 7.0, "phases": {}})                    # no size: median_px_frames 0
    sm_ = video.hist_summary(recs)
    assert sm_["a"] == {"n": 4, "median_total_s": 25.0, "median_phase_s": {"x": 2.5}, "median_px_frames": 25000}, sm_["a"]       # even count: mean of the middle two
    assert sm_["b"] == {"n": 1, "median_total_s": 7.0, "median_phase_s": {}, "median_px_frames": 0}
    many = [{"workflow": "c", "ok": True, "total_s": 1000.0} for _ in range(30)] + [{"workflow": "c", "ok": True, "total_s": 10.0} for _ in range(50)]
    assert video.hist_summary(many)["c"]["n"] == 50 and video.hist_summary(many)["c"]["median_total_s"] == 10.0     # only the newest 50
    assert video.hist_summary([]) == {} and video.hist_summary([{"workflow": "z", "ok": False, "total_s": 1.0}]) == {}


# ---------------- 3. ETA from history ----------------
ST = {"n": 3, "median_total_s": 100.0, "median_phase_s": {}, "median_px_frames": 1000}


def test_hist_eta_scales_clamps_and_subtracts_elapsed():
    f = video.hist_eta
    assert f(ST, 10, 10, 10) == 100.0                                                          # px-frames 1000 = the median
    assert f(ST, 20, 10, 10) == 200.0 and f(ST, 10, 10, 5) == 50.0
    assert f(ST, 100, 100, 10) == 300.0                                                        # 100x the work: clamped to 3x
    assert f(ST, 1, 1, 1) == 50.0                                                              # tiny: clamped to 0.5x
    assert f(ST, 10, 10, 10, elapsed=30.0) == 70.0 and f(ST, 10, 10, 10, elapsed=500.0) == 0.0
    assert f(ST, None, 10, 10) == 100.0 and f(dict(ST, median_px_frames=0), 20, 10, 10) == 100.0   # unknown size: the median itself
    assert f(dict(ST, n=1), 10, 10, 10) is None and f(None, 10, 10, 10) is None and f({}, 1, 1, 1) is None    # needs 2 ok records


def test_public_job_eta_source_live_history_or_null():
    H = {"t2v": ST}
    now = 5000.0
    base = {"id": "aaaaaaaa", "workflow": "t2v", "state": "queued", "created": 1.0, "params": {"width": 10, "height": 10, "frames": 20}}
    d = studio._public_job(base, H, now)
    assert d["eta_s"] == 200.0 and d["eta_source"] == "history", d                             # queued: the full scaled estimate
    d = studio._public_job(dict(base, state="running", started=now - 50.0), H, now)
    assert d["eta_s"] == 150.0 and d["eta_source"] == "history", d                             # running, no live ETA yet: minus elapsed
    d = studio._public_job(dict(base, state="running", started=now - 50.0, eta_s=12.34), H, now)
    assert d["eta_s"] == 12.3 and d["eta_source"] == "live", d                                 # the progress parser wins
    d = studio._public_job(dict(base, state="running", started=now - 50.0, eta_s=None), H, now)
    assert d["eta_source"] == "history"                                                        # parser has none between bars
    d = studio._public_job(base, {}, now)
    assert "eta_s" not in d and d["eta_source"] is None, d                                     # no history: existing behaviour (the page estimates itself)
    d = studio._public_job(base, {"t2v": dict(ST, n=1)}, now)
    assert "eta_s" not in d and d["eta_source"] is None
    d = studio._public_job(base)
    assert "eta_s" not in d and d["eta_source"] is None
    d = studio._public_job(dict(base, state="done"), H, now)
    assert "eta_s" not in d and d["eta_source"] is None, d                                     # finished jobs get no estimate
    d = studio._public_job(dict(base, state="waiting"), H, now)
    assert d["eta_source"] == "history" and d["eta_s"] == 200.0
    d = studio._public_job(dict(base, workflow="other"), H, now)
    assert d["eta_source"] is None


def test_jobs_route_and_stream_carry_eta_source():
    for i in range(3):
        rig.q._hist_add(fake_job(300 + i, wf="eta_wf", total=60.0, w=32, h=32, frames=9))
    wfs = [{"id": "bbbbbbbb", "workflow": "eta_wf", "state": "queued", "created": time.time(), "params": {"width": 32, "height": 32, "frames": 9}}]
    assert studio._public_job(wfs[0], rig.q.hist_stats())["eta_s"] == 60.0
    s, b, _ = call("GET", T + "/api/jobs", cookie=cookie)
    assert s == 200 and all("eta_source" in j and "preview_t" in j for j in json.loads(b))


# ---------------- 4. /api/history ----------------
def test_history_route_tiers_shape_filter_and_limit():
    ident_on()
    for i in range(4): rig.q._hist_add(fake_job(700 + i, wf="route_wf", total=10.0 * (i + 1)))
    rig.q._hist_add(dict(fake_job(704, wf="route_wf", total=999.0), state="failed"))
    rig.q._hist_add(fake_job(705, wf="other_wf", total=5.0))
    assert call("GET", T + "/api/history")[0] == 401 and idcall("GET", T + "/api/history")[0] == 401           # no tier
    s, b, h = call("GET", T + "/api/history?workflow=route_wf", cookie=cookie)
    d = json.loads(b)
    assert s == 200 and d["v"] == 1 and list(d) == ["v", "records", "summary"], d
    ids = [r["id"] for r in d["records"]]
    assert ids == ["%08x" % x for x in (704, 703, 702, 701, 700)], ids                         # newest first, only this workflow (the failed one included)
    assert d["records"][0]["ok"] is False
    assert list(d["summary"]) == ["route_wf"] and d["summary"]["route_wf"]["n"] == 4 and d["summary"]["route_wf"]["median_total_s"] == 25.0, d["summary"]   # ok records only
    assert d["summary"]["route_wf"]["median_px_frames"] == 768 * 512 * 97
    both = json.loads(call("GET", T + "/api/history?limit=200", cookie=cookie)[1])
    assert {"route_wf", "other_wf"} <= set(both["summary"]) and len(both["records"]) >= 6
    for q_, n in (("limit=2", 2), ("limit=0", 1), ("limit=-5", 1), ("limit=9999", None), ("limit=abc", None), ("", None)):
        got = json.loads(call("GET", T + "/api/history" + ("?workflow=route_wf&" + q_ if q_ else "?workflow=route_wf"), cookie=cookie)[1])["records"]
        assert (len(got) == n) if n else (len(got) == 5), (q_, len(got))
    cap = json.loads(call("GET", T + "/api/history?limit=9999", cookie=cookie)[1])["records"]
    assert len(cap) <= 200 and json.loads(call("GET", T + "/api/history?workflow=nope", cookie=cookie)[1]) == {"v": 1, "records": [], "summary": {}}
    s, b, _ = idcall("GET", T + "/api/history?workflow=route_wf", cookie=gws(), login=ALLOW)      # the Tailscale tier may read it
    assert s == 200 and len(json.loads(b)["records"]) == 5
    assert "GET " + T + "/api/history" in studio.ts_ok_keys(studio.routes(rig.q, rig.q.cfg, D, cfg=CFG)[0])


# ---------------- 5. /api/dev/info ----------------
SECRETS = ("hf_supersecretvalue1", "S3CR3T-ARG", "ghp_abcdefghijkl", "sk-abcdef123456", "tok-12345678901234567890123456789012345", "cookievalue99", "pw-in-query")


def test_dev_info_is_pin_only_and_redacts_everything_secret():
    ident_on()
    assert studio.PIN_ONLY.match("GET " + T + "/api/dev/info") and "GET " + T + "/api/dev/info" not in studio.ts_ok_keys(studio.routes(rig.q, rig.q.cfg, D, cfg=CFG)[0])
    cfg, old_cmd, old_env = rig.q.cfg, list(rig.q.cfg.comfy_cmd), dict(rig.q.cfg.comfy_env)
    cfg.comfy_cmd = old_cmd + ["--api-key", SECRETS[1], "--listen", "--auth-token=" + SECRETS[2]]
    cfg.comfy_env = {"HF_TOKEN": SECRETS[0], "COMFY_COOKIE": SECRETS[5], "MY_PIN": "1234", "CUDA_VISIBLE_DEVICES": "0", "NOTE": "Authorization: Bearer " + SECRETS[3]}
    lines = ["line %d" % i for i in range(300)] + ["GET /x?api_key=%s&ok=1" % SECRETS[6], "Bearer " + SECRETS[3], "ghp_" + "abcdefghijkl", SECRETS[4], "\x1b[31mred\x1b[0m done",
                                                    "12%|#| 3/8 [00:01<00:05,  1.00s/it]\r13%|#| 4/8 [00:02<00:04,  1.00s/it]\r"]
    open(rig.q.log_path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    try:
        assert call("GET", T + "/api/dev/info")[0] == 401                                      # nothing
        assert idcall("GET", T + "/api/dev/info", cookie=gws(), login=ALLOW)[0] == 401         # ts tier: refused
        s, b, _ = call("GET", T + "/api/dev/info", cookie=cookie)
        assert s == 200, (s, b)
        d = json.loads(b)
    finally:
        cfg.comfy_cmd, cfg.comfy_env = old_cmd, old_env
    assert list(d) == ["v", "comfy", "gateway", "governor", "llm"] and d["v"] == 1 and list(d["comfy"]) == ["cmd", "env", "log_tail"] and list(d["gateway"]) == ["version", "log_tail"], list(d)
    assert d["comfy"]["cmd"] == old_cmd + ["--api-key", "***", "--listen", "--auth-token=***"], d["comfy"]["cmd"]
    assert d["comfy"]["env"]["HF_TOKEN"] == "***" and d["comfy"]["env"]["COMFY_COOKIE"] == "***" and d["comfy"]["env"]["MY_PIN"] == "***" and d["comfy"]["env"]["CUDA_VISIBLE_DEVICES"] == "0"
    assert d["comfy"]["env"]["NOTE"] == "Authorization: ***"
    tail = d["comfy"]["log_tail"]
    assert isinstance(tail, list) and len(tail) == 200 and tail[-1].startswith("13%"), (len(tail), tail[-3:])      # the last 200 lines, tqdm updates split on \r
    assert "red done" in " ".join(tail) and "\x1b" not in " ".join(tail)
    blob = json.dumps(d)
    for sec in SECRETS: assert sec not in blob, sec
    assert "api_key=***" in blob and "ok=1" in blob
    assert d["governor"] == {"profile": "MAX", "mode": "AUTO"} and d["llm"] == {"model": "qwen-test-model"}
    assert d["gateway"]["version"] is None and d["gateway"]["log_tail"] is None                # no VERSION file and no gateway.log next to the code or the state dir
    before = json.dumps(rig.q.jobs, sort_keys=True)
    call("GET", T + "/api/dev/info", cookie=cookie)
    assert json.dumps(rig.q.jobs, sort_keys=True) == before                                    # read-only


def test_dev_info_version_and_gateway_log_and_missing_files():
    here = tempfile.mkdtemp(dir=tv.TMP); os.makedirs(os.path.join(here, "studio"))
    open(os.path.join(here, "VERSION"), "w").write("c296814\n")
    open(os.path.join(here, "gateway.log"), "w").write("started\nBearer abcdefghijklmnop\n")
    table = studio.routes(rig.q, rig.q.cfg, here, cfg={"video": {}, "studio": {"metrics": {"governor_status": os.path.join(here, "none.json"), "governor_running": os.path.join(here, "none2.json")}}})[0]
    h = table["GET " + T + "/api/dev/info"]
    code, body, _ = h({"tier": "pin", "authed": True, "query": {}, "path": T + "/api/dev/info"})
    d = json.loads(body)
    assert code == 200 and d["gateway"]["version"] == "c296814" and d["gateway"]["log_tail"] == ["started", "***"], d["gateway"]
    assert d["governor"] == {"profile": None, "mode": None} and d["llm"] == {"model": None}
    assert h({"tier": "ts", "authed": False, "query": {}, "path": T + "/api/dev/info"})[0] == 401
    assert h({"tier": None, "authed": False, "query": {}, "path": T + "/api/dev/info"})[0] == 401


def test_redaction_helpers():
    r = studio.redact_line
    assert r("password=hunter2 user=elz") == "password=*** user=elz" and r("Authorization: Bearer abc.def") == "Authorization: ***"
    assert r("a" * 31) == "a" * 31 and r("a" * 32) == "***" and r("x sk-12345678 y") == "x *** y" and r("ghp_1234567 ok") == "ghp_1234567 ok" and r("ghp_12345678") == "***"
    assert r("GET /v?token=abc&x=2") == "GET /v?token=***&x=2" and r("plain text") == "plain text"
    assert studio.redact_cmd(["py", "--secret", "x", "--port", "1", "--pin=9"]) == ["py", "--secret", "***", "--port", "1", "--pin=***"]
    assert studio.redact_env({"A": "1", "PASSWORD": "x", "my_auth": "y"}) == {"A": "1", "PASSWORD": "***", "my_auth": "***"}
    assert studio.log_tail(os.path.join(rig.t, "does-not-exist")) is None


# ---------------- 6. live previews ----------------
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(100))
JPG = b"\xff\xd8\xff\xe0" + bytes(range(100))


def wsframe(op, payload, fin=True, mask=False):
    n, b0 = len(payload), (0x80 if fin else 0) | op
    h = bytes([b0, n]) if n < 126 else bytes([b0, 126]) + struct.pack(">H", n) if n < 65536 else bytes([b0, 127]) + struct.pack(">Q", n)
    return h + payload


class FakeWS:
    """A ComfyUI /ws stand-in: handshake, then script(self, conn) sends frames. Records the request line and any pong the client sends."""
    def __init__(self, script, reply_ok=True):
        self.srv = socket.socket(); self.srv.bind(("127.0.0.1", 0)); self.srv.listen(2); self.port = self.srv.getsockname()[1]
        self.script, self.req, self.pong, self.conns, self.ok = script, None, None, 0, reply_ok
        threading.Thread(target=self.run, daemon=True).start()
    def run(self):
        while True:
            try: c, _ = self.srv.accept()
            except OSError: return
            self.conns += 1
            try:
                buf = b""
                while b"\r\n\r\n" not in buf: buf += c.recv(4096)
                self.req = buf.decode("latin-1")
                key = next(l.split(":", 1)[1].strip() for l in self.req.split("\r\n") if l.lower().startswith("sec-websocket-key"))
                acc = base64.b64encode(hashlib.sha1(key.encode() + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest()).decode()
                c.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n" % acc).encode() if self.ok
                          else b"HTTP/1.1 400 Bad Request\r\n\r\n")
                if self.ok: self.script(self, c)
                c.settimeout(3)
                while c.recv(1024): pass
            except (OSError, StopIteration): pass
            finally:
                try: c.close()
                except OSError: pass
    def close(self): self.srv.close()


def script_basic(ws, c):
    c.sendall(wsframe(1, b'{"type":"status"}'))
    c.sendall(wsframe(9, b"hi"))
    c.settimeout(2); got = c.recv(8)
    m = got[2:6]; ws.pong = (got[0], got[1] & 0x7F, bytes(x ^ m[i % 4] for i, x in enumerate(got[6:8])), bool(got[1] & 0x80))
    c.sendall(wsframe(2, struct.pack(">II", 1, 2) + PNG))                                      # event 1 (preview image), image type 2 (PNG)
    c.sendall(wsframe(2, b"\x00\x00\x00\x01" + JPG[:50], fin=False) + wsframe(9, b"x") + wsframe(0, JPG[50:]))     # fragmented, with a ping in between
    c.sendall(wsframe(2, struct.pack(">II", 1, 2) + PNG + bytes(70000)))                       # needs the 64-bit length form


def test_websocket_client_handshake_frames_ping_and_fragments():
    ws = FakeWS(script_basic)
    try:
        sock, rest = video.ws_connect("http://127.0.0.1:%d" % ws.port, "gw-abcd1234")
        assert ws.req.startswith("GET /ws?clientId=gw-abcd1234 HTTP/1.1\r\n") and "Upgrade: websocket" in ws.req and "Sec-WebSocket-Version: 13" in ws.req
        stop, out = threading.Event(), []
        for op, data in video.ws_messages(sock, rest, stop):
            out.append((op, data))
            if len(out) == 4: break
        sock.close()
    finally: ws.close()
    assert out[0] == (1, b'{"type":"status"}')
    assert out[1][0] == 2 and out[1][1].endswith(PNG)
    assert out[2][0] == 2 and out[2][1] == b"\x00\x00\x00\x01" + JPG                           # fragments joined
    assert out[3][0] == 2 and len(out[3][1]) == 8 + len(PNG) + 70000
    assert ws.pong == (0x8A, 2, b"hi", True), ws.pong                                          # a masked pong with the same payload
    bad = FakeWS(lambda *a: None, reply_ok=False)
    try:
        video.ws_connect("http://127.0.0.1:%d" % bad.port, "gw-x"); raise AssertionError("should refuse")
    except video.VideoError: pass
    finally: bad.close()


def test_preview_image_finds_jpeg_or_png_in_comfy_frames():
    assert video.preview_image(struct.pack(">II", 1, 2) + PNG) == (PNG, "image/png")
    assert video.preview_image(struct.pack(">II", 1, 1) + JPG) == (JPG, "image/jpeg")
    meta = json.dumps({"node_id": "5", "prompt_id": "x"}).encode()
    assert video.preview_image(struct.pack(">I", 4) + struct.pack(">I", len(meta)) + meta + struct.pack(">I", 1) + JPG) == (JPG, "image/jpeg")   # event 4: metadata first
    assert video.preview_image(b"\x00" * 200) is None and video.preview_image(struct.pack(">II", 1, 1) + b"\xff\xd8\xff") is None


def test_cfg_adds_the_latent2rgb_flag_only_when_asked():
    mk = lambda **k: video.Cfg(dict({"comfy_dir": "x", "comfy_cmd": ["python", "main.py", "--listen"]}, **k), ".")
    assert mk().comfy_cmd == ["python", "main.py", "--listen"] and mk(comfy_preview=False).comfy_preview is False
    assert mk(comfy_preview=True).comfy_cmd[-2:] == ["--preview-method", "latent2rgb"]
    c = video.Cfg({"comfy_dir": "x", "comfy_cmd": ["python", "main.py", "--preview-method", "auto"], "comfy_preview": True}, ".")
    assert c.comfy_cmd == ["python", "main.py", "--preview-method", "auto"]                    # an explicit choice is kept
    assert video.Cfg({"comfy_preview": True}, ".").comfy_cmd == [] and not video.Cfg({"comfy_preview": True}, ".").enabled


def test_previews_are_kept_per_active_job_and_served():
    q = rig.q
    j = fake_job(900, state="running"); j["ended"] = None
    idle = fake_job(901, state="running"); idle["ended"] = None
    with q.lock: q.jobs.extend([j, idle])
    done = threading.Event()
    def script(ws, c):
        c.sendall(wsframe(2, struct.pack(">II", 1, 2) + PNG)); done.set()
    ws = FakeWS(script)
    old = (q.cfg.comfy_url, q.cfg.comfy_preview)
    q.cfg.comfy_url, q.cfg.comfy_preview = "http://127.0.0.1:%d" % ws.port, True
    stop = q._preview_start(j["id"])
    try:
        assert stop is not None and wait_for(lambda: j["id"] in q.previews and q.get(j["id"]).get("preview_t"))
        img, ct, t = q.previews[j["id"]]
        assert img == PNG and ct == "image/png" and abs(time.time() - t) < 5 and q.get(j["id"])["preview_t"] == round(t, 1)
        assert studio._public_job(q.get(j["id"]))["preview_t"] == q.get(j["id"])["preview_t"]
        assert studio._public_job(q.get(idle["id"]))["preview_t"] is None
        s, b, h = call("GET", T + "/api/jobs/%s/preview" % j["id"], cookie=cookie)
        assert s == 200 and b == PNG and h["Content-Type"] == "image/png", (s, h["Content-Type"])
        s, b, _ = call("GET", T + "/api/jobs/%s/preview" % idle["id"], cookie=cookie)
        assert s == 204 and b == b""                                                           # no preview yet
        assert call("GET", T + "/api/jobs/%s/preview" % "ffffffff", cookie=cookie)[0] == 204    # unknown job
        assert call("GET", T + "/api/jobs/%s/preview" % j["id"])[0] == 401
        assert call("GET", T + "/api/jobs/nothex/preview", cookie=cookie)[0] in (404, 204)
        s, b, _ = idcall("GET", T + "/api/jobs/%s/preview" % j["id"], cookie=gws(), login=ALLOW)
        assert s == 200 and b == PNG                                                           # the Tailscale tier may watch
        assert "GET " + T + "/api/jobs/*" in studio.ts_ok_keys(studio.routes(q, q.cfg, D, cfg=CFG)[0])
        q._set(j["id"], state="done", ended=time.time())                                        # finished: preview dropped, field null
        assert j["id"] not in q.previews and q.get(j["id"])["preview_t"] is None and call("GET", T + "/api/jobs/%s/preview" % j["id"], cookie=cookie)[0] == 204
    finally:
        stop.set(); q.cfg.comfy_url, q.cfg.comfy_preview = old; ws.close(); q._set(idle["id"], state="done", ended=time.time())
    assert q._preview_start("deadbeef") is None                                                # comfy_preview off: nothing starts


if __name__ == "__main__":
    fails = 0
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            try: f(); print("ok   ", n)
            except Exception: fails += 1; print("FAIL ", n); traceback.print_exc()
    approvals.identity_stop(); SAMPLER.stop(); rig.close()
    print("%d failed" % fails); sys.exit(1 if fails else 0)
