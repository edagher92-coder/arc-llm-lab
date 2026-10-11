"""Studio tests: the real approvals server with the Studio routes, a mock llama-swap and a mock ComfyUI. Run: python tests/test_studio.py"""
import hashlib, json, os, re, sys, tempfile, time, traceback, urllib.request, urllib.error
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
    for p in ("/api/workflows", "/api/jobs", "/api/status", "/api/system", "/api/clip/abcdef12/x.mp4"):
        assert call("GET", T + p)[0] == 401, p
    for p in ("generate", "cancel", "delete", "upload", "assist", "fav", "rerun", "mode"):
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


def _png_size(b):
    assert b[:8] == b"\x89PNG\r\n\x1a\n" and b[12:16] == b"IHDR", b[:16]
    return int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")


def test_pwa_manifest_and_icons_public_and_data_free():
    s, body, h = call("GET", T + "/manifest.webmanifest")                                  # no cookie: the browser fetches it before sign-in
    assert s == 200 and h["Content-Type"].startswith("application/manifest+json"), (s, h["Content-Type"])
    m = json.loads(body.decode())
    assert m["name"] == "Studio" and m["short_name"] == "Studio" and m["start_url"] == T and m["scope"] == T and m["display"] == "standalone", m
    assert m["background_color"] == "#121316" and m["theme_color"] == "#121316", m
    assert sorted((i["sizes"], i["type"]) for i in m["icons"]) == [("192x192", "image/png"), ("512x512", "image/png")], m["icons"]
    assert set(m) <= {"name", "short_name", "start_url", "scope", "display", "background_color", "theme_color", "icons", "description", "id"}, set(m)
    jid, _, _ = rig.q.submit("t2v", {"prompt": "private prompt xyz"})
    rig.wait(jid, ("done", "failed"))
    blobs = [body]
    for name, px in (("icon-180.png", 180), ("icon-192.png", 192), ("icon-512.png", 512)):
        s, b, h = call("GET", T + "/" + name)
        assert s == 200 and h["Content-Type"] == "image/png" and _png_size(b) == (px, px), (name, s, h["Content-Type"])
        blobs.append(b)
    for b in blobs:
        assert jid.encode() not in b and b"private prompt" not in b and rig.t.encode() not in b      # static: no job data, no server paths
    assert call("GET", T + "/icon-999.png")[0] == 404 and call("GET", T + "/manifest.webmanifest/../x")[0] in (400, 404)


def test_shell_csp_adds_only_manifest_src():
    import re
    s, body, h = call("GET", T)
    csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]*)"', body.decode()).group(1)
    got = {d.strip() for d in csp.split(";") if d.strip()}
    assert got == {"default-src 'none'", "script-src 'unsafe-inline'", "style-src 'unsafe-inline'", "img-src 'self' data: blob:", "media-src 'self' blob:",
                   "connect-src 'self'", "base-uri 'none'", "form-action 'none'", "manifest-src 'self'"}, got
    assert "'unsafe-eval'" not in csp and "script-src 'unsafe-inline'" in csp
    html = body.decode()
    assert 'rel="manifest"' in html and 'rel="apple-touch-icon"' in html and 'name="apple-mobile-web-app-title"' in html
    assert "serviceWorker" not in html


def test_fav_roundtrip_and_validation():
    jid, _, _ = rig.q.submit("t2v", {"prompt": "star me", "seconds": 2}); rig.wait(jid, ("done",))
    f = lambda body, **kw: call("POST", T + "/api/fav", body, cookie, **kw)
    pj = lambda: next(x for x in js(call("GET", T + "/api/jobs", cookie=cookie)) if x["id"] == jid)
    assert pj()["fav"] is False
    s, b, _ = f({"id": jid, "fav": True}); assert s == 200 and json.loads(b) == {"id": jid, "fav": True}, b
    assert pj()["fav"] is True and rig.q.get(jid)["fav"] is True
    for bad in ({"id": jid, "fav": "yes"}, {"id": jid, "fav": 1}, {"id": jid}, {"id": "../x", "fav": True}, {"id": "ABCDEF12", "fav": True}, {"fav": True}):
        assert f(bad)[0] == 400, bad
    assert f({"id": "deadbeef", "fav": True})[0] == 404
    assert call("POST", T + "/api/fav", {"id": jid, "fav": False})[0] == 401                       # no session
    assert f({"id": jid, "fav": False}, xrw=False)[0] == 403                                       # no CSRF header
    assert f({"id": jid, "fav": False})[0] == 200 and pj()["fav"] is False


