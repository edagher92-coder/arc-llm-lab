"""Studio live stream + Tailscale-identity tier: the real approvals server with the Studio routes and a fast sampler. Run: python tests/test_studio_stream.py"""
import hashlib, http.client, json, os, socket, struct, sys, time, traceback, urllib.request, urllib.error
for _m in ("gateway", "approvals", "skills", "outbox", "agent", "studio", "studio_metrics", "video", "tts_server", "cc_notify", "tools_video_mcp", "tools_local_llm",
           "build_workflow", "test_video"):
    sys.modules.pop(_m, None)     # other test files in the same process may have imported these with their own port/state
_s = socket.socket(); _s.bind(("127.0.0.1", 0)); os.environ["GW_APPROVAL_PORT"] = str(_s.getsockname()[1]); _s.close()
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, D); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import approvals, studio, studio_metrics, video
import test_video as tv


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


approvals.PIN_FILE = os.path.join(tv.TMP, "pin-stream.json")
salt = b"saltsalt"
json.dump({"salt": salt.hex(), "iterations": 1000, "hash": hashlib.pbkdf2_hmac("sha256", b"4321", salt, 1000).hex()}, open(approvals.PIN_FILE, "w"))
PORT = approvals.PORT
T = "/approvals/studio"
rig = tv.Rig(quiet_s=0)
GOV = os.path.join(rig.t, "status.json")
json.dump({"vram_used_gib": 17.5, "phase": "ready", "phase_since": 1760000000, "mode": "AUTO", "profile": "MAX", "loaded": True}, open(GOV, "w"))
SAMPLER = studio_metrics.Sampler(gov_status=GOV, gov_running=os.path.join(rig.t, "no-running.json"), cpu=studio_metrics.CpuProbe(reader=None),
                                 tick_fast=0.05, tick_idle=0.2, park_after=5, park_poll=0.2, ping_s=0.4)
assert approvals._ident["enabled"] is False and approvals._ident["srv"] is None          # identity login is off until configured
studio.register(approvals, rig.q, rig.q.cfg, D, cfg={"video": {}}, sampler=SAMPLER)
assert approvals._ident["enabled"] is False and approvals._ident["srv"] is None          # still off: no studio.ts_identity block
approvals.start(); time.sleep(0.3)
cookie = None


def call(method, path, body=None, cookie=None, headers=None, xrw=True, port=None):
    h = dict(headers or {})
    if xrw: h["X-Requested-With"] = "approvals"
    if cookie: h["Cookie"] = cookie
    data = json.dumps(body).encode() if body is not None else None
    if data is not None: h["Content-Type"] = "application/json"
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port or PORT, path), data=data, headers=h, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=10); return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def login():
    r = call("POST", "/approvals/login", {"pin": "4321"})
    assert r[0] == 200, r
    return r[2].get("Set-Cookie").split(";")[0]


cookie = login()


class SSE:
    """A raw event-stream reader (http.client: the response has no Content-Length and ends when the server closes)."""
    def __init__(self, path=T + "/api/stream", cookie=None, headers=None, port=None):
        self.c = http.client.HTTPConnection("127.0.0.1", port or PORT, timeout=5)
        h = dict(headers or {})
        if cookie: h["Cookie"] = cookie
        self.c.request("GET", path, headers=h)
        self.sock = self.c.sock                   # http.client drops its own reference once it sees Connection: close
        self.r = self.c.getresponse()
        self.status, self.headers = self.r.status, self.r.headers

    def event(self, timeout=5):
        """Next frame as (name, data) or ("ping", None) for a ': ping' comment; skips the retry line."""
        self.sock.settimeout(timeout)
        name, data, lines = None, None, []
        while True:
            line = self.r.fp.readline()
            if not line: raise EOFError("stream closed")
            line = line.rstrip(b"\r\n")
            if line == b"":
                if lines: break
                continue
            lines.append(line)
        for l in lines:
            if l.startswith(b": "): return "ping", l[2:].decode()
            if l.startswith(b"retry:"): return self.event(timeout) if len(lines) == 1 else None
            if l.startswith(b"event: "): name = l[7:].decode()
            if l.startswith(b"data: "): data = json.loads(l[6:])
        return name, data

    def until(self, pred, timeout=5):
        end = time.time() + timeout
        while time.time() < end:
            ev = self.event(max(0.1, end - time.time()))
            if ev and pred(ev): return ev
        raise AssertionError("no matching event")

    def close(self, rst=False):
        if rst:   # abort: RST instead of FIN, like a phone dropping off the network
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        for x in (self.r, self.sock):
            try: x.close()
            except Exception: pass
        try: self.c.close()
        except Exception: pass


