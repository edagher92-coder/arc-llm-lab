"""Remembered-device login (cookie gwd): the real approvals server on a free port. Run: python tests/test_device_login.py"""
import hashlib, json, os, socket, sys, tempfile, time, traceback, urllib.request, urllib.error
for _m in ("gateway", "approvals", "skills", "outbox", "agent", "studio", "video"):
    sys.modules.pop(_m, None)     # other test files in the same process may have imported these with their own port/state
_s = socket.socket(); _s.bind(("127.0.0.1", 0)); os.environ["GW_APPROVAL_PORT"] = str(_s.getsockname()[1]); _s.close()
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, D)
import approvals

TMP = tempfile.mkdtemp(prefix="devlogin_")
approvals.PIN_FILE = os.path.join(TMP, "pin.json")
approvals.DEVICES_FILE = os.path.join(TMP, "trusted-devices.json")
approvals.STATE_DIR = os.path.join(TMP, "state"); os.makedirs(approvals.STATE_DIR, exist_ok=True)
_salt = b"saltsalt"
json.dump({"salt": _salt.hex(), "iterations": 1000, "hash": hashlib.pbkdf2_hmac("sha256", b"4321", _salt, 1000).hex()}, open(approvals.PIN_FILE, "w"))
B = "http://127.0.0.1:%d" % approvals.PORT
approvals.start(); time.sleep(0.3)
IP1, IP2 = "100.64.0.1", "100.64.0.2"


def call(method, path, body=None, cookie=None, ip=IP1, ua="UnitTest/1.0"):
    h = {"X-Requested-With": "approvals", "User-Agent": ua}
    if ip: h["X-Forwarded-For"] = ip
    if cookie: h["Cookie"] = cookie
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(B + path, data=data, headers=h, method=method)
    try:
        r = urllib.request.urlopen(req); return r.status, r.read().decode(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), e.headers


def cookies(hdrs):
    out = {}
    for c in hdrs.get_all("Set-Cookie") or []:
        k, v = c.split(";")[0].split("=", 1); out[k] = (v, c)
    return out


def reset():
    approvals._sessions.clear(); approvals._dev_sess.clear(); approvals._pending.clear()
    approvals._fails.update(n=0, until=0.0)
    approvals._dev.update(loaded=False, d={})
    try: os.remove(approvals.DEVICES_FILE)
    except OSError: pass


def login(remember=True, ip=IP1, cookie=None, pin="4321", ua="UnitTest/1.0"):
    s, b, h = call("POST", "/approvals/login", {"pin": pin, "remember": remember}, cookie=cookie, ip=ip, ua=ua)
    return s, cookies(h)


def store(): return json.load(open(approvals.DEVICES_FILE))["devices"]


def test_remember_true_sets_gwd_and_false_does_not():
    reset()
    s, c = login(True)
    assert s == 200 and "gwa" in c and "gwd" in c
    flags = c["gwd"][1]
    assert "Max-Age=7776000" in flags and "HttpOnly" in flags and "Secure" in flags and "SameSite=Strict" in flags and "Path=/" in flags
    assert len(c["gwd"][0]) == 64 and int(c["gwd"][0], 16) >= 0
    reset()
    s, c = login(False)
    assert s == 200 and "gwa" in c and "gwd" not in c and not os.path.exists(approvals.DEVICES_FILE)
    reset()
    s, b, h = call("POST", "/approvals/login", {"pin": "4321"})            # no remember field: server default is off
    assert s == 200 and "gwd" not in cookies(h)


def test_token_stored_hashed_never_raw_with_metadata():
    reset()
    s, c = login(True, ua="U" * 300)
    tok = c["gwd"][0]
    raw = open(approvals.DEVICES_FILE).read()
    assert tok not in raw and hashlib.sha256(tok.encode()).hexdigest() in raw
    e = store()[hashlib.sha256(tok.encode()).hexdigest()]
    assert e["ip"] == IP1 and len(e["ua"]) == 120 and e["created"] <= e["last_seen"]
    assert abs(e["expires"] - e["created"] - 90 * 86400) < 5


def test_device_cookie_same_ip_grants_session_and_marks_it_device_minted():
    reset()
    s, c = login(True)
    gwd = "gwd=" + c["gwd"][0]
    s, b, h = call("GET", "/approvals/pending.json", cookie=gwd)           # the gwa session is dropped: only gwd is sent
    assert s == 200, (s, b)
    ck = cookies(h)
    assert "gwa" in ck and "Max-Age=%d" % approvals.SESSION_TTL in ck["gwa"][1] and "HttpOnly" in ck["gwa"][1]
    assert ck["gwa"][0] in approvals._dev_sess and h.get("X-Device-Until")
    # the minted gwa keeps working by itself
    assert call("GET", "/approvals/pending.json", cookie="gwa=" + ck["gwa"][0])[0] == 200


