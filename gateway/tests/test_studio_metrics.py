"""studio_metrics unit tests: probes degrade to null, rings and averaging, change events, cadence, budget. No server. Run: python tests/test_studio_metrics.py"""
import json, os, sys, tempfile, threading, time, traceback, tracemalloc
sys.modules.pop("studio_metrics", None)
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, D)
import studio_metrics as sm

TMP = tempfile.mkdtemp(prefix="smtest-")
MISSING = os.path.join(TMP, "nope", "status.json")


def mk(**kw):
    """A sampler wired to nothing real: no governor files, no CPU reader, no llama-server."""
    base = dict(gov_status=MISSING, gov_running=MISSING, cpu=sm.CpuProbe(reader=None), tick_fast=0.02, tick_idle=0.05, park_after=0.3, park_poll=0.05, ping_s=0.2)
    base.update(kw)
    return sm.Sampler(**base)


def test_sampler_degrades_without_windows_apis_or_files():
    s = sm.Sampler(gov_status=MISSING, gov_running=MISSING)          # all defaults: on Linux there is no GetSystemTimes and no C:\AI\...
    p = s.sample()
    assert list(p) == list(sm.FIELDS) and isinstance(p["t"], float), p
    assert all(p[k] is None for k in sm.FIELDS if k != "t"), p
    if os.name != "nt": assert s.cpu.reader is None and s.cpu() is None
    def boom(): raise RuntimeError("probe broke")
    s2 = mk(host_ram=boom, owner_fn=boom, queue_fn=boom, jobs_fn=boom, sys_fn=boom, tps=lambda owner: 1 / 0)
    p2 = s2.tick()                                                   # nothing raises; every broken source is a null
    assert all(p2[k] is None for k in sm.FIELDS if k != "t"), p2
    assert s2._sys_now["error"] == "RuntimeError" and s2._sys_now["governor"] is None
    s3 = mk(host_ram=lambda: (32 * 2 ** 30, 8 * 2 ** 30), owner_fn=lambda: "gpu?", queue_fn=lambda: 2)
    p3 = s3.sample()
    assert p3["ram_total_gb"] == 32.0 and p3["ram_used_gb"] == 24.0 and p3["gpu_owner"] is None and p3["queue"] == 2, p3


def test_cpu_probe_deltas():
    seq = iter([(100, 300, 100), (150, 400, 200), (150, 400, 200), (0, 0, 0)])
    c = sm.CpuProbe(reader=lambda: next(seq))
    assert c() is None                                               # priming
    assert c() == 75.0                                               # idle +50 of (kernel +100 + user +100) = 25 % idle
    assert c() is None                                               # no time passed
    assert c() is None                                               # counters went backwards: dropped
    assert sm.CpuProbe(reader=lambda: 1 / 0)() is None


def test_governor_status_read_only_when_mtime_changes_and_stale_is_null():
    p = os.path.join(TMP, "status.json")
    with open(p, "w", encoding="utf-8-sig") as f: json.dump({"vram_used_gib": 18.42, "vram_llama_gib": 15.1, "phase": "ready", "phase_since": 1760000000, "mode": "AUTO",
                                                            "profile": "MAX", "loaded": True, "n_ctx": 65536, "processing": False}, f)       # PowerShell may add a BOM
    s = mk(gov_status=p)
    for _ in range(5): pt = s.sample()
    assert pt["vram_used_gb"] == 18.42 and s.gov.reads == 1, (pt, s.gov.reads)
    g = s._gov_sys(time.time()); assert g == {"phase": "ready", "phase_since": 1760000000, "mode": "AUTO", "profile": "MAX", "loaded": True, "stale": False}, g
    with open(p, "w") as f: f.write('{"vram_used_gib": 3.5, "phase": "loading"}')
    os.utime(p, (time.time() + 1, time.time() + 1))
    assert s.sample()["vram_used_gb"] == 3.5 and s.gov.reads == 2 and s._gov_sys(time.time())["phase"] == "loading"
    with open(p, "w") as f: f.write('{"vram_used_gib": 9')                                       # caught mid-write: the last good value stays
    os.utime(p, (time.time() + 2, time.time() + 2))
    assert s.sample()["vram_used_gb"] == 3.5
    old = time.time() - 600
    with open(p, "w") as f: f.write('{"vram_used_gib": 7.0, "phase": "ready"}')
    os.utime(p, (old, old))
    assert s.sample()["vram_used_gb"] is None and s._gov_sys(time.time())["stale"] is True        # a dead governor's numbers are not shown as live
    os.remove(p); assert s.sample()["vram_used_gb"] is None and s._gov_sys(time.time()) is None