def test_jobs_list_keeps_old_favourites():
    with rig.q.lock:
        rig.q.jobs.insert(0, dict(id="0a1df400", workflow="t2v", params={"prompt": "old"}, files={}, state="done", created=1.0, fav=True))
        for i in range(45): rig.q.jobs.append(dict(id="%08x" % (0xa0000 + i), workflow="t2v", params={}, files={}, state="done", created=time.time() + i))
    try:
        ids = [x["id"] for x in js(call("GET", T + "/api/jobs", cookie=cookie))]
        assert "0a1df400" in ids and len(ids) == 41, len(ids)                                         # newest 40 plus the starred one that fell out of them
    finally:
        with rig.q.lock: rig.q.jobs[:] = [x for x in rig.q.jobs if x["id"] != "0a1df400" and not (0xa0000 <= int(x["id"], 16) < 0xa0000 + 45)]


def test_rerun_creates_new_validated_job():
    up = js(call("POST", T + "/api/upload", cookie=cookie, raw=PNG))["name"]
    d = js(call("POST", T + "/api/generate", {"workflow": "t2v", "params": {"prompt": "again", "seconds": 2, "seed": 77, "image": up}}, cookie))
    old = rig.wait(d["id"], ("done",))
    r = lambda body, **kw: call("POST", T + "/api/rerun", body, cookie, **kw)
    s, b, _ = r({"id": old["id"]}); assert s == 200, b
    new = json.loads(b); assert new["id"] != old["id"] and re.match(r"^[0-9a-f]{8}$", new["id"]) and new["position"] >= 1, new
    nj = rig.wait(new["id"], ("done",))
    assert nj["workflow"] == "t2v" and nj["params"] == old["params"] and nj["params"]["seed"] == 77 and nj["files"] == old["files"], (nj["params"], old["params"])
    assert not nj.get("fav")                                                                      # a re-run is a new clip, not a copy of the star
    # it goes through resolve_params again (jobs are dicts held in q.jobs, so edit the stored original in place): a value the workflow no longer allows is clamped, an unknown key is refused
    with rig.q.lock: next(x for x in rig.q.jobs if x["id"] == old["id"])["params"]["width"] = 99999
    s, b, _ = r({"id": old["id"]}); assert s == 200, b
    assert rig.wait(json.loads(b)["id"], ("done",))["params"]["width"] == 1280
    with rig.q.lock: next(x for x in rig.q.jobs if x["id"] == old["id"])["params"]["bogus"] = 1
    s, b, _ = r({"id": old["id"]}); assert s == 400 and b"does not take" in b, (s, b)
    for bad in ({}, {"id": 5}, {"id": "../etc"}, {"id": "ABCDEF12"}, {"id": ""}):
        assert r(bad)[0] == 400, bad
    assert r({"id": "deadbeef"})[0] == 404
    assert call("POST", T + "/api/rerun", {"id": old["id"]})[0] == 401 and r({"id": old["id"]}, xrw=False)[0] == 403
    os.remove(os.path.join(rig.q.dir, "uploads", up))                                              # start image deleted since: a clear refusal, no new job
    with rig.q.lock: next(x for x in rig.q.jobs if x["id"] == old["id"])["params"].pop("bogus")
    n = len(rig.q.jobs); s, b, _ = r({"id": old["id"]}); assert s == 400 and len(rig.q.jobs) == n, (s, b)


def test_trim_uploads_skips_favourite_images():
    up_dir = os.path.join(rig.q.dir, "uploads")
    a = js(call("POST", T + "/api/upload", cookie=cookie, raw=PNG))["name"]; b = js(call("POST", T + "/api/upload", cookie=cookie, raw=PNG))["name"]
    ja = rig.wait(rig.q.submit("t2v", {"prompt": "fa", "seconds": 2, "image": os.path.join(up_dir, a)})[0], ("done",))
    rig.wait(rig.q.submit("t2v", {"prompt": "fb", "seconds": 2, "image": os.path.join(up_dir, b)})[0], ("done",))
    assert call("POST", T + "/api/fav", {"id": ja["id"], "fav": True}, cookie)[0] == 200
    for n, age in ((a, 500), (b, 400)): os.utime(os.path.join(up_dir, n), (time.time() - age, time.time() - age))        # the two oldest uploads
    for _ in range(61): assert call("POST", T + "/api/upload", cookie=cookie, raw=PNG)[0] == 200
    assert os.path.exists(os.path.join(up_dir, a)), "the favourite's start image was trimmed"
    assert not os.path.exists(os.path.join(up_dir, b)), "ordinary old uploads should still be trimmed"
    assert len([f for f in os.listdir(up_dir) if studio.UP_OK.match(f)]) <= 61                    # keep=60 plus the one protected image
    assert call("POST", T + "/api/rerun", {"id": ja["id"]}, cookie)[0] == 200                      # so the favourite can still be run again