def test_different_ip_rejected_entry_kept_and_pin_login_rebinds():
    reset()
    s, c = login(True)
    gwd = "gwd=" + c["gwd"][0]
    assert call("GET", "/approvals/pending.json", cookie=gwd, ip=IP2)[0] == 401
    assert len(store()) == 1 and approvals._fails["n"] == 0                  # kept, and not a PIN failure
    s, c2 = login(False, ip=IP2, cookie=gwd)                                 # PIN from the new IP refreshes the binding
    assert s == 200 and "gwd" not in c2
    assert call("GET", "/approvals/pending.json", cookie=gwd, ip=IP2)[0] == 200
    assert call("GET", "/approvals/pending.json", cookie=gwd, ip=IP1)[0] == 401


def test_unknown_token_ignored_and_not_a_pin_failure():
    reset()
    for tok in ("0" * 64, "zz", "a" * 10):
        assert call("GET", "/approvals/pending.json", cookie="gwd=" + tok)[0] == 401
    assert approvals._fails["n"] == 0 and approvals._fails["until"] == 0.0


def test_expired_entry_rejected_and_pruned():
    reset()
    s, c = login(True)
    h = hashlib.sha256(c["gwd"][0].encode()).hexdigest()
    d = store(); d[h]["expires"] = time.time() - 1                              # an entry that has just expired, on disk
    json.dump({"devices": d}, open(approvals.DEVICES_FILE, "w"))
    approvals._dev.update(loaded=False, d={})
    with approvals._lock: assert h not in approvals._dev_load()                 # pruned on load
    assert call("GET", "/approvals/pending.json", cookie="gwd=" + c["gwd"][0])[0] == 401
    # expiry between load and use is rejected too, and the next save prunes it
    s, c = login(True); h = hashlib.sha256(c["gwd"][0].encode()).hexdigest()
    approvals._dev["d"][h]["expires"] = time.time() - 1
    assert call("GET", "/approvals/pending.json", cookie="gwd=" + c["gwd"][0])[0] == 401
    login(True, ip=IP2)
    assert h not in store() and len(store()) == 1


def _pending():
    approvals._pending["abc123"] = dict(id="abc123", key="k", tool="pc_run_powershell", args={"command": "dir"}, why="t", created=time.time(),
                                        state="pending", decided=None, origin="phone", run=None, step=None)
    return "abc123"


def test_device_session_cannot_approve_or_deny_but_pin_session_can():
    reset()
    s, c = login(True)
    pid = _pending()
    gwd = "gwd=" + c["gwd"][0]
    s, b, h = call("POST", "/approvals/devices/forget_nothing", cookie=gwd)   # unrelated 404, just warms the device tier
    for act in ("approve", "allow", "deny"):
        s, b, h = call("POST", "/approvals/%s/%s" % (pid, act), cookie=gwd)
        assert s == 401 and json.loads(b) == {"error": "enter your PIN to approve actions", "pin_required": True}, (act, s, b)
        assert approvals._pending[pid]["state"] == "pending"
    # the minted gwa on its own is also refused
    s, b, h = call("GET", "/approvals/pending.json", cookie=gwd); tok = cookies(h)["gwa"][0]
    assert call("POST", "/approvals/%s/approve" % pid, cookie="gwa=" + tok)[0] == 401
    # everything else still works with the device-minted session
    assert call("GET", "/approvals/history.json", cookie="gwa=" + tok)[0] == 200
    # a real PIN session approves
    assert call("POST", "/approvals/%s/approve" % pid, cookie="gwa=" + c["gwa"][0])[0] == 200
    assert approvals._pending[pid]["state"] == "approved"
    pid = _pending(); approvals._pending[pid]["state"] = "pending"
    assert call("POST", "/approvals/%s/deny" % pid, cookie="gwa=" + c["gwa"][0])[0] == 200 and approvals._pending[pid]["state"] == "denied"


def test_pin_login_after_device_login_gives_a_pin_session():
    reset()
    s, c = login(True)
    gwd = "gwd=" + c["gwd"][0]
    pid = _pending()
    s, c2 = login(True, cookie=gwd)                                           # PIN again on the same device: reuses the entry
    assert c2["gwd"][0] == c["gwd"][0] and len(store()) == 1
    assert call("POST", "/approvals/%s/approve" % pid, cookie="gwa=" + c2["gwa"][0])[0] == 200


