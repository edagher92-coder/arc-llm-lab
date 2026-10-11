"""Studio live metrics: one sampler thread, two ring buffers and the change feed behind /approvals/studio/api/stream.

  fast ring  900 points, one per tick (1 s while a stream client is connected or a job is queued/active, else 10 s)
  slow ring  1440 points, each the average of one wall-clock minute of fast points (a day at 60 s)

A point is {"t", "cpu", "ram_used_gb", "ram_total_gb", "vram_used_gb", "gpu_owner", "queue", "tps"}; any probe that cannot answer gives null.
Sources (stdlib only, Windows first, every one optional so Linux and the tests see nulls instead of errors):
  cpu           GetSystemTimes deltas (Windows); null elsewhere
  ram_*         a host_ram() callable -> (total, available) bytes (studio.host_ram: GlobalMemoryStatusEx, /proc/meminfo elsewhere)
  vram_used_gb  governor public/status.json "vram_used_gib", re-read only when the file's mtime changes; null when missing or stale
  gpu_owner     "video" | "llm" from a callable (studio supplies it from the video Queue)
  queue         queued + active jobs from a callable
  tps           Qwen generation speed from llama-server /metrics deltas: d(tokens_predicted_total) / d(tokens_predicted_seconds_total), i.e. the
                speed of requests that finished since the previous point; null when none did. Port from governor running.json; skipped in video mode.
No GPU PDH/Sysman counters here (M2). Units: *_gb are GiB (2^30), the same unit the governor writes.

The sampler parks (no probes at all, only a cheap "is a job active?" check every PARK_POLL_S) after PARK_AFTER_S with no stream client, no job and
no touch(). Budget: well under 0.5 % CPU and 5 MB (2340 small dicts plus a 256-entry event log).
"""
import collections, ctypes, json, os, re, sys, threading, time, urllib.request

GOV_STATUS = os.environ.get("GOV_STATUS_JSON", r"C:\AI\governor\public\status.json")
GOV_RUNNING = os.environ.get("GOV_RUNNING_JSON", r"C:\AI\governor\running.json")
FAST_N, SLOW_N = 900, 1440
TICK_FAST_S, TICK_IDLE_S, PARK_AFTER_S, PARK_POLL_S, PING_S = 1.0, 10.0, 60.0, 15.0, 15.0
GOV_STALE_S = 120.0
STREAM_MAX_S = 1800.0          # a stream ends after 30 min; EventSource reconnects and gets a fresh hello
FIELDS = ("t", "cpu", "ram_used_gb", "ram_total_gb", "vram_used_gb", "gpu_owner", "queue", "tps")
AVG_FIELDS = ("cpu", "ram_used_gb", "vram_used_gb", "tps")
FILE_MAX = 256 * 1024
GIB = float(2 ** 30)
_no_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # llama-server is on loopback: never go through HTTP(S)_PROXY


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and v not in (float("inf"), float("-inf"))


def _r(v, n):
    return round(float(v), n) if _num(v) else None


# ---------------- probes ----------------
def _win_system_times():
    FT = ctypes.c_ulonglong                                    # FILETIME: two DWORDs, little-endian = one 64-bit count of 100 ns
    i, k, u = FT(), FT(), FT()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u)): raise OSError("GetSystemTimes failed")
    return i.value, k.value, u.value


class CpuProbe:
    """Whole-machine CPU % from GetSystemTimes deltas (kernel time includes idle). `reader` returns (idle, kernel, user); None -> Windows API,
    or always null when not on Windows. The first call only primes the counters."""
    def __init__(self, reader=None):
        self.reader = reader if reader is not None else (_win_system_times if os.name == "nt" else None)
        self.prev = None

    def __call__(self):
        if self.reader is None: return None
        try: cur = tuple(int(x) for x in self.reader())
        except Exception:
            self.prev = None; return None
        prev, self.prev = self.prev, cur
        if not prev: return None
        di, dk, du = (c - p for c, p in zip(cur, prev))
        tot = dk + du
        if tot <= 0 or di < 0: return None
        return round(max(0.0, min(100.0, (1.0 - di / tot) * 100.0)), 1)