def wait_for(pred, secs=5):
    end = time.time() + secs
    while time.time() < end:
        if pred(): return True
        time.sleep(0.02)
    return False


def test_stream_and_stats_need_auth():
    for p in ("/api/stream", "/api/stats"):
        s, b, h = call("GET", T + p)
        assert s == 401 and "error" in json.loads(b) and "event-stream" not in h["Content-Type"], (p, s)
    st = SSE(cookie="gwa=forged")
    assert st.status == 401; st.close()
    assert approvals.stream_count() == 0


def test_sse_framing_hello_then_m_then_ping():
    st = SSE(cookie=cookie)
    try:
        assert st.status == 200 and st.headers["Content-Type"].startswith("text/event-stream"), st.headers
        assert st.headers["Cache-Control"] == "no-cache" and st.headers["X-Accel-Buffering"] == "no" and st.headers["Connection"] == "close"
        assert st.headers.get("Content-Length") is None and st.headers["X-Content-Type-Options"] == "nosniff"
        name, h = st.event()
        assert name == "hello", name
        assert h["v"] == 1 and h["fields"] == list(studio_metrics.FIELDS) and isinstance(h["points"], list) and isinstance(h["jobs"], list), h
        assert set(h["sys"]) >= {"mode", "gov_mode", "linger_until", "comfy", "governor"} and h["sys"]["governor"]["phase"] == "ready", h["sys"]
        assert rig.t not in json.dumps(h), "a server path reached the browser"
        name, m = st.until(lambda e: e[0] == "m")
        assert list(m) == list(studio_metrics.FIELDS) and m["vram_used_gb"] == 17.5 and m["gpu_owner"] in ("llm", "video") and m["queue"] == 0, m
        assert m["ram_total_gb"] is None or m["ram_total_gb"] > 0
        assert st.until(lambda e: e[0] == "ping", 3) == ("ping", "ping")
        assert approvals.stream_count() == 1 and SAMPLER.clients == 1
    finally:
        st.close()
    assert wait_for(lambda: approvals.stream_count() == 0 and SAMPLER.clients == 0), (approvals.stream_count(), SAMPLER.clients)


def test_backfill_query():
    assert call("GET", T + "/api/stats", cookie=cookie)[0] == 200                     # first use starts the sampler
    assert wait_for(lambda: len(SAMPLER.rings.fast) >= 5)
    for q, want in (("?backfill=0", 0), ("?backfill=3", 3), ("?backfill=x", None), ("?backfill=-5", 0)):
        st = SSE(T + "/api/stream" + q, cookie=cookie)
        try:
            name, h = st.event()
            assert name == "hello" and (len(h["points"]) == want if want is not None else len(h["points"]) >= 3), (q, len(h["points"]))
        finally: st.close()
    assert wait_for(lambda: approvals.stream_count() == 0)


def test_stats_ring_json():
    assert call("GET", T + "/api/stats", cookie=cookie)[0] == 200
    assert wait_for(lambda: len(SAMPLER.rings.fast) >= 3)
    s, b, h = call("GET", T + "/api/stats", cookie=cookie)
    d = json.loads(b)
    assert s == 200 and h["Content-Type"] == "application/json" and d["v"] == 1 and d["fields"] == list(studio_metrics.FIELDS), d
    assert len(d["fast"]) >= 3 and isinstance(d["slow"], list) and d["running"] is True and d["tick_s"] == 0.05
    assert all(list(p) == list(studio_metrics.FIELDS) for p in d["fast"])


