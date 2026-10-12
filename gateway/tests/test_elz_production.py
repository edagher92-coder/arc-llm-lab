"""Tests for Auto Production (production.py, cheatsheets/*.json, auto workflows, web/elz_production.js). No torch/ComfyUI needed. Run: python -m pytest tests/test_elz_production.py -q"""
import importlib.util, io, json, os, re, urllib.error

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(D, "comfy_nodes", "elz_nodes")
SHEETS = os.path.join(PACK, "cheatsheets")
AUTO = os.path.join(D, "presets", "ltx25", "auto")
JS = os.path.join(PACK, "web", "elz_production.js")
spec = importlib.util.spec_from_file_location("elz_production_under_test", os.path.join(PACK, "production.py"))
P = importlib.util.module_from_spec(spec); spec.loader.exec_module(P)
SHEET_FILES = ("grading", "sound", "effects", "styling", "camera", "lighting", "shots")
MIN_ENTRIES = {"grading": 8, "sound": 5, "effects": 8, "styling": 6, "camera": 7, "lighting": 6, "shots": 6}


def load(name):
    return json.load(open(os.path.join(SHEETS, name + ".json"), encoding="utf-8"))


def test_cheatsheets_valid_schema():
    for name in SHEET_FILES:
        s = load(name)
        assert s["schema"] == 1 and s["sheet"] == name and s["license"] == "MIT" and s["guidance"], name
        assert len(s["entries"]) >= MIN_ENTRIES[name], name
        ids = [e["id"] for e in s["entries"]]
        assert len(ids) == len(set(ids)), name
        for e in s["entries"]:
            assert re.fullmatch(r"[a-z0-9-]+", e["id"]), e["id"]
            assert e["label"].strip() and e["prompt"].strip() and e["notes"].strip(), e["id"]
            assert len(e["prompt"]) <= 260, e["id"]
            assert isinstance(e.get("keywords"), list) and e["keywords"] and all(isinstance(k, str) for k in e["keywords"]), e["id"]
            assert isinstance(e.get("negative", ""), str)
            assert set(e) <= {"id", "label", "prompt", "negative", "keywords", "notes", "default"}, e["id"]
        assert sum(1 for e in s["entries"] if e.get("default")) <= 1, name
    for must in ("teal-orange", "kodak-2383", "bleach-bypass", "golden-hour", "noir-mono", "clean-commercial", "pastel", "night-neon"):
        assert must in [e["id"] for e in load("grading")["entries"]]


def test_characters_schema():
    c = load("characters")
    assert c["schema"] == 1 and c["fields"] == ["name", "look", "wardrobe", "voice", "mannerisms"] and len(c["entries"]) == 3
    for e in c["entries"]:
        assert e["id"] and all(e[f].strip() for f in c["fields"])


def test_auto_selection_is_deterministic_and_sensible():
    idea = "A chef flips a pizza in a busy kitchen at night, rain on the window"
    a = P.build_plan(idea); b = P.build_plan(idea)
    assert a == b and json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert P.auto_pick("grading", "neon cyberpunk city at night") == "night-neon"
    assert P.auto_pick("effects", "rain falls on the street") == "rain"
    assert P.auto_pick("effects", "a quiet moment") is None
    assert P.auto_pick("grading", "zzz") == "kodak-2383"            # the flagged default when nothing matches
    plan = P.build_plan("product ad for a bottle of water, orbit shot")
    assert plan["picks"]["style"]["id"] == "commercial-product" and plan["picks"]["camera"]["id"] == "orbit" and plan["picks"]["grade"]["id"] == "clean-commercial"


def test_manual_none_and_auto_off():
    plan = P.build_plan("a man walks", style="vintage-16mm", grade="none", sound="none", effects="none", camera="fpv", lighting="candle", shot="none")
    assert plan["picks"]["style"] == {"id": "vintage-16mm", "label": "Vintage 16mm", "source": "manual"}
    assert plan["picks"]["grade"]["id"] is None and plan["picks"]["sound"]["source"] == "none"
    off = P.build_plan("a man walks", auto=False)
    assert all(v["id"] is None for v in off["picks"].values())
    assert off["positive"].startswith("A man walks.")


