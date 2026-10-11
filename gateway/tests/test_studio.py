"""Studio tests: the real approvals server with the Studio routes, a mock llama-swap and a mock ComfyUI. Run: python tests/test_studio.py"""
import hashlib, json, os, sys, tempfile, time, traceback, urllib.request, urllib.error
os.environ["GW_APPROVAL_PORT"] = "18096"
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, D); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import approvals, studio, video
import test_video as tv

approvals.PIN_FILE = os.path.join(tv.TMP, "pin.json")
salt = b"saltsalt"
json.dump({"salt": salt.hex(), "iterations": 1000, "hash": hashlib.pbkdf2_hmac("sha256", b"4321", salt, 1000).hex()}, open(approvals.PIN_FILE, "w"))
B = "http://127.0.0.1:18096"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64


class AssistEnv(video.Env):
    """Real http for everything except the chat call, which answers like Qwen would (with a think block to be stripped)."""
    def __init__(self): self.chats = []
    def http(self, method, url, body=None, headers=None, timeout=10):
        if url.endswith("/v1/chat/completions"):
            self.chats.append(body)
            return {"choices": [{"message": {"content": "<think>hmm</think>A slow dolly toward a red fox in snow at dawn."}}]}
        return super().http(method, url, body, headers, timeout)


def call(method, path, body=None, cookie=None, raw=None, headers=None, xrw=True):
    h = dict(headers or {})
    if xrw: h["X-Requested-With"] = "approvals"
    if cookie: h["Cookie"] = cookie
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if raw is None and body is not None: h["Content-Type"] = "application/json"
    req = urllib.request.Request(B + path, data=data, headers=h, method=method)
    try:
        r = urllib.request.urlopen(req); return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def js(t): return json.loads(t[1].decode())


rig = tv.Rig(quiet_s=0)
env = AssistEnv()
vc = rig.q.cfg
vc.model_id = "m"
studio.register(approvals, rig.q, vc, D, env)
approvals.attach(state_dir=rig.t, kill=rig.kill)
approvals.start(); time.sleep(0.3)
T = "/approvals/studio"
st, ck, _ = None, None, None
r = call("POST", "/approvals/login", {"pin": "4321"})
assert r[0] == 200, r
cookie = r[2].get("Set-Cookie").split(";")[0]


def test_shell_public_api_private():
    s, body, h = call("GET", T)
    assert s == 200 and b"<title>Studio</title>" in body and "text/html" in h["Content-Type"], s
    assert call("GET", T + "/")[0] == 200
    for p in ("/api/workflows", "/api/jobs", "/api/status", "/api/clip/abcdef12/x.mp4"):
        assert call("GET", T + p)[0] == 401, p
    for p in ("generate", "cancel", "delete", "upload", "assist"):
        assert call("POST", T + "/api/" + p, {})[0] == 401, p
        assert call("POST", T + "/api/" + p, {}, cookie, xrw=False)[0] == 403, p       # the CSRF header is still required


def test_workflows_and_status():
    w = js(call("GET", T + "/api/workflows", cookie=cookie))
    assert w["enabled"] and w["workflows"][0]["name"] == "t2v" and w["workflows"][0]["params"]["prompt"]["required"]
    s = js(call("GET", T + "/api/status", cookie=cookie))
    assert s["gpu"] in ("llm", "video") and s["llm"] in ("loaded", "unloaded") and s["queued"] == 0 and s["enabled"], s


def test_upload_rules():
    assert call("POST", T + "/api/upload", cookie=cookie, raw=b"")[0] == 400
    assert call("POST", T + "/api/upload", cookie=cookie, raw=b"GIF89a....")[0] == 415
    assert call("POST", T + "/api/upload", cookie=cookie, raw=b"x" * (studio.MAX_UPLOAD + 100))[0] == 413
    d = js(call("POST", T + "/api/upload", cookie=cookie, raw=PNG))
    assert studio.UP_OK.match(d["name"]), d
    assert os.path.isfile(os.path.join(rig.q.dir, "uploads", d["name"]))


