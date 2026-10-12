"""MCP video tool tests (tools_video_mcp.py): registration, policy gating, presets listing, session/mode tools against a mock Queue.
Run: python -m pytest tests/test_mcp_video.py -q"""
import asyncio, json, os, sys, tempfile

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, D)
import video, tools_video_mcp as tv

TMP = tempfile.mkdtemp(prefix="mcpvid-")
NEW = {"video_system", "video_presets", "video_comfy_session", "video_mode"}
OLD = {"video_workflows", "video_generate", "video_status", "video_result", "video_queue", "video_cancel"}


class FakeServer:
    def __init__(self): self.tools = {}
    def tool(self, name, description=""):
        def deco(f): self.tools[name] = (f, description); return f
        return deco


class FakeQueue:
    """Records calls; stands in for video.Queue so the tools are shown to delegate and not to re-implement."""
    def __init__(self, workflows_dir, enabled=True):
        self.cfg = video.Cfg({"comfy_dir": TMP, "comfy_cmd": ["x"], "workflows_dir": workflows_dir}, TMP)
        self.cfg.enabled = enabled
        self.calls, self.raise_ = [], None
    def _maybe(self):
        if self.raise_: raise self.raise_
    def recent(self, n=10): return [{"id": "aa", "state": "running"}, {"id": "bb", "state": "queued"}]
    def mode_get(self): return {"mode": "MAX", "view": "llm", "hold": False}
    def session_info(self): return {"active": False, "state": None, "idle_s": None, "error": ""}
    def busy(self): return True
    def session_start(self): self.calls.append(("session_start",)); self._maybe(); return {"active": True, "state": "starting", "idle_s": None, "error": ""}
    def session_stop(self): self.calls.append(("session_stop",)); self._maybe(); return {"active": False, "state": None, "idle_s": None, "error": ""}
    def mode_set(self, m): self.calls.append(("mode_set", m)); self._maybe(); return {"mode": "OFF", "view": m, "hold": True}
    def submit(self, wf, raw): self.calls.append(("submit", wf, raw)); self._maybe(); return "j1", 0, 4.0


def workflows_dir():
    d = tempfile.mkdtemp(dir=TMP)
    meta = {"description": "t", "est_minutes": "4", "params": {"prompt": {"type": "str", "required": True}},
            "presets": [{"name": "draft", "label": "Draft", "params": {"width": 768, "height": 416, "seconds": 3}, "note": "fast"},
                        {"name": "hero", "label": "Hero", "params": {"width": 960, "height": 544, "seconds": 5}}]}
    json.dump({"meta": meta, "prompt": {"1": {"class_type": "T", "inputs": {}}}}, open(os.path.join(d, "t2v.json"), "w"))
    return d


def rig(enabled=True):
    q = FakeQueue(workflows_dir(), enabled); s = FakeServer(); tv.register(s, q, D)
    return q, {k: v[0] for k, v in s.tools.items()}, s


def test_tools_registered():
    q, t, s = rig()
    assert NEW | {"video_generate"} <= set(t), set(t)
    assert "preset" in s.tools["video_generate"][1] and "seed" in s.tools["video_generate"][1] and "image" in s.tools["video_generate"][1]
    import inspect
    assert list(inspect.signature(t["video_generate"]).parameters) == ["prompt", "workflow", "preset", "seconds", "width", "height", "seed", "image", "negative"]


def test_noop_without_queue():
    s = FakeServer(); tv.register(s, None, D); assert s.tools == {}


def test_registered_on_real_fastmcp_replacing_generate():
    from fastmcp import FastMCP
    srv = FastMCP("t"); wd = workflows_dir()
    cfg = {"video": {"comfy_dir": TMP, "comfy_cmd": ["x"], "workflows_dir": wd, "enabled": False}}
    q = video.register(srv, cfg, TMP, TMP, None); tv.register(srv, q, D)
    tools = {x.name: x for x in asyncio.run(srv.list_tools())}
    assert (NEW | OLD) <= set(tools) and "preset" in tools["video_generate"].parameters["properties"], set(tools)
    assert "preset" in tools["video_generate"].description