def test_prompt_contains_fragments_and_stays_short():
    plan = P.build_plan("a runner sprints through a forest", style="documentary", grade="bleach-bypass", sound="amb-nature", effects="fog", camera="tracking", lighting="overcast", shot="medium")
    for sheet, key in (("styling", "style"), ("grading", "grade"), ("sound", "sound"), ("effects", "effects"), ("camera", "camera"), ("lighting", "lighting"), ("shots", "shot")):
        eid = plan["picks"][key]["id"]
        frag = next(e for e in P.entries_of(sheet) if e["id"] == eid)["prompt"]
        assert frag in plan["positive"], (key, eid)
    assert len(plan["positive"]) < 1500 and "\n" not in plan["positive"]
    long = P.build_plan("word " * 400 + "end", character=json.dumps([{"name": "A", "look": "x" * 240, "wardrobe": "y" * 240, "voice": "z" * 240, "mannerisms": "m" * 240}] * 3))
    assert len(long["positive"]) <= 1500 and long["warnings"]


def test_negative_merges_fragments_and_dedupes():
    plan = P.build_plan("a hero", style="photoreal-default", effects="handheld", negative_extra="blurry, extra fingers")
    neg = plan["negative"].split(", ")
    assert neg[0] == "blurry" and "extra fingers" in neg and "anime" in neg and "tripod stability" in neg
    assert len(neg) == len({n.lower() for n in neg})


def test_characters_input_forms():
    by_id = P.build_plan("x", character="mara")["positive"]
    assert "Mara Voss" in by_id and "silver-streaked" in by_id
    obj = P.build_plan("x", character=json.dumps({"name": "Zed", "look": "a tall robot", "voice": "flat"}))["positive"]
    assert "Zed, a tall robot." in obj and "voice is flat" in obj
    bad = P.build_plan("x", character="{not json")
    assert bad["warnings"] and "{not json" in bad["positive"]


def test_node_interface():
    cls = P.NODE_CLASS_MAPPINGS["ElzProductionPrompt"]
    it = cls.INPUT_TYPES()
    for k in ("style", "grade", "sound", "effects", "camera", "lighting"):
        assert it["required"][k][0][:2] == ["auto", "none"] and it["required"][k][1]["default"] == "auto"
    assert it["required"]["idea"][1]["multiline"] and it["required"]["length_seconds"][0] == "INT" and it["required"]["auto"][0] == "BOOLEAN"
    assert "character" in it["optional"] and cls.RETURN_TYPES == ("STRING",) * 3 and cls.RETURN_NAMES == ("positive", "negative", "plan")
    pos, neg, plan = cls().run("a cat on a wall")
    assert json.loads(plan)["positive"] == pos and neg


class _Resp:
    def __init__(self, text): self.b = text.encode()
    def read(self, n=-1): return self.b
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_director_fails_soft_when_unreachable_and_never_echoes_key(tmp_path, capsys):
    keyf = tmp_path / "key.txt"; keyf.write_text("SECRET-KEY-123\n")
    d = P.NODE_CLASS_MAPPINGS["ElzQwenDirector"]()
    plan = P.build_plan("a fox in snow")
    out, status = d.run("http://127.0.0.1:9/v1/chat/completions", "m", str(keyf), 1, True, json.dumps(plan), "")
    assert out == plan["positive"] and status.startswith("fallback")
    assert "SECRET-KEY-123" not in status and "SECRET-KEY-123" not in capsys.readouterr().out
    out2, st2 = d.run("not a url", "m", str(keyf), 1, True, "", "a fox")
    assert st2.startswith("fallback") and out2
    try:
        d.run("http://127.0.0.1:9/x", "m", str(keyf), 1, False, "", "a fox")
        raise AssertionError("should raise when skip_if_unavailable is false")
    except RuntimeError as ex:
        assert "SECRET-KEY-123" not in str(ex)
    assert d.INPUT_TYPES()["required"]["skip_if_unavailable"][1]["default"] is True
    assert d.INPUT_TYPES()["required"]["endpoint"][1]["default"] == "http://127.0.0.1:8090/v1/chat/completions"
    assert d.INPUT_TYPES()["required"]["model"][1]["default"] == "qwen3.8-27b"