class JsonFile:
    """A small JSON file re-read only when its mtime (or size) changes. A file mid-replace or unparsable keeps the last good value."""
    def __init__(self, path):
        self.path, self.sig, self.data, self.mtime, self.reads = path, None, None, None, 0

    def get(self):
        try: st = os.stat(self.path)
        except (OSError, TypeError, ValueError):
            self.sig = self.data = self.mtime = None; return None
        sig = (st.st_mtime_ns, st.st_size)
        if sig != self.sig and st.st_size <= FILE_MAX:
            try:
                with open(self.path, encoding="utf-8-sig") as f: d = json.load(f)
                self.reads += 1
                if isinstance(d, dict): self.data, self.sig, self.mtime = d, sig, st.st_mtime
            except (OSError, ValueError):
                pass
        return self.data

    def age(self, now=None):
        return None if self.mtime is None else max(0.0, (now or time.time()) - self.mtime)


def parse_metric(text, name):
    m = re.search(r"(?m)^" + re.escape(name) + r"(?:\{[^}]*\})?\s+([0-9.eE+-]+)\s*$", text or "")
    try: return float(m.group(1)) if m else None
    except ValueError: return None


def _http_get(url, timeout):
    with _no_proxy.open(url, timeout=timeout) as r:
        return r.read(FILE_MAX).decode("utf-8", "replace")


class TpsProbe:
    """Qwen tokens/s from llama-server /metrics. port_fn() -> port or None; get(url, timeout) -> text. A failed fetch backs off 10 s."""
    def __init__(self, port_fn, get=None, backoff_s=10.0, timeout=0.8):
        self.port_fn, self.get, self.backoff_s, self.timeout = port_fn, get or _http_get, backoff_s, timeout
        self.prev, self.until, self.calls = None, 0.0, 0

    def __call__(self, owner=None, now=None):
        now = now or time.monotonic()
        if owner == "video": self.prev = None; return None      # the LLM is unloaded or about to be: do not poke it
        try: port = self.port_fn()
        except Exception: port = None
        if not port: self.prev = None; return None
        if now < self.until: return None
        try:
            self.calls += 1
            text = self.get("http://127.0.0.1:%d/metrics" % port, self.timeout)
        except Exception:
            self.prev, self.until = None, now + self.backoff_s; return None
        n, s = parse_metric(text, "llamacpp:tokens_predicted_total"), parse_metric(text, "llamacpp:tokens_predicted_seconds_total")
        if n is None or s is None: self.prev = None; return None
        prev, self.prev = self.prev, (port, n, s)
        if not prev or prev[0] != port: return None
        dn, ds = n - prev[1], s - prev[2]
        if dn <= 0 or ds <= 0: return None                       # nothing finished, or llama-server restarted (counters reset)
        return round(dn / ds, 1)


def running_port(jf):
    """Port of the running Qwen from governor running.json ({"port": 10001, ...}), or None."""
    d = jf.get() or {}
    p = d.get("port")
    return int(p) if isinstance(p, int) and not isinstance(p, bool) and 0 < p < 65536 else None


# ---------------- rings ----------------
def average(points, t):
    """One slow point from a minute of fast points: means of cpu/ram_used/vram_used/tps (nulls skipped, all null -> null), ram_total and
    gpu_owner = the last known value, queue = the maximum."""
    out = {"t": t}
    for k in AVG_FIELDS:
        vs = [p[k] for p in points if _num(p.get(k))]
        out[k] = round(sum(vs) / len(vs), 2) if vs else None
    out["ram_total_gb"] = next((p["ram_total_gb"] for p in reversed(points) if _num(p.get("ram_total_gb"))), None)
    out["gpu_owner"] = next((p["gpu_owner"] for p in reversed(points) if p.get("gpu_owner")), None)
    qs = [p["queue"] for p in points if _num(p.get("queue"))]
    out["queue"] = max(qs) if qs else None
    return {k: out.get(k) for k in FIELDS}