def test_job_and_sys_change_events():
    st = SSE(cookie=cookie)
    try:
        assert st.event()[0] == "hello"
        with rig.q.lock: rig.q.jobs.append(dict(id="5ee5ee01", workflow="t2v", params={"prompt": "p"}, files={}, state="running", created=time.time(),
                                                  started=time.time(), note="sampling", progress=10.0, step="1/8"))
        try:
            _, j = st.until(lambda e: e[0] == "job" and e[1].get("id") == "5ee5ee01")
            assert j["state"] == "running" and j["progress"] == 10.0 and j["step"] == "1/8" and "files" not in j, j
            _, sd = st.until(lambda e: e[0] == "sys" and e[1]["mode"] == "busy")
            _, m = st.until(lambda e: e[0] == "m" and e[1]["queue"] == 1)
            assert m["gpu_owner"] == "video", m
            rig.q._set("5ee5ee01", progress=55.0)
            _, j = st.until(lambda e: e[0] == "job" and e[1].get("id") == "5ee5ee01" and e[1].get("progress") == 55.0)
        finally:
            with rig.q.lock: rig.q.jobs[:] = [x for x in rig.q.jobs if x["id"] != "5ee5ee01"]
        assert st.until(lambda e: e[0] == "job" and e[1] == {"id": "5ee5ee01", "gone": True})
        st.until(lambda e: e[0] == "sys" and e[1]["mode"] != "busy")
        json.dump({"vram_used_gib": 4.0, "phase": "loading", "phase_since": 1760000100, "mode": "AUTO", "profile": "MAX", "loaded": False}, open(GOV, "w"))
        os.utime(GOV, (time.time() + 1, time.time() + 1))
        _, sd = st.until(lambda e: e[0] == "sys" and (e[1].get("governor") or {}).get("phase") == "loading")
        assert sd["governor"]["loaded"] is False and sd["governor"]["stale"] is False
        st.until(lambda e: e[0] == "m" and e[1]["vram_used_gb"] == 4.0)
    finally:
        st.close()
        json.dump({"vram_used_gib": 17.5, "phase": "ready", "phase_since": 1760000000, "mode": "AUTO", "profile": "MAX", "loaded": True}, open(GOV, "w"))
        os.utime(GOV, (time.time() + 2, time.time() + 2))
    assert wait_for(lambda: approvals.stream_count() == 0)


def test_four_stream_cap_then_429_then_slot_frees():
    assert wait_for(lambda: approvals.stream_count() == 0)
    open_ = []
    try:
        for _ in range(approvals.STREAM_MAX):
            st = SSE(cookie=cookie); assert st.status == 200 and st.event()[0] == "hello"; open_.append(st)
        assert approvals.stream_count() == 4
        s, b, h = call("GET", T + "/api/stream", cookie=cookie)
        assert s == 429 and "too many" in json.loads(b)["error"] and "event-stream" not in h["Content-Type"], (s, b)
        assert approvals.stream_count() == 4 and SAMPLER.clients == 4                 # the refused one was never counted
        assert call("GET", T + "/api/stats", cookie=cookie)[0] == 200                   # ordinary routes still answer
        open_.pop().close()
        assert wait_for(lambda: approvals.stream_count() == 3), approvals.stream_count()
        st = SSE(cookie=cookie); assert st.status == 200 and st.event()[0] == "hello"; open_.append(st)
    finally:
        for st in open_: st.close()
    assert wait_for(lambda: approvals.stream_count() == 0 and SAMPLER.clients == 0)


def test_broken_pipe_cleans_up():
    assert wait_for(lambda: approvals.stream_count() == 0)
    sts = [SSE(cookie=cookie) for _ in range(3)]
    for st in sts: assert st.event()[0] == "hello"
    assert approvals.stream_count() == 3 and SAMPLER.clients == 3
    for st in sts: st.close(rst=True)                                                # abrupt resets, no FIN
    assert wait_for(lambda: approvals.stream_count() == 0 and SAMPLER.clients == 0, 5), (approvals.stream_count(), SAMPLER.clients)
    st = SSE(cookie=cookie); assert st.status == 200; st.close()                     # slots were released


def test_existing_handlers_unchanged_by_streaming():
    s, b, h = call("GET", T + "/api/jobs", cookie=cookie)
    assert s == 200 and h["Content-Length"] == str(len(b)) and h["Cache-Control"] == "no-store"
    assert call("GET", T + "/api/jobs")[0] == 401
    assert call("POST", T + "/api/fav", {"id": "deadbeef", "fav": True}, cookie)[0] == 404
    assert call("POST", T + "/api/fav", {"id": "deadbeef", "fav": True}, cookie, xrw=False)[0] == 403


# ---------------- Tailscale identity tier ----------------
ALLOW = "elz@example.com"
IDP = free_port()


def ident_on():
    if approvals._ident["srv"] is None:
        ok, err = approvals.identity_configure(enabled=True, allow_logins=["Elz@Example.com", "jörg@example.com"], listen="127.0.0.1:%d" % IDP)
        assert ok and not err, err