def test_write_tools_gated_read_tools_not():
    """Policy straight from gateway.example.json: write tools are PIN-gated, read tools are not."""
    if "gateway" not in sys.modules:
        cf = os.path.join(TMP, "gw.json"); json.dump({"name": "gw", "servers": {}}, open(cf, "w")); sys.argv = ["gateway.py", cf]
        os.environ.setdefault("GW_STATE_DIR", os.path.join(TMP, "state"))
    import gateway
    ex = json.load(open(os.path.join(D, "gateway.example.json"), encoding="utf-8-sig"))["policy"]
    assert {"video_system", "video_presets"} <= set(ex["read"])      # the example policy itself lists them (no test-side injection)
    old, gateway.POLICY = gateway.POLICY, ex
    try:
        g = gateway.Guard()
        for n in ("video_generate", "video_cancel", "video_comfy_session", "video_mode"):
            assert g.intent(n) == "write", n
            c = g.check(n, {"x": 1})
            assert isinstance(c, tuple) and c[0] == "approve", (n, c)
        for n in ("video_system", "video_presets", "video_workflows", "video_status", "video_result", "video_queue"):
            assert g.intent(n) == "read", n
    finally:
        gateway.POLICY = old


def test_presets_lists_index_and_workflow_presets():
    q, t, _ = rig()
    out = json.loads(t["video_presets"]())
    assert [p["name"] for p in out["workflow_presets"]["t2v"]] == ["draft", "hero"]
    idx = json.load(open(os.path.join(D, "presets", "ltx25", "index.json"), encoding="utf-8"))
    assert [p["name"] for p in out["comfy_graphs"]] == [p["name"] for p in idx["presets"]] and len(out["comfy_graphs"]) == 17
    two = next(p for p in out["comfy_graphs"] if p["name"] == "LTX-2.5_T2V_I2V_Two_Stage_Distilled")
    assert two["runnable_now"] and two["purpose"] and out["models"] == idx["our_models"] and out["source_sha"] == idx["source_sha"]


def test_presets_missing_index_is_soft():
    assert tv.load_index(tempfile.mkdtemp(dir=TMP)) == {}


def test_system_reads_queue_functions():
    q, t, _ = rig()
    d = json.loads(t["video_system"]())
    assert d["mode"] == "busy" and d["governor_mode"] == "MAX" and d["queued"] == 1 and d["running_job"] == "aa" and d["comfy_session"]["active"] is False and d["enabled"]
    assert q.calls == []                                     # read only


def test_session_tool_calls_queue():
    q, t, _ = rig()
    assert json.loads(t["video_comfy_session"]("start"))["state"] == "starting"
    assert json.loads(t["video_comfy_session"]("stop"))["active"] is False
    assert q.calls == [("session_start",), ("session_stop",)]
    assert "start or stop" in t["video_comfy_session"]("restart") and len(q.calls) == 2
    q.raise_ = video.VideoBusy("a video job is running"); r = t["video_comfy_session"]("start")
    assert r.startswith("Refused") and "video job" in r


def test_mode_tool_calls_queue():
    q, t, _ = rig()
    assert json.loads(t["video_mode"]("video"))["view"] == "video" and json.loads(t["video_mode"]("llm"))["view"] == "llm"
    assert q.calls == [("mode_set", "video"), ("mode_set", "llm")]
    assert "video or llm" in t["video_mode"]("gpu") and len(q.calls) == 2
    q.raise_ = video.VideoError("the governor mode file is not configured"); assert t["video_mode"]("llm").startswith("Refused")