class Rings:
    def __init__(self, fast_n=FAST_N, slow_n=SLOW_N):
        self.fast, self.slow = collections.deque(maxlen=fast_n), collections.deque(maxlen=slow_n)
        self.bucket, self.acc = None, []

    def add(self, p):
        self.fast.append(p)
        b = int(p["t"] // 60)
        if self.bucket is not None and b != self.bucket and self.acc:
            self.slow.append(average(self.acc, self.bucket * 60)); self.acc = []
        self.bucket = b; self.acc.append(p)


def frame(event, data):
    return b"event: " + event.encode() + b"\ndata: " + json.dumps(data, separators=(",", ":")).encode() + b"\n\n"


# ---------------- sampler ----------------
class Sampler:
    """One daemon thread. Feeds the rings and an event log of (seq, name, data) for the stream: "m" every tick, "job" when a job's public
    dict changes (or {"id", "gone": true} when it leaves the list), "sys" when the system dict (mode, linger, ComfyUI, governor) changes."""
    def __init__(self, host_ram=None, owner_fn=None, queue_fn=None, jobs_fn=None, sys_fn=None, gov_status=GOV_STATUS, gov_running=GOV_RUNNING,
                 cpu=None, tps=None, clock=time.time, tick_fast=TICK_FAST_S, tick_idle=TICK_IDLE_S, park_after=PARK_AFTER_S, park_poll=PARK_POLL_S,
                 ping_s=PING_S, fast_n=FAST_N, slow_n=SLOW_N, gov_stale_s=GOV_STALE_S, events_max=256, stream_max_s=STREAM_MAX_S):
        self.host_ram, self.owner_fn, self.queue_fn, self.jobs_fn, self.sys_fn = host_ram, owner_fn, queue_fn, jobs_fn, sys_fn
        self.gov, self.run_file = JsonFile(gov_status), JsonFile(gov_running)
        self.cpu = cpu if cpu is not None else CpuProbe()
        self.tps = tps if tps is not None else TpsProbe(lambda: running_port(self.run_file))
        self.clock, self.tick_fast, self.tick_idle, self.park_after, self.park_poll = clock, tick_fast, tick_idle, park_after, park_poll
        self.ping_s, self.gov_stale_s, self.stream_max_s = ping_s, gov_stale_s, stream_max_s
        self.rings = Rings(fast_n, slow_n)
        self.cv = threading.Condition()
        self.seq, self.events = 0, collections.deque(maxlen=events_max)
        self.clients, self.last_use, self.parked, self.ticks = 0, time.monotonic(), False, 0
        self._jobs_prev, self._sys_prev, self._sys_now = None, None, None
        self._thread, self._stop, self._wake, self._last_tick, self._errs = None, False, False, 0.0, 0

    # -- lifecycle --
    def start(self):
        with self.cv:
            if self._thread is not None and self._thread.is_alive(): return
            self._stop = False
            self._thread = threading.Thread(target=self._main, name="studio-metrics", daemon=True)
            self._thread.start()

    def running(self):
        return bool(self._thread is not None and self._thread.is_alive())

    def stop(self, timeout=2.0):
        with self.cv:
            self._stop = True; self.cv.notify_all()
        t = self._thread
        if t is not None and t is not threading.current_thread(): t.join(timeout)

    def touch(self):
        """Someone looked (stats request, stream connect): wake a parked or slow sampler."""
        with self.cv:
            self.last_use = time.monotonic()
            if self.parked or self._slow_wait: self._wake = True; self.cv.notify_all()

    def poke(self):
        """Something changed (a POST that queues, cancels or switches mode): tick soon rather than at the next interval."""
        with self.cv:
            self.last_use = time.monotonic(); self._wake = True; self.cv.notify_all()

    _slow_wait = False

    def client_enter(self):
        with self.cv:
            self.clients += 1; self.last_use = time.monotonic(); self._wake = True; self.cv.notify_all()

    def client_exit(self):
        with self.cv:
            self.clients = max(0, self.clients - 1); self.last_use = time.monotonic()

    def _active(self):
        try: return bool(self.queue_fn and (self.queue_fn() or 0) > 0)
        except Exception: return False

    def cadence(self, active=None):
        """"fast" | "idle" | "park": what the next wait should be."""
        if active is None: active = self._active()
        if self.clients or active: return "fast"
        if time.monotonic() - self.last_use >= self.park_after: return "park"
        return "idle"

    def _main(self):
        while True:
            with self.cv:
                if self._stop: return
            try:
                self.tick()
            except Exception as e:                                # a broken probe must never kill the thread
                self._errs += 1
                if self._errs <= 3: sys.stderr.write("studio_metrics: tick failed: %r\n" % (e,))
            mode = self.cadence()
            with self.cv:
                if self._stop: return
                if mode == "park":
                    self.parked = True
                    while not self._stop and not self._wake:
                        self.cv.wait(self.park_poll)
                        if self._wake or self.clients: break
                        self.cv.release()
                        try: act = self._active()                 # the only work done while parked
                        finally: self.cv.acquire()
                        if act: break
                    self.parked = False
                else:
                    wait = self.tick_fast if mode == "fast" else self.tick_idle
                    self._slow_wait = mode != "fast"
                    end = time.monotonic() + wait
                    while not self._stop and not self._wake:
                        rem = end - time.monotonic()
                        if rem <= 0: break
                        self.cv.wait(rem)
                    self._slow_wait = False
                    if self._wake:                                # a poke: still keep at least half a fast tick between points
                        gap = self.tick_fast * 0.5 - (time.monotonic() - self._last_tick)
                        if gap > 0: self.cv.wait(gap)
                self._wake = False

    # -- one sample --
    def _gov_sys(self, now):
        d = self.gov.get()
        if not d: return None
        age = self.gov.age(now)
        return {"phase": d.get("phase") if isinstance(d.get("phase"), str) else None, "phase_since": d.get("phase_since") if _num(d.get("phase_since")) else None,
                "mode": d.get("mode") if isinstance(d.get("mode"), str) else None, "profile": d.get("profile") if isinstance(d.get("profile"), str) else None,
                "loaded": d.get("loaded") if isinstance(d.get("loaded"), bool) else None, "stale": bool(age is not None and age > self.gov_stale_s)}

    def sample(self, now=None):
        """One point (no side effects on the rings)."""
        now = self.clock() if now is None else now
        p = dict.fromkeys(FIELDS); p["t"] = round(now, 1)
        try: p["cpu"] = _r(self.cpu(), 1)
        except Exception: pass
        try:
            tot, avail = self.host_ram() if self.host_ram else (None, None)
            if _num(tot) and tot > 0:
                p["ram_total_gb"] = round(tot / GIB, 1)
                if _num(avail): p["ram_used_gb"] = round(max(0.0, tot - avail) / GIB, 2)
        except Exception: pass
        try:
            d = self.gov.get()
            age = self.gov.age(now)
            if d and age is not None and age <= self.gov_stale_s and _num(d.get("vram_used_gib")): p["vram_used_gb"] = round(float(d["vram_used_gib"]), 2)
        except Exception: pass
        try: p["gpu_owner"] = self.owner_fn() if self.owner_fn else None
        except Exception: pass
        if p["gpu_owner"] not in ("video", "llm"): p["gpu_owner"] = None
        try:
            qn = self.queue_fn() if self.queue_fn else None
            p["queue"] = int(qn) if _num(qn) else None
        except Exception: pass
        try: p["tps"] = _r(self.tps(p["gpu_owner"]), 1)
        except Exception: pass
        return p

    def _system(self, now):
        s = {}
        try: s = dict(self.sys_fn() or {}) if self.sys_fn else {}
        except Exception as e: s = {"error": type(e).__name__}
        s["governor"] = self._gov_sys(now)
        return s

    def _jobs(self):
        try: return list(self.jobs_fn() or []) if self.jobs_fn else []
        except Exception: return None                              # a failed read is not "every job is gone"

    def tick(self):
        now = self.clock()
        p = self.sample(now)
        jobs = self._jobs()
        sysd = self._system(now)
        with self.cv:
            self.rings.add(p)
            self._push("m", p)
            if jobs is not None:
                cur = {j["id"]: (json.dumps(j, sort_keys=True, separators=(",", ":")), j) for j in jobs if isinstance(j, dict) and j.get("id")}
                if self._jobs_prev is not None:                    # the first tick only takes the baseline
                    for jid, (ser, j) in cur.items():
                        if self._jobs_prev.get(jid) != ser: self._push("job", j)
                    for jid in self._jobs_prev:
                        if jid not in cur: self._push("job", {"id": jid, "gone": True})
                self._jobs_prev = {k: v[0] for k, v in cur.items()}
            ser = json.dumps(sysd, sort_keys=True, separators=(",", ":"))
            if self._sys_prev is not None and ser != self._sys_prev: self._push("sys", sysd)
            self._sys_prev, self._sys_now = ser, sysd
            self.ticks += 1; self._last_tick = time.monotonic()
        return p

    def _push(self, name, data):              # caller holds cv
        self.seq += 1
        self.events.append((self.seq, name, data))
        self.cv.notify_all()

    # -- readers --
    def snapshot(self):
        """For /api/stats: both rings as they stand."""
        with self.cv:
            return {"v": 1, "now": round(self.clock(), 1), "tick_s": self.tick_fast, "fields": list(FIELDS), "fast": list(self.rings.fast),
                    "slow": list(self.rings.slow), "running": self.running(), "parked": self.parked}

    def hello(self, backfill=FAST_N):
        """The first stream event: everything a fresh page needs. Returns (data, seq): events after seq follow it."""
        jobs = self._jobs()
        with self.cv:
            seq = self.seq
            pts = list(self.rings.fast)[-backfill:] if backfill > 0 else []
            sysd = self._sys_now
        if sysd is None: sysd = self._system(self.clock())
        return {"v": 1, "seq": seq, "now": round(self.clock(), 1), "tick_s": self.tick_fast, "ping_s": self.ping_s, "fields": list(FIELDS), "points": pts,
                "jobs": jobs or [], "sys": sysd}, seq

    def wait_events(self, seq, timeout):
        """(events, new_seq, resync). events is None when the sampler stopped. resync=True when the log no longer reaches back to seq."""
        end = time.monotonic() + max(0.0, timeout)
        with self.cv:
            while self.seq == seq and not self._stop:
                rem = end - time.monotonic()
                if rem <= 0: break
                self.cv.wait(rem)
            if self._stop: return None, seq, False
            if self.seq == seq: return [], seq, False
            if not self.events or self.events[0][0] > seq + 1: return [], self.seq, True
            return [(n, d) for s, n, d in self.events if s > seq], self.seq, False


def sse(s, backfill=FAST_N, max_s=None):
    """The event stream for one client, as a generator of bytes for approvals' {"stream": ...} responses. The client is counted only once the
    generator runs (approvals refuses a 5th stream before that)."""
    s.start(); s.client_enter()
    try:
        h, seq = s.hello(backfill)
        yield b"retry: 3000\n\n" + frame("hello", h)
        t0 = last_ping = time.monotonic()
        limit = s.stream_max_s if max_s is None else max_s
        while time.monotonic() - t0 < limit:
            evs, seq, resync = s.wait_events(seq, max(0.02, min(s.ping_s - (time.monotonic() - last_ping), limit - (time.monotonic() - t0))))
            if evs is None: return
            out = b""
            if resync:
                h, seq = s.hello(backfill); out = frame("hello", h)
            else:
                for n, d in evs: out += frame(n, d)
            if time.monotonic() - last_ping >= s.ping_s:
                out += b": ping\n\n"; last_ping = time.monotonic()
            if out: yield out
    finally:
        s.client_exit()