def test_devices_list_forget_and_revoke():
    reset()
    s, c = login(True); gwd = "gwd=" + c["gwd"][0]
    s, c_b = login(True, ip=IP2, ua="Other")                                  # a second device
    s, b, h = call("GET", "/approvals/devices", cookie=gwd)                   # device-minted session may list
    assert s == 200
    rows = json.loads(b)
    assert len(rows) == 2 and all(set(r) == {"id", "ip", "created", "expires", "last_seen", "ua", "current"} and len(r["id"]) == 8 for r in rows)
    assert [r["current"] for r in rows].count(True) == 1 and next(r for r in rows if r["current"])["ip"] == IP1
    assert call("GET", "/approvals/devices", ip=IP1)[0] == 401
    gwa_dev = "gwa=" + cookies(h)["gwa"][0]
    other = next(r for r in rows if not r["current"])["id"]
    s, b, _ = call("POST", "/approvals/devices/revoke", {"id": other}, cookie=gwa_dev)
    assert s == 401 and json.loads(b)["pin_required"] is True and len(store()) == 2
    s, b, _ = call("POST", "/approvals/devices/revoke", {"id": other}, cookie="gwa=" + c["gwa"][0])
    assert s == 200 and len(store()) == 1
    assert call("POST", "/approvals/devices/revoke", {"id": "nothex"}, cookie="gwa=" + c["gwa"][0])[0] == 400
    # forget: needs a session and the CSRF header; clears both cookies and the entry
    req = urllib.request.Request(B + "/approvals/devices/forget", data=b"{}", headers={"Cookie": "gwa=" + c["gwa"][0]}, method="POST")
    try: urllib.request.urlopen(req); assert False
    except urllib.error.HTTPError as e: assert e.code == 403
    assert call("POST", "/approvals/devices/forget", cookie=None)[0] == 401
    s, b, h = call("POST", "/approvals/devices/forget", cookie="gwa=%s; gwd=%s" % (c["gwa"][0], c["gwd"][0]))
    ck = cookies(h)
    assert s == 200 and "Max-Age=0" in ck["gwa"][1] and "Max-Age=0" in ck["gwd"][1] and store() == {}
    assert call("GET", "/approvals/pending.json", cookie=gwd)[0] == 401
    assert call("GET", "/approvals/pending.json", cookie="gwa=" + c["gwa"][0])[0] == 401


def test_cap_of_ten_evicts_oldest():
    reset()
    first = None
    for i in range(11):
        s, c = login(True, ip="100.64.1.%d" % i)
        if i == 0: first = c["gwd"][0]
        time.sleep(0.01)
    d = store(); assert len(d) == 10
    assert hashlib.sha256(first.encode()).hexdigest() not in d
    assert call("GET", "/approvals/pending.json", cookie="gwd=" + first, ip="100.64.1.0")[0] == 401


def test_store_survives_reload():
    reset()
    s, c = login(True)
    approvals._dev.update(loaded=False, d={})                                  # what a restart does
    s, b, h = call("GET", "/approvals/pending.json", cookie="gwd=" + c["gwd"][0])
    assert s == 200 and "gwa" in cookies(h)
    assert not os.path.exists(approvals.DEVICES_FILE + ".tmp")


def test_xff_only_trusted_from_loopback():
    assert approvals._client_ip("127.0.0.1", "100.64.0.9, 10.0.0.1") == "100.64.0.9"
    assert approvals._client_ip("::1", "100.64.0.9") == "100.64.0.9"
    assert approvals._client_ip("127.0.0.1", "") == "127.0.0.1"
    assert approvals._client_ip("203.0.113.7", "100.64.0.9") == "203.0.113.7"   # not loopback: header ignored
    # the handler uses it: a non-loopback peer cannot borrow a bound IP via the header
    reset()
    h = approvals._H.__new__(approvals._H)
    h.client_address = ("203.0.113.7", 1234); h.headers = {"X-Forwarded-For": IP1}
    class _Hd(dict):
        def get(self, k, d=None): return dict.get(self, k, d)
    h.headers = _Hd({"X-Forwarded-For": IP1})
    assert h._ip() == "203.0.113.7"
    h.client_address = ("127.0.0.1", 1234); assert h._ip() == IP1


def test_lockout_still_applies_to_pin_attempts():
    reset()
    for _ in range(approvals.MAX_FAILS):
        assert call("POST", "/approvals/login", {"pin": "0000", "remember": True})[0] == 401
    assert call("POST", "/approvals/login", {"pin": "4321", "remember": True})[0] == 429
    reset()


def test_page_has_checkbox_and_forget_line():
    assert 'id="rem" type="checkbox" checked' in approvals.PAGE and "Remember this device for 90 days" in approvals.PAGE
    assert "remember:$('#rem').checked" in approvals.PAGE and "pin_required" in approvals.PAGE and "approvals/devices/forget" in approvals.PAGE
    assert "http://" not in approvals.PAGE.replace("http://www.w3.org", "") and "https://" not in approvals.PAGE


if __name__ == "__main__":
    fails = 0
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            try: f(); print("ok   ", n)
            except Exception: fails += 1; print("FAIL ", n); traceback.print_exc()
    print("%d failed" % fails); sys.exit(1 if fails else 0)


def test_kill_switch_off_needs_a_real_pin_on_a_remembered_device(tmp_path=None):
    reset()
    s, c = login(True)
    gwd = "gwd=" + c["gwd"][0]
    kf = os.path.join(tempfile.mkdtemp(), "KILL"); open(kf, "w").write("x"); approvals.KILL_FILE = kf
    s, b, h = call("POST", "/approvals/kill", body={"on": False}, cookie=gwd)
    assert s == 401 and json.loads(b).get("pin_required") is True and os.path.exists(kf)

    s, b, h = call("POST", "/approvals/kill", body={"on": False}, cookie="gwa=" + c["gwa"][0])
    assert s == 200 and not os.path.exists(kf), (s, b)