def idcall(method, path, login=None, body=None, cookie=None, xrw=True, extra=()):
    c = http.client.HTTPConnection("127.0.0.1", IDP, timeout=5)
    c.putrequest(method, path)
    if login is not None: c.putheader("Tailscale-User-Login", login)
    for k, v in extra: c.putheader(k, v)
    if xrw: c.putheader("X-Requested-With", "approvals")
    if cookie: c.putheader("Cookie", cookie)
    data = json.dumps(body).encode() if body is not None else b""
    if method == "POST": c.putheader("Content-Type", "application/json"); c.putheader("Content-Length", str(len(data)))
    c.endheaders(data if method == "POST" else None)
    r = c.getresponse(); out = (r.status, r.read(), r.headers); c.close()
    return out


def gws_of(h):
    sc = [v for k, v in h.items() if k.lower() == "set-cookie"]
    return next((v for v in sc if v.startswith("gws=")), None), sc


def test_identity_refuses_non_loopback_and_is_off_by_default():
    assert studio.ts_identity_cfg({}) == {"enabled": False, "allow_logins": [], "listen": "127.0.0.1:8096"}
    assert studio.ts_identity_cfg({"studio": {"ts_identity": {"enabled": "yes", "allow_logins": ["a@b"]}}})["enabled"] is False      # only a real true
    if approvals._ident["srv"] is not None: return                                   # another test turned it on already
    ok, err = approvals.identity_configure(enabled=True, allow_logins=[ALLOW], listen="0.0.0.0:%d" % free_port())
    assert not ok and "loopback" in err and approvals._ident["srv"] is None, err
    ok, err = approvals.identity_configure(enabled=True, allow_logins=[], listen="127.0.0.1:%d" % free_port())
    assert not ok and approvals._ident["enabled"] is False and "allow_logins" in err
    ok, err = approvals.identity_configure(enabled=True, allow_logins=[ALLOW], listen="nonsense")
    assert not ok and approvals._ident["enabled"] is False


def test_ts_login_normalisation():
    n = approvals.ts_login_norm
    assert n("Elz@Example.COM") == "elz@example.com" and n("  elz@example.com ") == "elz@example.com"
    assert n("=?utf-8?q?J=C3=B6rg=40Example.com?=") == "jörg@example.com"
    assert n("=?UTF-8?B?SsO2cmdARXhhbXBsZS5jb20=?=") == "jörg@example.com"
    for bad in ("", None, "a b@c", "a@b;c", "x" * 2000, 5):
        assert n(bad) == "", bad


def test_identity_allowlisted_login_gets_gws_and_studio_but_not_gwa():
    ident_on()
    s, b, h = idcall("GET", T, login="Elz@Example.com")                               # the Studio shell, through tailscale serve
    g, all_sc = gws_of(h)
    assert s == 200 and g, (s, all_sc)
    assert not any(v.startswith("gwa=") for v in all_sc)                              # never a PIN session
    attrs = [a.strip() for a in g.split(";")]
    assert "Path=/approvals/studio" in attrs and "HttpOnly" in attrs and "Secure" in attrs and "SameSite=Strict" in attrs and "Max-Age=43200" in attrs, attrs
    gws = g.split(";")[0]
    s, b, h = idcall("GET", T + "/api/jobs", login=ALLOW, cookie=gws)
    assert s == 200 and isinstance(json.loads(b), list) and gws_of(h)[0] is None, s           # an existing session is reused
    assert idcall("GET", T + "/api/system", login=ALLOW, cookie=gws)[0] == 200
    s, b, _ = idcall("POST", T + "/api/fav", ALLOW, {"id": "deadbeef", "fav": True}, gws)
    assert s == 404, (s, b)                                                           # the handler ran: Studio POST works on the ts tier
    assert idcall("POST", T + "/api/fav", ALLOW, {"id": "deadbeef", "fav": True}, gws, xrw=False)[0] == 403
    assert idcall("POST", T + "/api/fav", ALLOW, {"id": "deadbeef", "fav": True})[0] == 401      # a POST needs the cookie, not just the header
    # no approvals, no Control Centre, no PIN-only Studio routes
    assert idcall("GET", "/approvals/pending.json", ALLOW, cookie=gws)[0] == 401
    assert idcall("GET", "/approvals/history.json", ALLOW, cookie=gws)[0] == 401
    for path, body in (("/approvals/abc123/approve", {}), ("/approvals/mode", {"mode": "LEAN"}), ("/approvals/kill", {"on": True}),
                       ("/approvals/model", {"action": "load"}), (T + "/api/delete", {"id": "deadbeef"})):
        s, b, _ = idcall("POST", path, ALLOW, body, gws); assert s == 401, (path, s, b)
    # the stream works on the ts tier too
    st = SSE(cookie=gws, headers={"Tailscale-User-Login": ALLOW}, port=IDP)
    try: assert st.status == 200 and st.event()[0] == "hello"
    finally: st.close()
    assert wait_for(lambda: approvals.stream_count() == 0)


