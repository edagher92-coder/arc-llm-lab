"""Studio code-tab chat tests: the real approvals server + studio_chat routes against a stub llama-swap that streams OpenAI-style SSE.
Run: python tests/test_studio_chat.py (or pytest)."""
import hashlib, http.client, json, os, socket, sys, tempfile, threading, time, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
for _m in ("gateway", "approvals", "skills", "outbox", "agent", "studio", "studio_metrics", "studio_chat", "video", "tts_server", "cc_notify", "tools_video_mcp", "tools_local_llm", "build_workflow", "test_video"):
    sys.modules.pop(_m, None)     # other test files in the same process may have imported these with their own port/state
_s = socket.socket(); _s.bind(("127.0.0.1", 0)); os.environ["GW_APPROVAL_PORT"] = str(_s.getsockname()[1]); _s.close()
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, D); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import approvals, studio_chat
import test_video as tv

SECRET = "sk-test-SECRET-key-123"
approvals.PIN_FILE = os.path.join(tv.TMP, "pin.json")
salt = b"saltsalt"
json.dump({"salt": salt.hex(), "iterations": 1000, "hash": hashlib.pbkdf2_hmac("sha256", b"4321", salt, 1000).hex()}, open(approvals.PIN_FILE, "w"))
PORT = approvals.PORT
T = "/approvals/studio"


class Stub:
    """llama-swap stand-in for /v1/chat/completions. mode: normal | slow (never ends) | http500 (error body echoes the key) | cut (closes without [DONE])."""
    def __init__(self):
        me = self; self.mode = "normal"; self.reqs = []; self.disconnects = 0; self.started = threading.Event(); self.port = tv.free_port()

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *a): pass
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n) or b"{}")
                me.reqs.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
                if me.mode == "http500":
                    b = json.dumps({"error": "boom " + SECRET}).encode()
                    self.send_response(500); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
                self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Connection", "close"); self.end_headers()
                self.close_connection = True

                def w(o):
                    self.wfile.write(("data: %s\n\n" % (o if isinstance(o, str) else json.dumps(o))).encode()); self.wfile.flush()
                try:
                    me.started.set()
                    if me.mode == "slow":
                        i = 0
                        while i < 600:
                            w({"choices": [{"index": 0, "delta": {"content": "tick%d " % i}}]}); i += 1; time.sleep(0.05)
                        return
                    w({"choices": [{"index": 0, "delta": {"role": "assistant"}}]})
                    w({"choices": [{"index": 0, "delta": {"reasoning_content": "Let me "}}]})
                    w({"choices": [{"index": 0, "delta": {"reasoning_content": "think."}}]})
                    w({"choices": [{"index": 0, "delta": {"content": "Hello "}}]})
                    w({"choices": [{"index": 0, "delta": {"content": "world"}}]})
                    if me.mode == "cut":
                        return
                    w({"choices": [{"index": 0, "delta": {}, "finish_reason": "length" if body.get("max_tokens") == 7 else "stop"}],
                       "timings": {"prompt_n": 12, "prompt_ms": 10.5, "prompt_per_second": 1142.8, "predicted_n": 5, "predicted_ms": 250.0, "predicted_per_second": 20.0, "draft_n": 8, "draft_n_accepted": 6}})
                    w({"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}})
                    w("[DONE]")
                except (BrokenPipeError, ConnectionResetError, OSError):
                    me.disconnects += 1
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), H); self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


stub = Stub()
rig = tv.Rig(quiet_s=0)
vc = rig.q.cfg
vc.model_id = "qwen-test"
vc.swap_url = "http://127.0.0.1:%d" % stub.port
keyf = os.path.join(rig.t, "key.txt"); open(keyf, "w").write(SECRET + "\n"); vc.api_key_file = keyf
studio_chat.register(approvals, {"video": rig.cfgd}, rig.q)
approvals.attach(state_dir=rig.t, kill=rig.kill)
approvals.start(); time.sleep(0.3)
r = None


def call(method, path, body=None, cookie=None, raw=None, xrw=True):
    h = {}
    if xrw: h["X-Requested-With"] = "approvals"
    if cookie: h["Cookie"] = cookie
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if data is not None: h["Content-Type"] = "application/json"
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)
    c.request(method, path, data, h); resp = c.getresponse(); b = resp.read(); c.close()
    return resp.status, b, resp


_lg = call("POST", "/approvals/login", {"pin": "4321"}); assert _lg[0] == 200, _lg
cookie = _lg[2].getheader("Set-Cookie").split(";")[0]
URL = T + "/api/chat"
ASK = {"preset": "code", "messages": [{"role": "user", "content": "hi"}]}
ALL = []                     # every body seen by the browser side, for the key check