def test_generate_validation():
    g = lambda params: call("POST", T + "/api/generate", {"workflow": "t2v", "params": params}, cookie)
    s, b, _ = g({"prompt": "x", "image": "/etc/passwd"}); assert s == 400 and b"uploaded" in b          # a browser cannot name a server path
    s, b, _ = g({"prompt": "x", "image": "../../x.png"}); assert s == 400
    s, b, _ = g({}); assert s == 400 and b"prompt is required" in b
    s, b, _ = g({"prompt": "x", "bogus": 1}); assert s == 400 and b"does not take" in b
    assert call("POST", T + "/api/generate", {"workflow": "nope", "params": {"prompt": "x"}}, cookie)[0] == 400
    assert call("POST", T + "/api/generate", {"workflow": "t2v", "params": "x"}, cookie)[0] == 400


def test_full_job_clip_delete():
    up = js(call("POST", T + "/api/upload", cookie=cookie, raw=PNG))["name"]
    d = js(call("POST", T + "/api/generate", {"workflow": "t2v", "params": {"prompt": "a fox", "seconds": 2, "image": up}}, cookie))
    jid = d["id"]; assert d["position"] == 1
    j = rig.wait(jid, ("done", "failed"))
    assert j["state"] == "done", j
    jobs = js(call("GET", T + "/api/jobs", cookie=cookie))
    pj = next(x for x in jobs if x["id"] == jid)
    assert pj["state"] == "done" and pj["clips"][0]["type"] == "video/mp4" and pj["has_image"]
    assert "files_out" not in pj and "files" not in pj and rig.t not in json.dumps(pj), pj          # no server paths reach the browser
    name = pj["clips"][0]["name"]; u = "%s/api/clip/%s/%s" % (T, jid, name)
    s, body, h = call("GET", u, cookie=cookie)
    assert s == 200 and body == b"FAKEMP4DATA" and h["Accept-Ranges"] == "bytes" and h["Content-Type"] == "video/mp4"
    s, body, h = call("GET", u, cookie=cookie, headers={"Range": "bytes=2-5"})
    assert s == 206 and body == b"KEMP" and h["Content-Range"] == "bytes 2-5/11", (s, body, h["Content-Range"])
    s, _, h = call("GET", u + "?dl=1", cookie=cookie); assert "attachment" in h["Content-Disposition"]
    for bad in ("%2e%2e%2fjobs.json", "..%2f..%2fpin.json", "a%5cb.mp4", "nothere.mp4"):
        assert call("GET", "%s/api/clip/%s/%s" % (T, jid, bad), cookie=cookie)[0] in (400, 404), bad
    assert call("GET", "%s/api/clip/%s/x.mp4" % (T, "zzzzzzzz"), cookie=cookie)[0] in (400, 404)
    for _ in range(100):                                                                               # the queue restores the mode just after it marks the job done
        if rig.mode() == "MAX": break
        time.sleep(0.1)
    assert rig.mode() == "MAX"                                                                         # the governor mode came back
    s, b, _ = call("POST", T + "/api/delete", {"id": jid}, cookie); assert s == 200, b
    assert call("GET", u, cookie=cookie)[0] == 404 and rig.q.get(jid) is None


def test_mode_refused_while_render_holds_gpu():
    lock = rig.q.lock_path; open(lock, "w").write("{}")
    try:
        for path, body in (("/approvals/mode", {"mode": "LEAN"}), ("/approvals/model", {"action": "load"})):
            s, b, _ = call("POST", path, body, cookie); assert s == 409 and "has the GPU" in b.decode(), (path, s, b)
    finally: os.remove(lock)
    s, b, _ = call("POST", "/approvals/mode", {"mode": "bogus"}, cookie); assert s == 400


def test_cancel_and_delete_guard():
    rig2 = tv.Rig(mode="slow", quiet_s=0)
    try:
        q = rig2.q; q.cfg.allowed_roots = list(q.cfg.allowed_roots)
        jid, _, _ = q.submit("t2v", {"prompt": "slow"})
        rig2.wait(jid, ("running",))
        ok, msg = q.delete_job(jid); assert not ok and "cancel" in msg
        q.cancel_job(jid); j = rig2.wait(jid, ("cancelled",)); assert j["state"] == "cancelled"
        ok, msg = q.delete_job(jid); assert ok
        ok, msg = q.delete_job("deadbeef"); assert not ok
    finally: rig2.close()


