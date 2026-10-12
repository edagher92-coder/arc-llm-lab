"""ask_local tests (tools_local_llm.py): fake HTTP layer plus one real 127.0.0.1 stub server; no outside network.
Run: python -m pytest tests/test_local_llm.py -q"""
import io, json, os, socket, sys, tempfile, threading, urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, D)
import video, tools_local_llm as tl, tools_video_mcp as tv

TMP = tempfile.mkdtemp(prefix="localllm-")
KEY = "sk-SECRET-KEY-123"


class FakeServer:
    def __init__(self): self.tools = {}
    def tool(self, name, description=""):
        def deco(f): self.tools[name] = (f, description); return f
        return deco


def cfg_dict(mode="MAX", swap="http://127.0.0.1:1"):
    mf, kf = os.path.join(TMP, "mode.txt"), os.path.join(TMP, "key.txt")
    open(mf, "w").write(mode); open(kf, "w").write(KEY + "\n")
    return {"video": {"comfy_dir": TMP, "comfy_cmd": ["x"], "llm": {"swap_url": swap, "api_key_file": kf, "model_id": "qwen3.8-27b", "governor_mode_file": mf}}}


class FakeQueue:
    def __init__(self, cfg, busy=False):
        self.cfg = video.Cfg(cfg["video"], TMP); self._busy = busy
    def busy(self): return self._busy
    def session_info(self): return {"active": False}
    def mode_get(self): return {"view": "llm"}


def rig(mode="MAX", busy=False, swap="http://127.0.0.1:1"):
    c = cfg_dict(mode, swap); s = FakeServer()
    tl.register(s, FakeQueue(c, busy), D, c)
    return s.tools["ask_local"][0], s


def fake_http(calls, reply=None, exc=None):
    def f(url, body, headers, timeout):
        calls.append((url, body, headers, timeout))
        if exc: raise exc
        return 200, reply or {"choices": [{"message": {"content": "hello draft"}}]}
    return f


def run(fn, *a, **k):
    return json.loads(fn(*a, **k))


def test_ok_path_and_request_shape():
    fn, s = rig(); calls = []; real, tl._http = tl._http, fake_http(calls)
    try:
        r = run(fn, "Summarise: the cat sat.", "summarise", "be brief", 99999, 1)
    finally:
        tl._http = real
    assert r["ok"] and r["status"] == "ok" and r["text"] == "hello draft" and r["model"] == "qwen3.8-27b:code" and "elapsed_ms" in r
    url, body, headers, to = calls[0]
    assert url == "http://127.0.0.1:1/v1/chat/completions" and body["max_tokens"] == 4096 and to == 5 and body["temperature"] == 0.2
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert headers["Authorization"] == "Bearer " + KEY
    assert KEY not in json.dumps(r)
    assert "DRAFT" in s.tools["ask_local"][1] and "NEVER" in s.tools["ask_local"][1]


def test_paused_when_mode_off_and_no_call():
    fn, _ = rig(mode="OFF"); calls = []; real, tl._http = tl._http, fake_http(calls)
    try:
        r = run(fn, "summarise this note")
    finally:
        tl._http = real
    assert r["status"] == "paused" and not r["ok"] and r["note"] == tl.PAUSED_NOTE and calls == []


def test_paused_when_video_job_holds_gpu():
    fn, _ = rig(busy=True)
    assert run(fn, "summarise this note")["status"] == "paused"


def test_refused_bad_task_and_stakes():
    fn, _ = rig(); calls = []; real, tl._http = tl._http, fake_http(calls)
    try:
        assert run(fn, "hi", "poetry")["status"] == "refused"
        for p in ("what is the price of the machine", "Write a quote for 5 units", "draft an invoice", "refund them $50", "total is 120 AUD", "add GST", "legal advice", "review this contract", "tax return", "cost 20$"):
            assert run(fn, p)["status"] == "refused", p
        assert run(fn, "Summarise the meeting about the pricing page", "summarise")["status"] == "refused"
        assert run(fn, "")["status"] == "refused"
    finally:
        tl._http = real
    assert calls == []