def events(b):
    out = []
    for blk in b.decode().split("\n\n"):
        ev = dat = None
        for ln in blk.split("\n"):
            if ln.startswith("event: "): ev = ln[7:]
            elif ln.startswith("data: "): dat = json.loads(ln[6:])
        if ev: out.append((ev, dat))
    return out


def chat(body, **kw):
    s, b, h = call("POST", URL, body, cookie, **kw); ALL.append(b); return s, b, h


def wait(pred, secs=5):
    end = time.time() + secs
    while time.time() < end:
        if pred(): return True
        time.sleep(0.05)
    return False


def test_auth_and_csrf():
    assert call("POST", URL, ASK)[0] == 401
    assert call("POST", URL, ASK, cookie, xrw=False)[0] == 403
    assert "POST " + URL in approvals._extra_ts and "GET " + T + "/code.js" in approvals._extra_ts      # reachable by the Tailscale-identity tier


def test_event_translation():
    stub.mode = "normal"; n = len(stub.reqs)
    s, b, h = chat(ASK)
    assert s == 200 and h.getheader("Content-Type").startswith("text/event-stream"), (s, b)
    ev = events(b)
    names = [e for e, _ in ev]
    assert names == ["think", "think", "delta", "delta", "usage", "timings", "done"], names
    assert "".join(d["text"] for e, d in ev if e == "think") == "Let me think."
    assert "".join(d["text"] for e, d in ev if e == "delta") == "Hello world"
    assert dict(ev[-3:-2])["usage"] == {"prompt_tokens": 12, "completion_tokens": 5}
    assert dict(ev[-2:-1])["timings"] == {"prompt_ms": 10.5, "prompt_per_s": 1142.8, "predicted_ms": 250.0, "predicted_per_s": 20.0, "draft_n": 8, "draft_accepted": 6}
    assert ev[-1] == ("done", {"finish_reason": "stop"})
    q = stub.reqs[n]
    assert q["path"] == "/v1/chat/completions" and q["body"]["stream"] is True and q["body"]["stream_options"] == {"include_usage": True}
    assert q["body"]["model"] == "qwen-test:code" and q["auth"] == "Bearer " + SECRET
    assert wait(lambda: chat(ASK)[0] == 200)                              # the slot is free again after the stream ends


def test_finish_length_and_cap():
    n = len(stub.reqs)
    s, b, _ = chat(dict(ASK, max_tokens=7)); assert events(b)[-1] == ("done", {"finish_reason": "length"}), b
    chat(dict(ASK, max_tokens=999999)); assert stub.reqs[-1]["body"]["max_tokens"] == 8192
    chat(dict(ASK, max_tokens=0)); assert stub.reqs[-1]["body"]["max_tokens"] == 2048                 # unset/zero: the default
    chat(dict(ASK, temperature=9)); assert stub.reqs[-1]["body"]["temperature"] == 2.0
    chat(ASK); assert "temperature" not in stub.reqs[-1]["body"]
    assert chat(dict(ASK, max_tokens="x"))[0] == 400 and chat(dict(ASK, temperature="hot"))[0] == 400
    assert len(stub.reqs) > n


def test_preset_allowlist():
    n = len(stub.reqs)
    for bad in (None, "", "think", "code:plan", "../x", "CODE", 7, ["code"]):
        s, b, _ = chat(dict(ASK, preset=bad)); assert s == 400, (bad, s)
    chat(dict(ASK, preset="plan")); assert stub.reqs[-1]["body"]["model"] == "qwen-test:plan"
    assert len(stub.reqs) == n + 1                                                                  # rejected presets never reached the upstream


def test_message_validation_and_caps():
    n = len(stub.reqs)
    for bad in (None, [], "hi", [{"role": "user"}], [{"role": "tool", "content": "x"}], [{"role": "assistant", "content": "x"}], ["x"], [{"role": "user", "content": 5}]):
        assert chat(dict(ASK, messages=bad))[0] == 400, bad
    assert chat(dict(ASK, context_files="x"))[0] == 400 and chat(dict(ASK, context_files=[{"name": "a"}]))[0] == 400
    assert chat(dict(ASK, context_files=[{"name": "a", "text": "x"}] * 9))[0] == 400
    big = "a" * (256 * 1024 + 1)
    assert chat(dict(ASK, messages=[{"role": "user", "content": big}]))[0] == 413
    half = "b" * (130 * 1024)
    assert chat(dict(ASK, messages=[{"role": "user", "content": half}], context_files=[{"name": "f", "text": half}]))[0] == 413     # the total counts, not each part
    s, _, _ = chat(dict(ASK, messages=[{"role": "user", "content": "c" * (250 * 1024)}])); assert s == 200       # above the old 16 KB body cap, under 256 KB
    assert len(stub.reqs) == n + 1