def test_assist():
    s, b, _ = call("POST", T + "/api/assist", {"idea": "  "}, cookie); assert s == 400
    d = js(call("POST", T + "/api/assist", {"idea": "fox in snow"}, cookie))
    assert d["prompt"] == "A slow dolly toward a red fox in snow at dawn." and "<think>" not in d["prompt"]
    c = env.chats[-1]; assert c["model"] == "m" and c["messages"][1]["content"] == "fox in snow" and c["reasoning_effort"] == "low"
    # refuse while the GPU belongs to a render: the helper would pull the LLM back in
    rig3 = tv.Rig(mode="slow", quiet_s=0)
    try:
        jid, _, _ = rig3.q.submit("t2v", {"prompt": "slow"}); rig3.wait(jid, ("running",))
        with rig.q.lock: rig.q.jobs.append(dict(id="aaaaaaaa", workflow="t2v", params={}, files={}, state="running", created=time.time()))
        s, b, _ = call("POST", T + "/api/assist", {"idea": "x"}, cookie); assert s == 409, (s, b)
        with rig.q.lock: rig.q.jobs[:] = [x for x in rig.q.jobs if x["id"] != "aaaaaaaa"]
        rig3.q.cancel_job(jid); rig3.wait(jid, ("cancelled",))
    finally: rig3.close()


def test_assist_modes():
    ask = lambda body: js(call("POST", T + "/api/assist", dict({"idea": "fox in snow"}, **body), cookie))
    sys_of = lambda: env.chats[-1]["messages"][0]["content"]
    d = ask({}); assert d["mode"] == "single" and "MULTI-SHOT" not in sys_of() and "CONTINUE:" not in sys_of()
    assert "flowing paragraph" in sys_of() and "present tense" in sys_of() and "no lists" in sys_of()          # the LTX guide's core rules
    d = ask({"mode": "multi"}); assert d["mode"] == "multi" and "MULTI-SHOT" in sys_of() and "re-identify" in sys_of() and "Do not number" in sys_of()
    assert env.chats[-1]["max_tokens"] > 700                                                                    # room for 2-4 shots
    d = ask({"mode": "continue"}); assert d["mode"] == "continue" and "CONTINUE:" in sys_of() and "what happens next" in sys_of()
    assert env.chats[-1]["messages"][1]["content"] == "fox in snow"                                              # the user's words go through untouched
    for bad in ("MULTI", "everything", "", None, 7, ["multi"], {"a": 1}):
        assert ask({"mode": bad})["mode"] == "single", bad                                                       # unknown or malformed -> single
    assert studio.assist_mode("multi") == "multi" and studio.assist_mode(None) == "single"
    # dialogue quotes survive; a wrapping pair of quotes does not
    class Q(AssistEnv):
        reply = ""
        def http(self, method, url, body=None, headers=None, timeout=10):
            if url.endswith("/v1/chat/completions"): return {"choices": [{"message": {"content": self.reply}}]}
            return video.Env.http(self, method, url, body, headers, timeout)
    qe = Q(); old = vc.model_id
    t2 = studio.routes(rig.q, vc, D, qe)[0]["POST /approvals/studio/api/assist"]
    run = lambda reply: (setattr(qe, "reply", reply), json.loads(t2({"body": {"idea": "x"}, "authed": True})[1])["prompt"])[1]
    assert run('"A woman smiles."') == "A woman smiles."                                                         # a wrapper is removed
    assert run('A woman says, "Welcome home."') == 'A woman says, "Welcome home."'                             # a closing quote of dialogue is not
    assert run('"Hi," she says, "bye."') == '"Hi," she says, "bye."'