def test_tps_from_metrics_deltas():
    texts = []
    def get(url, timeout):
        assert url == "http://127.0.0.1:10001/metrics" and timeout <= 1
        return texts.pop(0)
    m = lambda n, s: "# HELP x\nllamacpp:tokens_predicted_total %s\nllamacpp:tokens_predicted_seconds_total %s\nllamacpp:prompt_tokens_total 9\n" % (n, s)
    t = sm.TpsProbe(lambda: 10001, get=get)
    texts += [m(1000, 50.0), m(1000, 50.0), m(1400, 60.0), m(10, 0.5)]
    assert t() is None                       # first read primes
    assert t() is None                       # nothing finished
    assert t() == 40.0                       # 400 tokens in 10 s of generation
    assert t() is None                       # llama-server restarted: counters reset
    assert t("video") is None and t.prev is None and not texts       # video mode: /metrics is not touched
    calls = []
    t2 = sm.TpsProbe(lambda: None, get=lambda u, to: calls.append(u))
    assert t2() is None and calls == []      # no running.json: never fetched
    t3 = sm.TpsProbe(lambda: 10001, get=lambda u, to: (_ for _ in ()).throw(OSError("refused")), backoff_s=60)
    assert t3() is None and t3() is None and t3.calls == 1           # a refused fetch backs off
    rp = os.path.join(TMP, "running.json"); json.dump({"profile": "MAX", "port": 10003, "id": "qwen3.8-27b-turbo"}, open(rp, "w"))
    assert sm.running_port(sm.JsonFile(rp)) == 10003
    json.dump({"port": "10003"}, open(rp, "w")); os.utime(rp, (time.time() + 5, time.time() + 5))
    assert sm.running_port(sm.JsonFile(rp)) is None and sm.running_port(sm.JsonFile(MISSING)) is None
    assert sm.parse_metric('llamacpp:tokens_predicted_total{slot="0"} 12\n', "llamacpp:tokens_predicted_total") == 12.0