def test_context_files_fenced():
    chat(dict(ASK, messages=[{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}, {"role": "user", "content": "Explain"}],
              context_files=[{"name": "x.py", "text": "print(1)\n"}, {"name": "ev`il\nname", "text": "has ``` inside"}]))
    ms = stub.reqs[-1]["body"]["messages"]
    assert len(ms) == 3 and ms[0]["content"] == "q1" and ms[1]["content"] == "a1"
    c = ms[2]["content"]
    assert "File: x.py\n```\nprint(1)\n\n```" in c and c.endswith("Explain"), c
    assert "````\nhas ``` inside\n````" in c and "File: ev il name\n" in c, c                   # fence grows past any backtick run; the name cannot break out


def test_paused_409():
    n = len(stub.reqs)
    open(rig.mode_file, "w").write("OFF\n")
    try:
        s, b, _ = chat(ASK); d = json.loads(b); assert s == 409 and d["reason"] == "paused" and d["error"], (s, b)
    finally:
        open(rig.mode_file, "w").write("MAX\n")
    open(rig.q.lock_path, "w").write("x")                                                           # ComfyUI / a render holds the GPU
    try:
        assert chat(ASK)[0] == 409
    finally:
        os.remove(rig.q.lock_path)
    assert len(stub.reqs) == n and chat(ASK)[0] == 200


def test_busy_429_and_disconnect_closes_upstream():
    stub.mode = "slow"; stub.started.clear(); d0 = stub.disconnects
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    c.request("POST", URL, json.dumps(ASK), {"X-Requested-With": "approvals", "Cookie": cookie, "Content-Type": "application/json"})
    r1 = c.getresponse(); assert r1.status == 200
    got = b""
    while b"tick1 " not in got: got += r1.fp.readline()
    s, b, _ = chat(ASK); d = json.loads(b); ALL.append(b)
    assert s == 429 and d["reason"] == "busy" and d["retry_after"] == 5, (s, b)
    r1.close(); c.close()                                                                                       # the browser goes away mid-generation
    assert wait(lambda: stub.disconnects > d0, 8), "the upstream connection was not closed"
    stub.mode = "normal"
    assert wait(lambda: chat(ASK)[0] == 200, 8), "the busy slot was not released"


def test_upstream_errors():
    stub.mode = "http500"; s, b, _ = chat(ASK); assert s == 502 and json.loads(b)["error"] and SECRET not in b.decode(), (s, b)
    stub.mode = "cut"; s, b, _ = chat(ASK); ev = events(b)
    assert s == 200 and [e for e, _ in ev][-2:] == ["error", "done"] and ev[-1][1]["finish_reason"] == "error" and ev[-1][1]["error"], ev
    assert ("delta", {"text": "world"}) in ev
    stub.mode = "normal"
    p = stub.port; vc.swap_url = "http://127.0.0.1:%d" % tv.free_port()                             # nothing listens there
    try:
        s, b, _ = chat(ASK); assert s == 502 and json.loads(b) == {"error": "the language model did not answer"}
    finally:
        vc.swap_url = "http://127.0.0.1:%d" % p
    assert chat(ASK)[0] == 200                                                                      # and the slot was released on every failure path


def test_key_never_in_output():
    assert stub.reqs and all(r["auth"] == "Bearer " + SECRET for r in stub.reqs)
    assert ALL and not any(SECRET.encode() in b for b in ALL)
    s, b, h = call("GET", T + "/code.js")
    assert SECRET not in b.decode() and SECRET not in str(h.getheaders())


def test_code_js_served():
    s, b, h = call("GET", T + "/code.js")
    assert s == 200 and h.getheader("Content-Type").startswith("application/javascript") and h.getheader("Cache-Control") in ("no-store", "no-cache")
    assert b"export function mount" in b and b"innerHTML" not in b.replace(b"never innerHTML", b"")


def test_ts_tier_and_unconfigured():
    assert "POST " + URL in approvals._extra
    assert studio_chat.register(approvals, {}, None) == {}                                          # no video.llm config: nothing registered


if __name__ == "__main__":
    fails = 0
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            try: f(); print("ok   ", n)
            except Exception: fails += 1; print("FAIL ", n); traceback.print_exc()
    rig.close()
    print("%d failed" % fails); sys.exit(1 if fails else 0)