def test_assist_audio_follows_workflow():
    wf = json.loads(json.dumps(tv.WF)); wf["meta"]["audio"] = False
    path = os.path.join(rig.t, "wf", "silent.json"); json.dump(wf, open(path, "w"))
    try:
        js(call("POST", T + "/api/assist", {"idea": "x", "workflow": "silent"}, cookie)); assert "no audio" in env.chats[-1]["messages"][0]["content"]
        wf["meta"]["audio"] = True; json.dump(wf, open(path, "w"))
        js(call("POST", T + "/api/assist", {"idea": "x", "workflow": "silent"}, cookie)); c = env.chats[-1]["messages"][0]["content"]; assert "double quotes" in c and "no audio" not in c
        js(call("POST", T + "/api/assist", {"idea": "x", "workflow": "nope"}, cookie)); assert "double quotes" in env.chats[-1]["messages"][0]["content"]   # unknown -> sound on
    finally: os.remove(path)


def test_assist_still_blocked_while_rendering():
    with rig.q.lock: rig.q.jobs.append(dict(id="cccccccc", workflow="t2v", params={}, files={}, state="starting", created=time.time()))
    try:
        n = len(env.chats)
        for mode in ("single", "multi", "continue", "bogus"):
            s, b, _ = call("POST", T + "/api/assist", {"idea": "x", "mode": mode}, cookie); assert s == 409, (mode, s)
        assert len(env.chats) == n                                                                                 # the LLM was never called
    finally:
        with rig.q.lock: rig.q.jobs[:] = [x for x in rig.q.jobs if x["id"] != "cccccccc"]


def test_presets_exposed():
    wf = json.loads(json.dumps(tv.WF)); m = wf["meta"]
    m["order"] = 200; m["sizes"] = [[768, 512, "Draft"], [704, 1280, "Vertical"]]
    m["presets"] = [{"name": "Draft Fast!", "label": "Draft fast", "hint": "quick look", "params": {"size": "Draft", "seconds": 2, "negative": "ugly", "prompt": "no", "image": "/etc/passwd", "seed": 1, "bogus": 1}},
                    {"label": "Vertical", "params": {"size": 1, "width": 704, "height": 1280, "workflow": "t2v"}},
                    {"label": "No params"}, {"params": {"size": 0}}, "junk", {"label": "Nested", "params": {"negative": {"a": 1}}}]
    path = os.path.join(rig.t, "wf", "pre.json"); json.dump(wf, open(path, "w"))
    try:
        ws = {w["name"]: w for w in js(call("GET", T + "/api/workflows", cookie=cookie))["workflows"]}
        assert ws["t2v"]["presets"] == [] and ws["t2v"]["frames_rule"] == "8n+1"                                   # no presets -> empty list, the UI falls back to size chips
        pr = ws["pre"]["presets"]; assert [p["label"] for p in pr] == ["Draft fast", "Vertical"], pr
        assert pr[0] == {"name": "draft-fast-", "label": "Draft fast", "hint": "quick look", "params": {"size": "Draft", "seconds": 2, "negative": "ugly"}}, pr[0]
        assert pr[1]["params"] == {"size": 1, "width": 704, "height": 1280, "workflow": "t2v"} and pr[1]["hint"] == ""
        assert ws["pre"]["sizes"][1][2] == "Vertical"
    finally: os.remove(path)
    assert studio.clean_presets("x", {}) == [] and studio.clean_presets(None, {}) == []
    assert len(studio.clean_presets([{"label": str(i), "params": {"size": 0}} for i in range(20)], {})) == 8


def test_status_while_rendering():
    with rig.q.lock: rig.q.jobs.append(dict(id="bbbbbbbb", workflow="t2v", params={"prompt": "p"}, files={}, state="running", created=time.time(), started=time.time()))
    try:
        s = js(call("GET", T + "/api/status", cookie=cookie))
        assert s["gpu"] == "video" and s["active"]["id"] == "bbbbbbbb"
    finally:
        with rig.q.lock: rig.q.jobs[:] = [x for x in rig.q.jobs if x["id"] != "bbbbbbbb"]


if __name__ == "__main__":
    fails = 0
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            try: f(); print("ok   ", n)
            except Exception: fails += 1; print("FAIL ", n); traceback.print_exc()
    rig.close()
    print("%d failed" % fails); sys.exit(1 if fails else 0)