def test_director_success_and_key_only_to_loopback(tmp_path, monkeypatch):
    keyf = tmp_path / "key.txt"; keyf.write_text("SECRET-KEY-123"); monkeypatch.setenv("ELZ_LLM_KEY_FILE", str(keyf))
    seen = {}
    reply = json.dumps({"choices": [{"message": {"content": "<think>hmm</think>A fox trots across fresh snow as the camera tracks beside it, soft breath rising in the cold air."}}]})
    def opener(req, timeout=None):
        seen["auth"] = req.get_header("Authorization"); seen["body"] = json.loads(req.data); return _Resp(reply)
    out, st = P.direct("template prompt", "a fox", "http://127.0.0.1:8090/v1/chat/completions", "m", str(keyf), 5, opener)
    assert out.startswith("A fox trots") and "think" not in out and st == "llm: m" and seen["auth"] == "Bearer SECRET-KEY-123"
    assert "LTX-2.5" in seen["body"]["messages"][0]["content"]
    seen.clear()
    out, st = P.direct("t", "a fox", "http://example.com/v1/chat/completions", "m", str(keyf), 5, opener)
    assert not seen and out == "t" and st == "fallback: remote endpoint refused (loopback only)"     # nothing sent to a remote host
    for url in ("http://127.0.0.2:1/x", "http://[::1]:1/x", "http://localhost:1/x"):
        assert P._is_local(url), url
    for url in ("http://example.com/x", "http://10.0.0.1/x", "http://127.0.0.1.evil.com/x", "http://localhost.evil.com/x", "http://user@example.com/x"):
        assert not P._is_local(url), url
    def boom(req, timeout=None): raise urllib.error.HTTPError("u", 401, "bad SECRET-KEY-123", {}, io.BytesIO(b""))
    out, st = P.direct("tmpl", "x", "http://127.0.0.1:1/x", "m", str(keyf), 1, boom)
    assert out == "tmpl" and st == "fallback: HTTP 401" and "SECRET" not in st


def test_redirect_is_not_followed(tmp_path):
    import http.server, threading
    hits = []
    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append((self.path, self.headers.get("Authorization")))
            self.send_response(302); self.send_header("Location", "http://127.0.0.1:%d/second" % self.server.server_port); self.send_header("Content-Length", "0"); self.end_headers()
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    keyf = tmp_path / "key.txt"; keyf.write_text("SECRET-KEY-123")
    old = os.environ.get("ELZ_LLM_KEY_FILE"); os.environ["ELZ_LLM_KEY_FILE"] = str(keyf)
    try:
        out, st = P.direct("tmpl", "x", "http://127.0.0.1:%d/first" % srv.server_port, "m", str(keyf), 3)
    finally:
        srv.shutdown(); srv.server_close()
        if old is None: os.environ.pop("ELZ_LLM_KEY_FILE", None)
        else: os.environ["ELZ_LLM_KEY_FILE"] = old
    assert out == "tmpl" and st == "fallback: HTTP 302" and "SECRET" not in st
    assert [h[0] for h in hits] == ["/first"] and hits[0][1] == "Bearer SECRET-KEY-123"      # the redirect target was never requested