def test_status_while_rendering():
    with rig.q.lock: rig.q.jobs.append(dict(id="bbbbbbbb", workflow="t2v", params={"prompt": "p"}, files={}, state="running", created=time.time(), started=time.time()))
    try:
        s = js(call("GET", T + "/api/status", cookie=cookie))
        assert s["gpu"] == "video" and s["active"]["id"] == "bbbbbbbb"
    finally:
        with rig.q.lock: rig.q.jobs[:] = [x for x in rig.q.jobs if x["id"] != "bbbbbbbb"]


def test_system_snapshot_shape_cache_and_privacy():
    end = time.time() + 20
    while rig.q.busy() and time.time() < end: time.sleep(0.1)
    time.sleep(2.1)
    s = js(call("GET", T + "/api/system", cookie=cookie))
    assert s["version"] == "studio-v3" and s["mode"] in ("video", "llm") and s["llm_loaded"] in (True, False), s
    assert set(s) >= {"mode", "llm_loaded", "comfy", "queue", "ram", "disk", "vram", "last", "drive", "ntfy", "loudnorm", "version"}, s
    assert s["comfy"]["running"] is False and s["comfy"]["session"] is False and s["comfy"]["idle_s"] is None and "port" in s["comfy"]
    assert s["queue"] == {"len": 0, "running_id": None, "stage": None, "progress": None}, s["queue"]
    assert s["ram"]["total_mb"] >= s["ram"]["avail_mb"] >= 0 and s["disk"]["out_free_gb"] > 0 and s["vram"] is None
    assert s["drive"]["mode"] == "off" and s["drive"]["dir_ok"] is False and s["drive"]["last_path"] is None and s["loudnorm"] is False
    assert rig.t not in json.dumps(s), "a server path reached the browser"
    assert call("GET", T + "/api/system")[0] == 401
    s2 = js(call("GET", T + "/api/system", cookie=cookie)); assert s2 == s, "second call within 2 s should come from the cache"


def test_system_shows_stage_last_speed_and_fails_soft():
    jid, _, _ = rig.q.submit("t2v", {"prompt": "speed", "seconds": 2}); rig.wait(jid, ("done",))
    with rig.q.lock: rig.q.jobs.append(dict(id="dddddddd", workflow="t2v", params={"prompt": "p"}, files={}, state="running", created=time.time(), started=time.time(), note="stage 2 of 2: sampling", progress=55.5))
    try:
        time.sleep(2.1); s = js(call("GET", T + "/api/system", cookie=cookie))
        assert s["mode"] == "busy" and s["queue"]["running_id"] == "dddddddd" and s["queue"]["stage"].startswith("stage 2") and s["queue"]["progress"] == 55.5 and s["queue"]["len"] == 1, s
        assert s["last"]["seconds"] > 0 and s["last"]["out_seconds"] > 0, s["last"]
        orig = studio.host_ram; studio.host_ram = lambda: (_ for _ in ()).throw(RuntimeError("probe broke"))
        try:
            time.sleep(2.1); s = js(call("GET", T + "/api/system", cookie=cookie)); assert "error" in s and s["version"] == "studio-v3"       # a broken probe is an answer, not a 500
        finally: studio.host_ram = orig
    finally:
        with rig.q.lock: rig.q.jobs[:] = [x for x in rig.q.jobs if x["id"] != "dddddddd"]
        time.sleep(2.1)
    assert studio.last_speed([]) is None and studio._out_secs({"params": {"frames": 49}}) == 2.0
    open(os.path.join(rig.t, "mi"), "w").write("MemTotal: 1000 kB\nMemAvailable: 400 kB\n")
    assert studio._meminfo(os.path.join(rig.t, "mi")) == (1024000, 409600)