def test_timeout_and_error_mapping_no_key_leak():
    fn, _ = rig()
    real = tl._http
    try:
        tl._http = fake_http([], exc=socket.timeout("timed out"))
        assert run(fn, "hello there")["status"] == "timeout"
        tl._http = fake_http([], exc=urllib.error.URLError(socket.timeout("t")))
        assert run(fn, "hello there")["status"] == "timeout"
        tl._http = fake_http([], exc=urllib.error.HTTPError("u", 503, "x " + KEY, {}, io.BytesIO(b"")))
        r = run(fn, "hello there"); assert r["status"] == "busy" and "503" in r["note"]
        tl._http = fake_http([], exc=ConnectionRefusedError(KEY))
        s = fn("hello there"); assert json.loads(s)["status"] == "error" and json.loads(s)["note"] == "ConnectionRefusedError" and KEY not in s
        tl._http = fake_http([], reply={"nope": 1})
        assert run(fn, "hello there")["status"] == "error"
        tl._http = fake_http([], reply={"choices": [{"message": {"content": "x" * 30000}}]})
        r = run(fn, "hello there"); assert len(r["text"]) == 20000 and "truncated" in r["note"]
    finally:
        tl._http = real


def test_real_stub_server_and_key_not_logged(capsys):
    seen = {}
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["auth"] = self.headers.get("Authorization"); seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            b = json.dumps({"choices": [{"message": {"content": "from stub"}}]}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        def log_message(self, *a): pass
    srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        fn, _ = rig(swap="http://127.0.0.1:%d" % srv.server_port)
        r = run(fn, "classify this", "classify")
    finally:
        srv.shutdown()
    assert r["text"] == "from stub" and seen["auth"] == "Bearer " + KEY and seen["body"]["model"] == "qwen3.8-27b:code"
    cap = capsys.readouterr(); assert KEY not in cap.out + cap.err


def test_noop_without_video_config():
    s = FakeServer(); tl.register(s, None, D, {"name": "gw"}); assert not s.tools


def test_build_hook_registers_ask_local():
    """gateway.build() must call tools_local_llm.register: deleting that hook fails this test."""
    if "gateway" not in sys.modules:
        cf = os.path.join(TMP, "gw.json"); json.dump({"name": "gw", "servers": {}}, open(cf, "w")); sys.argv = ["gateway.py", cf]
        os.environ.setdefault("GW_STATE_DIR", os.path.join(TMP, "state"))
    import gateway
    import tools_local_llm as lmod     # the module gateway.build() imports (another test file may have re-imported it)
    seen = []; real = lmod.register
    lmod.register = lambda srv, q, base, cfg=None: seen.append((srv, q, base, cfg))
    try:
        gateway.build()
    finally:
        lmod.register = real
    assert len(seen) == 1 and seen[0][2] == gateway.HERE and seen[0][3] is gateway.CFG


def test_code_and_review_tasks_get_an_engineer_system_prompt():
    fn, s = rig(); calls = []; real, tl._http = tl._http, fake_http(calls)
    try:
        a = run(fn, "Write is_8n1(n).", "code")
        b = run(fn, "Review: def f(x): return x/0", "review", "custom reviewer")
        c = run(fn, "summarise this note", "summarise")
    finally:
        tl._http = real
    assert a["ok"] and b["ok"] and c["ok"]
    sysmsg = lambda i: [m for m in calls[i][1]["messages"] if m["role"] == "system"]
    assert "senior engineer" in sysmsg(0)[0]["content"] and sysmsg(1)[0]["content"] == "custom reviewer" and sysmsg(2) == []
    assert run(fn, "Write the invoice total function for GST", "code")["status"] == "refused"      # the stakes filter still applies to code tasks