def test_generate_preset_and_overrides():
    q, t, _ = rig()
    g = json.loads(t["video_generate"]("a fox", preset="Draft", seed=7, image="/x/a.png"))
    assert g == {"job_id": "j1", "workflow": "t2v", "position": 0, "est_minutes": 4.0}
    _, wf, raw = q.calls[-1]
    assert wf == "t2v" and (raw["width"], raw["height"], raw["seconds"], raw["seed"], raw["image"], raw["prompt"]) == (768, 416, 3, 7, "/x/a.png", "a fox")
    t["video_generate"]("a fox", preset="hero", width=1024, seconds=2)
    raw = q.calls[-1][2]; assert (raw["width"], raw["height"], raw["seconds"]) == (1024, 544, 2)       # explicit args win, preset fills the rest
    t["video_generate"]("a fox"); raw = q.calls[-1][2]; assert raw["width"] == 0 and raw["seed"] == -1   # no preset: passed through untouched
    n = len(q.calls); assert t["video_generate"]("a fox", preset="nope").startswith("Not queued: unknown preset") and len(q.calls) == n
    assert t["video_generate"]("a fox", workflow="t2v", preset="hero") and q.calls[-1][1] == "t2v"
    q.raise_ = video.VideoError("queue is full"); assert t["video_generate"]("x").startswith("Not queued")


def test_generate_disabled():
    q, t, _ = rig(enabled=False)
    assert "not set up" in t["video_generate"]("x") and q.calls == []


def test_generate_preset_ambiguous_across_workflows():
    q, t, _ = rig()
    d2 = q.cfg.workflows_dir
    w = json.load(open(os.path.join(d2, "t2v.json"))); json.dump(w, open(os.path.join(d2, "i2v.json"), "w"))
    n = len(q.calls)
    r = t["video_generate"]("a fox", preset="draft")
    assert r.startswith("Not queued: ambiguous preset 'draft'; pass workflow (one of: i2v, t2v)") and len(q.calls) == n
    assert json.loads(t["video_generate"]("a fox", workflow="i2v", preset="draft"))["workflow"] == "i2v"


def test_preset_values_go_through_real_alignment():
    """Preset values are only filled in here; video.resolve_params (called by the real Queue.submit) snaps them: multiple_of and 8n+1 frames."""
    d = tempfile.mkdtemp(dir=TMP)
    meta = {"fps": 24, "frames_rule": "8n+1", "presets": [{"name": "odd", "params": {"width": 770, "height": 421, "seconds": 3.3}}],
            "params": {"prompt": {"type": "str", "required": True},
                       "width": {"type": "int", "min": 256, "max": 1280, "multiple_of": 32, "default": 768},
                       "height": {"type": "int", "min": 256, "max": 1280, "multiple_of": 32, "default": 416},
                       "frames": {"type": "int", "min": 9, "max": 257, "default": 49}}}
    json.dump({"meta": meta, "prompt": {"1": {"class_type": "T", "inputs": {}}}}, open(os.path.join(d, "t2v.json"), "w"))
    q = FakeQueue(d); s = FakeServer(); tv.register(s, q, D)
    s.tools["video_generate"][0]("a fox", preset="odd")
    _, wf, raw = q.calls[-1]
    vals, _ = video.resolve_params(video.load_workflows(d)[wf], raw, q.cfg)
    assert raw["width"] == 770 and vals["width"] % 32 == 0 and vals["height"] % 32 == 0 and (vals["width"], vals["height"]) == (768, 416)
    assert vals["frames"] % 8 == 1 and vals["frames"] == 81, vals            # 3.3 s * 24 fps + 1 = 80.2 -> 81


def test_build_hook_registers_video_tools():
    """gateway.build() must call tools_video_mcp.register right after video.register: deleting that hook fails this test."""
    if "gateway" not in sys.modules:
        cf = os.path.join(TMP, "gw.json"); json.dump({"name": "gw", "servers": {}}, open(cf, "w")); sys.argv = ["gateway.py", cf]
        os.environ.setdefault("GW_STATE_DIR", os.path.join(TMP, "state"))
    import gateway
    import tools_video_mcp as vmod     # the module gateway.build() imports (another test file may have re-imported it)
    seen = []
    real = vmod.register
    vmod.register = lambda srv, q, base: seen.append((srv, q, base))
    try:
        gateway.build()
    finally:
        vmod.register = real
    assert len(seen) == 1 and seen[0][2] == gateway.HERE