def test_mode_endpoint():
    m = lambda body, **kw: call("POST", T + "/api/mode", body, cookie, **kw)
    assert call("POST", T + "/api/mode", {"mode": "video"})[0] == 401 and m({"mode": "video"}, xrw=False)[0] == 403
    for bad in ({}, {"mode": "gpu"}, {"mode": 1}, {"mode": None}): assert m(bad)[0] == 400, bad
    orig = rig.q._warm_llm; rig.q._warm_llm = lambda: None
    try:
        s, b, _ = m({"mode": "video"}); d = json.loads(b); assert s == 200 and d == {"ok": True, "mode": "video"} and rig.mode() == "OFF", (s, b)
        time.sleep(2.1); assert js(call("GET", T + "/api/system", cookie=cookie))["mode"] == "video"
        with rig.q.lock: rig.q.jobs.append(dict(id="eeeeeeee", workflow="t2v", params={}, files={}, state="running", created=time.time()))
        try:
            s, b, _ = m({"mode": "llm"}); assert s == 409 and "error" in json.loads(b) and rig.mode() == "OFF", (s, b)       # refused while busy, governor untouched
        finally:
            with rig.q.lock: rig.q.jobs[:] = [x for x in rig.q.jobs if x["id"] != "eeeeeeee"]
        s, b, _ = m({"mode": "llm"}); assert s == 200 and json.loads(b) == {"ok": True, "mode": "llm"} and rig.mode() == "MAX", (s, b)
        mf = rig.q.cfg.mode_file; rig.q.cfg.mode_file = ""
        try: assert m({"mode": "video"})[0] == 503
        finally: rig.q.cfg.mode_file = mf
    finally: rig.q._warm_llm = orig


def test_comfy_session_endpoint():
    c = lambda body, **kw: call("POST", T + "/api/comfy", body, cookie, **kw)
    assert call("POST", T + "/api/comfy", {"action": "start"})[0] == 401 and c({"action": "start"}, xrw=False)[0] == 403
    for bad in ({}, {"action": "restart"}, {"action": 1}): assert c(bad)[0] == 400, bad
    end = time.time() + 20
    while rig.q.busy() and time.time() < end: time.sleep(0.1)
    vc.tailnet_port = 8448
    with rig.q.lock: rig.q.jobs.append(dict(id="ffffffff", workflow="t2v", params={}, files={}, state="running", created=time.time()))
    try:
        s, b, _ = c({"action": "start"}); assert s == 409 and "error" in json.loads(b) and not rig.q.session_info()["active"], (s, b)       # refused while a job runs
    finally:
        with rig.q.lock: rig.q.jobs[:] = [x for x in rig.q.jobs if x["id"] != "ffffffff"]
    try:
        s, b, _ = c({"action": "start"}); assert s == 200 and json.loads(b)["ok"] is True and json.loads(b)["session"] is True, (s, b)
        tv.wait_for(lambda: rig.q.session_info()["state"] == "ready", 20)
        assert c({"action": "start"})[0] == 409                                      # a second start is refused
        s2 = call("POST", T + "/api/mode", {"mode": "llm"}, cookie)
        assert s2[0] == 409, s2                                                      # mode switch refused during a session
        time.sleep(2.1); sysd = js(call("GET", T + "/api/system", cookie=cookie))
        assert sysd["mode"] == "busy" and sysd["comfy"]["session"] is True and sysd["comfy"]["running"] is True and sysd["comfy"]["port"] == 8448 and isinstance(sysd["comfy"]["idle_s"], int), sysd["comfy"]
        assert rig.mode() == "OFF"
    finally:
        s, b, _ = c({"action": "stop"}); assert s == 200 and json.loads(b) == {"ok": True, "session": False}, (s, b)
    assert rig.mode() == "MAX" and not rig.q.session_info()["active"]
    time.sleep(2.1); sysd = js(call("GET", T + "/api/system", cookie=cookie)); assert sysd["comfy"]["session"] is False and sysd["comfy"]["idle_s"] is None and sysd["mode"] == "llm", sysd


def test_system_reports_drive_and_loudnorm_settings():
    old = (vc.drive_dir, vc.drive_mode, vc.loudnorm)
    d = tempfile.mkdtemp(dir=tv.TMP)
    try:
        vc.drive_dir, vc.drive_mode, vc.loudnorm = d, "favourites", True
        time.sleep(2.1); s = js(call("GET", T + "/api/system", cookie=cookie))
        assert s["drive"]["mode"] == "favourites" and s["drive"]["dir_ok"] is True and s["loudnorm"] is True and d not in json.dumps(s), s
        vc.drive_dir = os.path.join(d, "missing")
        time.sleep(2.1); assert js(call("GET", T + "/api/system", cookie=cookie))["drive"]["dir_ok"] is False
    finally:
        vc.drive_dir, vc.drive_mode, vc.loudnorm = old; time.sleep(2.1)