def test_key_file_allowlist(tmp_path, monkeypatch):
    allowed = tmp_path / "ok.txt"; allowed.write_text("SECRET-KEY-123")
    other = tmp_path / "other.txt"; other.write_text("OTHER-KEY")
    link = tmp_path / "link.txt"
    try: link.symlink_to(other)
    except (OSError, NotImplementedError): link = None
    monkeypatch.delenv("ELZ_LLM_KEY_FILE", raising=False)
    assert P.read_key(str(allowed)) == "" and not P.key_file_allowed(str(allowed))
    monkeypatch.setenv("ELZ_LLM_KEY_FILE", str(allowed))
    assert P.read_key(str(allowed)) == "SECRET-KEY-123"
    assert P.read_key(str(other)) == ""
    if link: assert P.read_key(str(link)) == ""                                    # a symlink to a different file is judged by its real path
    seen = {}
    reply = json.dumps({"choices": [{"message": {"content": "A fox trots across fresh snow as the camera tracks beside it, soft breath rising."}}]})
    def opener(req, timeout=None): seen["auth"] = req.get_header("Authorization"); return _Resp(reply)
    out, st = P.direct("t", "x", "http://127.0.0.1:1/x", "m", str(other), 1, opener)
    assert seen["auth"] is None and "key file not allowed" in st and "OTHER-KEY" not in st
    out, st = P.direct("t", "x", "http://127.0.0.1:1/x", "m", str(allowed), 1, opener)
    assert seen["auth"] == "Bearer SECRET-KEY-123" and "not allowed" not in st


def test_prompt_cap_keeps_idea_and_is_deterministic():
    idea = ("a" * 1197) + " end"
    runs = [P.build_plan(idea + "xyz") for _ in range(2)]
    assert runs[0] == runs[1]
    assert len(runs[0]["positive"]) <= 1500 and runs[0]["idea"][:300] == runs[0]["positive"][:300]
    assert runs[0]["idea"].lower().startswith("aaaa") and len(runs[0]["idea"]) <= 1200
    assert runs[0]["positive"].startswith(runs[0]["idea"].rstrip(".") )
    assert len(P.build_plan("b" * 1200 + "xyz", style="trailer-epic")["positive"]) <= 1500


def test_set_size_targets_only_preprocess_subgraph():
    src = open(JS, encoding="utf-8").read()
    m = re.search(r'SIZE_SUBGRAPH_ID = "([0-9a-f-]{36})"', src)
    for f in os.listdir(AUTO):
        d = json.load(open(os.path.join(AUTO, f), encoding="utf-8"))
        assert [n for n in d["nodes"] if n["type"] == m.group(1)], f
    body = src[src.index("function setSize"):src.index("async function loadWorkflow")]
    assert "SIZE_SUBGRAPH_ID" in body and "continue" in body


def test_init_registers_nodes_without_touching_existing():
    src = open(os.path.join(PACK, "__init__.py"), encoding="utf-8").read()
    assert '"ElzAudioNanGuard": AudioNanGuard, "ElzSaveConditioning": SaveConditioning, "ElzLoadConditioning": LoadConditioning' in src
    assert 'WEB_DIRECTORY = "./web"' in src and "from .production import" in src and "NODE_CLASS_MAPPINGS.update" in src


def _check_workflow(path):
    d = json.load(open(path, encoding="utf-8"))
    nodes = {n["id"]: n for n in d["nodes"]}
    assert len(nodes) == len(d["nodes"]) and d["last_node_id"] >= max(nodes)
    links = {}
    for l in d["links"]:
        assert len(l) == 6 and l[0] not in links; links[l[0]] = l
    assert d["last_link_id"] >= max(links)
    for lid, (_, o, os_, t, ts, typ) in links.items():
        assert o in nodes and t in nodes, lid
        assert lid in (nodes[o]["outputs"][os_].get("links") or []), ("origin slot does not list link", lid)
        assert nodes[t]["inputs"][ts]["link"] == lid, ("target slot does not point back", lid)
    for n in d["nodes"]:
        for i, s in enumerate(n.get("outputs") or []):
            for lid in s.get("links") or []:
                assert lid in links and links[lid][1] == n["id"] and links[lid][2] == i, (n["id"], lid)
        for i, s in enumerate(n.get("inputs") or []):
            if s.get("link") is not None:
                assert s["link"] in links and links[s["link"]][3] == n["id"] and links[s["link"]][4] == i, (n["id"], s["link"])
    return d, nodes, links