def test_ring_sizes_and_minute_averages():
    r = sm.Rings()
    base = 1_760_000_000 - (1_760_000_000 % 60)
    for i in range(3000):
        r.add({"t": base + i, "cpu": float(i % 60), "ram_used_gb": 10.0, "ram_total_gb": 64.0, "vram_used_gb": None if i < 60 else 20.0,
               "gpu_owner": "llm" if i % 60 < 59 else "video", "queue": i % 60 // 30, "tps": None})
    assert len(r.fast) == sm.FAST_N == 900 and r.fast[-1]["t"] == base + 2999
    assert len(r.slow) == 49 and r.slow[0]["t"] == base and r.slow[1]["t"] == base + 60       # 50 minutes started, 49 complete
    a = r.slow[0]
    assert a["cpu"] == 29.5 and a["ram_used_gb"] == 10.0 and a["ram_total_gb"] == 64.0 and a["vram_used_gb"] is None and a["tps"] is None, a
    assert a["gpu_owner"] == "video" and a["queue"] == 1 and list(a) == list(sm.FIELDS)
    assert r.slow[1]["vram_used_gb"] == 20.0
    r2 = sm.Rings(fast_n=900, slow_n=1440)
    for i in range(1500): r2.slow.append({"t": i})
    assert len(r2.slow) == 1440


def test_events_m_job_sys_and_gone():
    jobs = [{"id": "aaaaaaaa", "state": "queued"}, {"id": "bbbbbbbb", "state": "done"}]
    sysd = {"mode": "llm", "linger_until": None}
    s = mk(jobs_fn=lambda: [dict(j) for j in jobs], sys_fn=lambda: dict(sysd))
    s.tick()
    assert [n for _, n, _ in s.events] == ["m"]                                 # the first tick is the baseline: no job/sys flood
    s.tick(); assert [n for _, n, _ in s.events] == ["m", "m"]
    jobs[0]["state"] = "running"; jobs[0]["progress"] = 12.5
    sysd["mode"] = "busy"
    s.tick()
    ev = [(n, d) for _, n, d in s.events][2:]
    assert [n for n, _ in ev] == ["m", "job", "sys"], ev
    assert ev[1][1] == {"id": "aaaaaaaa", "state": "running", "progress": 12.5} and ev[2][1]["mode"] == "busy" and "governor" in ev[2][1]
    del jobs[1]; s.tick()
    assert [(n, d) for _, n, d in s.events][-1] == ("job", {"id": "bbbbbbbb", "gone": True})
    seq = s.seq
    s.jobs_fn = lambda: 1 / 0; s.tick()                                         # a failed read does not mark every job gone
    assert [n for q, n, _ in s.events if q > seq] == ["m"]


def test_wait_events_and_resync():
    s = mk(events_max=4)
    s.tick(); s.tick()
    evs, seq, rs = s.wait_events(0, 0.01)
    assert [n for n, _ in evs] == ["m", "m"] and seq == 2 and not rs
    t0 = time.monotonic(); evs, seq2, rs = s.wait_events(seq, 0.1)
    assert evs == [] and seq2 == seq and time.monotonic() - t0 >= 0.09         # times out quietly
    for _ in range(6): s.tick()
    evs, seq3, rs = s.wait_events(seq, 0.01)
    assert rs and evs == [] and seq3 == s.seq                                   # the log no longer reaches back: the stream sends a new hello
    threading.Timer(0.05, s.tick).start()
    evs, _, _ = s.wait_events(seq3, 2.0); assert [n for n, _ in evs] == ["m"]   # woken by the next tick
    s.stop(); assert s.wait_events(s.seq, 1.0)[0] is None


def test_hello_snapshot_and_backfill():
    s = mk(jobs_fn=lambda: [{"id": "cccccccc", "state": "done"}], sys_fn=lambda: {"mode": "llm"})
    h, seq = s.hello()
    assert h["points"] == [] and h["jobs"] == [{"id": "cccccccc", "state": "done"}] and h["sys"]["mode"] == "llm" and seq == 0
    for _ in range(5): s.tick()
    h, seq = s.hello(3)
    assert len(h["points"]) == 3 and seq == 5 and h["fields"] == list(sm.FIELDS) and h["v"] == 1 and h["ping_s"] == 0.2
    assert s.hello(0)[0]["points"] == []
    snap = s.snapshot(); assert len(snap["fast"]) == 5 and snap["slow"] == [] and snap["fields"] == list(sm.FIELDS) and snap["running"] is False


def test_cadence_fast_idle_park_and_thread_lifecycle():
    busy = {"n": 0}
    s = mk(queue_fn=lambda: busy["n"])
    assert s.cadence() == "idle"
    s.client_enter(); assert s.cadence() == "fast"; s.client_exit()
    busy["n"] = 1; assert s.cadence() == "fast"; busy["n"] = 0
    s.last_use = time.monotonic() - 1; assert s.cadence() == "park"
    s.start(); s.start()                                                        # idempotent
    end = time.time() + 3
    while not s.parked and time.time() < end: time.sleep(0.02)
    assert s.parked, "sampler should park after park_after with nobody watching"
    n = s.ticks; time.sleep(0.2); assert s.ticks == n                           # parked: no probes run
    busy["n"] = 1                                                               # a job starts with nobody watching: the cheap check unparks it
    end = time.time() + 3
    while s.ticks == n and time.time() < end: time.sleep(0.02)
    assert s.ticks > n and not s.parked
    busy["n"] = 0
    end = time.time() + 3
    while not s.parked and time.time() < end: time.sleep(0.02)
    n = s.ticks; s.touch()
    end = time.time() + 2
    while s.ticks == n and time.time() < end: time.sleep(0.01)
    assert s.ticks > n                                                          # touch() wakes a parked sampler
    s.stop(); assert not s.running()


def test_sse_generator_framing_and_client_count():
    s = mk(ping_s=0.1, jobs_fn=lambda: [], sys_fn=lambda: {})
    g = sm.sse(s, backfill=10, max_s=0.6)
    first = next(g)
    assert first.startswith(b"retry: 3000\n\nevent: hello\ndata: {") and first.endswith(b"\n\n") and s.clients == 1
    rest = b"".join(g)                                                          # ends by itself after max_s
    assert b"event: m\ndata: {" in rest and b": ping\n\n" in rest and s.clients == 0
    for chunk in rest.split(b"\n\n"):
        if chunk.startswith(b"event: m"): json.loads(chunk.split(b"data: ", 1)[1])
    g2 = sm.sse(s, max_s=5); next(g2); assert s.clients == 1
    g2.close(); assert s.clients == 0                                           # closing the generator (client gone) unregisters it
    s.stop()


def test_budget_memory_of_full_rings():
    tracemalloc.start()
    a = tracemalloc.take_snapshot()
    s = mk()
    for i in range(sm.FAST_N + sm.SLOW_N * 60 // 20):                          # fill the fast ring; push enough minutes through the slow one
        s.rings.add({"t": i * 20.0, "cpu": 12.3, "ram_used_gb": 40.12, "ram_total_gb": 63.6, "vram_used_gb": 21.5, "gpu_owner": "llm", "queue": 0, "tps": 18.4})
    with s.cv:
        for i in range(300): s._push("m", s.rings.fast[-1])
    assert len(s.rings.fast) == 900 and len(s.rings.slow) == 1440
    b = tracemalloc.take_snapshot(); tracemalloc.stop()
    used = sum(x.size_diff for x in b.compare_to(a, "filename"))
    assert used < 5 * 2 ** 20, used


def test_tick_cost_is_small():
    s = mk(host_ram=lambda: (2 ** 36, 2 ** 35), owner_fn=lambda: "llm", queue_fn=lambda: 0, jobs_fn=lambda: [{"id": "%08x" % i, "state": "done", "params": {"prompt": "x" * 200}} for i in range(41)],
           sys_fn=lambda: {"mode": "llm"})
    t0 = time.process_time()
    for _ in range(200): s.tick()
    per = (time.process_time() - t0) / 200
    assert per < 0.005, per                                                     # < 5 ms CPU per 1 s tick = < 0.5 %


if __name__ == "__main__":
    fails = 0
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            try: f(); print("ok   ", n)
            except Exception: fails += 1; print("FAIL ", n); traceback.print_exc()
    print("%d failed" % fails); sys.exit(1 if fails else 0)