def test_drive_status_in_job_list_is_relative_only():
    jid, _, _ = rig.q.submit("t2v", {"prompt": "d", "seconds": 2}); rig.wait(jid, ("done",))
    rig.q._set(jid, drive_path="/secret/Drive/2026-10/x.mp4", drive_rel="2026-10/x.mp4")
    pj = next(x for x in js(call("GET", T + "/api/jobs", cookie=cookie)) if x["id"] == jid)
    assert pj["drive"] == "2026-10/x.mp4" and "drive_path" not in pj and "/secret" not in json.dumps(pj), pj


def test_workflow_meta_has_est_ref_only_when_valid():
    wf = json.loads(json.dumps(tv.WF)); wf["meta"]["est_ref"] = [768, 512, 2]; wf["meta"]["order"] = 201
    bad = json.loads(json.dumps(tv.WF)); bad["meta"]["est_ref"] = [768, "x", 2]; bad["meta"]["order"] = 202
    for n, w in (("er", wf), ("erbad", bad)): json.dump(w, open(os.path.join(rig.t, "wf", n + ".json"), "w"))
    try:
        ws = {w["name"]: w for w in js(call("GET", T + "/api/workflows", cookie=cookie))["workflows"]}
        assert ws["er"]["est_ref"] == [768.0, 512.0, 2.0] and "est_ref" not in ws["erbad"] and "est_ref" not in ws["t2v"]
    finally:
        for n in ("er", "erbad"): os.remove(os.path.join(rig.t, "wf", n + ".json"))


def _shell_html():
    s, body, h = call("GET", T)
    assert s == 200
    return body.decode()


def test_v3_shell_gpu_mode_switch_wiring():
    html = _shell_html()
    assert 'api("mode"' in html and '{mode: m}' in html and 'role: "radiogroup"' in html and '"Video"' in html and '"Qwen"' in html
    assert "x.status === 409" in html and "A video is rendering; wait or cancel it first" in html          # a refusal is a plain message, not a crash


def test_v3_shell_comfy_session_wiring_and_links():
    html = _shell_html()
    assert 'api("comfy"' in html and '{action}' in html and "Start session" in html and "Stop session" in html
    assert "const COMFY_PORT = 8448" in html
    assert 'comfyUrl("/mobile")' in html and 'comfyUrl("/")' in html and "Open CueForge" in html and "Open ComfyUI" in html
    assert '"https://" + location.hostname + ":"' in html                                                 # host comes from the page, so any tailnet name works
    assert 'target: "_blank"' in html and 'rel: "noopener noreferrer"' in html


def test_v3_shell_system_poll_and_tabs():
    html = _shell_html()
    assert 'api("system")' in html and "visibilitychange" in html and "document.hidden" in html
    for tab in ("create", "queue", "gallery", "system"):
        assert '["%s", ' % tab in html, tab
    assert 'id="v-system"' in html and "Unknown" in html                                                 # missing numbers read as Unknown, never invented


def test_v3_shell_settings_sheet_and_storage_guards():
    html = _shell_html()
    assert 'id="settings"' in html and "renderSettings" in html and "studio.settings.v3" in html
    for k in ("seedLock", "autoOpen", "haptics", "sound", "motion", "poll"):
        assert k in html, k
    assert "navigator.vibrate" in html and "prefers-reduced-motion" in html and "Request preview" in html
    i = html.index("const store = {")
    assert html[i:i + 400].count("try {") >= 2                                                           # every storage access is guarded


def test_v3_shell_csp_safe_and_self_contained():
    html = _shell_html()
    assert not re.search(r"<script[^>]+src=", html, re.I), "no external or src scripts"
    assert not re.search(r"<link[^>]+rel=[\"']stylesheet", html, re.I)
    assert "@import" not in html and "@font-face" not in html
    assert not re.search(r"(?:src|href)=[\"']https?://", html, re.I), "no external http(s) src or href in markup"
    assert not re.search(r"url\(\s*[\"']?https?://", html, re.I), "no external url() in CSS"
    assert not re.search(r"<[a-z][^>]*\son[a-z]+=", html, re.I), "no inline event-handler attributes"
    assert "eval(" not in html and "new Function" not in html
    assert "X-Requested-With" in html and '"approvals"' in html


if __name__ == "__main__":
    fails = 0
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            try: f(); print("ok   ", n)
            except Exception: fails += 1; print("FAIL ", n); traceback.print_exc()
    rig.close()
    print("%d failed" % fails); sys.exit(1 if fails else 0)