def test_identity_delete_needs_pin_and_pin_still_works_there():
    ident_on()
    gws = gws_of(idcall("GET", T, login=ALLOW)[2])[0].split(";")[0]
    jid, _, _ = rig.q.submit("t2v", {"prompt": "ts delete", "seconds": 2}); rig.wait(jid, ("done",))
    assert idcall("POST", T + "/api/delete", ALLOW, {"id": jid}, gws)[0] == 401 and rig.q.get(jid)
    s, b, _ = idcall("POST", T + "/api/delete", ALLOW, {"id": jid}, gws + "; " + cookie)      # the PIN session upgrades the same page
    assert s == 200 and rig.q.get(jid) is None, (s, b)


def test_identity_non_allowlisted_login_falls_back_to_pin():
    ident_on()
    s, b, h = idcall("GET", T, login="mallory@example.com")
    assert s == 200 and gws_of(h)[0] is None                                          # the shell is public; no session minted
    assert idcall("GET", T + "/api/jobs", login="mallory@example.com")[0] == 401
    assert idcall("GET", T + "/api/jobs")[0] == 401                                   # no header (Funnel, tagged device): PIN tier only
    assert idcall("GET", T + "/api/jobs", cookie=cookie)[0] == 200                    # the PIN session works on this socket as anywhere
    two = idcall("GET", T + "/api/jobs", login=ALLOW, extra=[("Tailscale-User-Login", "other@example.com")])
    assert two[0] == 401                                                              # duplicated identity headers: refused
    gws = gws_of(idcall("GET", T, login=ALLOW)[2])[0].split(";")[0]
    assert idcall("POST", T + "/api/fav", "=?utf-8?q?J=C3=B6rg=40example.com?=", {"id": "deadbeef", "fav": True}, gws)[0] == 401   # a session is bound to its login
    assert idcall("GET", T + "/api/jobs", login="mallory@example.com", cookie=gws)[0] == 401


def test_identity_rfc2047_and_case():
    ident_on()
    s, b, h = idcall("GET", T + "/api/jobs", login="=?utf-8?q?J=C3=B6rg=40EXAMPLE.com?=")
    assert s == 200 and gws_of(h)[0], s
    assert idcall("GET", T + "/api/jobs", login="ELZ@EXAMPLE.COM")[0] == 200


def test_identity_headers_on_main_port_always_ignored():
    ident_on()
    assert call("GET", T + "/api/jobs", headers={"Tailscale-User-Login": ALLOW})[0] == 401
    s, b, h = call("GET", T, headers={"Tailscale-User-Login": ALLOW})
    assert s == 200 and gws_of(h)[0] is None                                          # nothing minted on 8093
    gws = gws_of(idcall("GET", T, login=ALLOW)[2])[0].split(";")[0]
    assert call("GET", T + "/api/jobs", cookie=gws, headers={"Tailscale-User-Login": ALLOW})[0] == 401     # gws is honoured only on the identity socket
    assert call("POST", T + "/api/fav", {"id": "deadbeef", "fav": True}, gws, headers={"Tailscale-User-Login": ALLOW})[0] == 401
    seen = {}
    approvals.register_extra({"GET /approvals/zz-echo": lambda req: (seen.update(req["headers"]), (200, "{}", "application/json"))[1]})
    call("GET", "/approvals/zz-echo", headers={"Tailscale-User-Login": ALLOW, "Tailscale-User-Name": "Elz"})
    assert not any(k.startswith("tailscale-") for k in seen), seen                    # handlers on 8093 never even see them


if __name__ == "__main__":
    fails = 0
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            try: f(); print("ok   ", n)
            except Exception: fails += 1; print("FAIL ", n); traceback.print_exc()
    approvals.identity_stop(); SAMPLER.stop(); rig.close()
    print("%d failed" % fails); sys.exit(1 if fails else 0)