def test_auto_workflows_have_valid_links():
    for dst, src in (("Auto_Production_T2V_I2V_Two_Stage_Distilled", "LTX-2.5_T2V_I2V_Two_Stage_Distilled"), ("Auto_Production_T2V_I2V_Single_Stage_Distilled", "LTX-2.5_T2V_I2V_Single_Stage_Distilled")):
        d, nodes, links = _check_workflow(os.path.join(AUTO, dst + ".json"))
        base, bnodes, blinks = _check_workflow(os.path.join(D, "presets", "ltx25", src + ".json"))
        elz = [n for n in d["nodes"] if n["type"] == "ElzProductionPrompt"]
        assert len(elz) == 1
        e = elz[0]
        assert d["extra"]["auto_production"]["name"] == "Auto Production T2V/I2V"
        sub = nodes[5014]
        assert links[sub["inputs"][4]["link"]][1] == e["id"] and links[sub["inputs"][4]["link"]][2] == 0     # positive -> prompt subgraph
        assert links[sub["inputs"][6]["link"]][1] == e["id"] and links[sub["inputs"][6]["link"]][2] == 1     # negative -> prompt subgraph
        assert [i["name"] for i in e["inputs"] if i.get("widget")] == [i for i in ["idea", "style", "grade", "sound", "effects", "camera", "lighting", "length_seconds", "auto", "character", "shot"]]
        it = P.ProductionPrompt.INPUT_TYPES()
        assert len([i for i in e["inputs"] if i.get("widget")]) == len(e["widgets_values"])
        for name, val in zip([i["name"] for i in e["inputs"] if i.get("widget")], e["widgets_values"]):
            spec = (it["required"].get(name) or it["optional"][name])[0]
            if isinstance(spec, list): assert val in spec, (name, val)
        # everything that was in the base workflow is still there, with the same links except the two re-routed ones
        assert set(bnodes) <= set(nodes)
        for lid, l in blinks.items():
            if lid in (13630, 13631): assert links[lid][3:] == l[3:] and links[lid][1] == e["id"]
            else: assert links[lid] == l, lid
        assert {k for k in d if k not in ("id", "nodes", "links", "groups", "extra", "last_node_id", "last_link_id")} == {k for k in base if k not in ("id", "nodes", "links", "groups", "extra", "last_node_id", "last_link_id")}
        assert d["definitions"] == base["definitions"]
        for nid, bn in bnodes.items():
            if nid not in (5508, 5509): assert nodes[nid] == bn, nid


def test_web_extension():
    src = open(JS, encoding="utf-8").read()
    assert 'name: "elz.production"' in src and "registerExtension" in src
    assert "http://" not in src and "https://" not in src and not re.search(r"\beval\s*\(|new Function|XMLHttpRequest|\bfetch\(|import\(", src)
    m = re.search(r"/\*PRESETS_BEGIN\*/(.*?)/\*PRESETS_END\*/", src, re.S)
    assert json.loads(m.group(1)) == load("production_presets")["presets"]
    pre = load("production_presets")["presets"]
    assert list(pre) == ["trailer", "product-ad", "music-video", "documentary", "social-vertical"]
    for name, p in pre.items():
        for key, sheet in (("style", "styling"), ("grade", "grading"), ("sound", "sound"), ("effects", "effects"), ("camera", "camera"), ("lighting", "lighting"), ("shot", "shots")):
            assert p[key] in P.sheet_choices(sheet), (name, key, p[key])
        assert 1 <= p["length_seconds"] <= 60 and p["width"] % 64 == 0 and p["height"] % 64 == 0
        assert len(P.build_plan(p["idea"], **{k: p[k] for k in ("style", "grade", "sound", "effects", "camera", "lighting", "shot")})["positive"]) < 1500
    assert "elz_studio" not in src
