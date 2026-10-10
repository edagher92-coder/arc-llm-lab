"""Gateway tests: plain asserts, no pytest needed (works under pytest too).  Run: python tests/test_gateway.py"""
import asyncio, hashlib, json, os, sys, tempfile, traceback, urllib.request, secrets

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gwtest-")
PY = sys.executable

# ---- fixture: three skills (one with broken frontmatter), a second missing root, and a test config ----
ROOT = os.path.join(TMP, "skills"); os.makedirs(ROOT)
def skill(d, text):
    os.makedirs(os.path.join(ROOT, d)); open(os.path.join(ROOT, d, "SKILL.md"), "w", encoding="utf-8").write(text)
skill("quote-builder", "---\nname: quote-builder\ndescription: Build an equipment hire quote with delivery and bond\n---\n# Quote builder\n\nStep 1: ask the dates.\n")
skill("release-check", "---\nname: release-check\ndescription: >\n  Release checklist for tagging, CI and\n  deploying a build\n---\nRun the tests first.\n")
skill("bad-front", "---\n:::: not yaml [oops ::::\n---\nDiagnose pump seal leaks on soft-serve machines by checking the O-ring.\n\nSecond paragraph.\n")
os.makedirs(os.path.join(ROOT, "no-skill-md"))
open(os.path.join(TMP, "secret.txt"), "w").write("SECRET")
os.environ["GWTEST_SKILLS"] = ROOT

CFGF = os.path.join(TMP, "gw.json")
json.dump({
    "name": "gw", "max_results": 3,
    "servers": {"pc": {"command": PY, "args": [os.path.join(D, "proto", "dummy_a.py")]},
                "web": {"command": PY, "args": [os.path.join(D, "proto", "dummy_b.py")]},
                "data": {"command": PY, "args": [os.path.join(D, "proto", "dummy_c.py")]}},
    "pin": ["pc_read_file", "skills"], "hide": ["web_get_current_time"],
    "aliases": {"web_browser_screenshot": "capture picture image snapshot page"},
    "descriptions": {"search_tools": "SEARCH-DESC find a tool", "call_tool": "CALL-DESC run a tool",
                     "skills": "SKILLS-DESC playbooks", "pc_read_file": "READ-DESC read a file"},
    "skills": {"roots": ["%GWTEST_SKILLS%", os.path.join(TMP, "missing-root")]},
    "policy": {"read": ["*read_file", "*screenshot*", "data_*", "skills"], "write": ["*powershell*"], "destructive": [],
               "deny_args": [{"tools": ["*powershell*"], "pattern": "Remove-Item[^|]*-Recurse", "why": "recursive delete"}],
               "max_identical_calls": 3, "max_result_chars": 12000}}, open(CFGF, "w"))
sys.argv = ["gateway.py", CFGF]
sys.path.insert(0, D)
os.environ["GW_APPROVAL_PORT"] = "18095"
os.environ["GW_STATE_DIR"] = os.path.join(TMP, "state")
import gateway, approvals
from fastmcp import Client
approvals.PIN_FILE = os.path.join(TMP, "approval-pin.json")
GW = gateway.build()


def run(coro): return asyncio.run(coro)
async def call(c, name, args):
    try: r = await c.call_tool("call_tool", {"name": name, "arguments": args}); return "RAN: " + r.content[0].text
    except Exception as e: return "ERR: " + str(e)


def test_descriptions_rewritten_and_stable():
    async def go():
        async with Client(GW) as c:
            a = await c.list_tools(); b = await c.list_tools()
        d = {t.name: t.description for t in a}
        assert d["search_tools"] == "SEARCH-DESC find a tool" and d["call_tool"] == "CALL-DESC run a tool", d
        assert d["skills"] == "SKILLS-DESC playbooks" and d["pc_read_file"] == "READ-DESC read a file"
        assert [t.name for t in a] == ["pc_read_file", "skills", "search_tools", "call_tool"], [t.name for t in a]
        h = lambda ts: hashlib.sha256(json.dumps([t.model_dump(mode="json") for t in ts], sort_keys=True).encode()).hexdigest()
        assert h(a) == h(b), "tool list changed between calls"
        for t in a:   # schemas untouched: required args still there
            if t.name == "call_tool": assert "name" in t.inputSchema["required"]
    run(go())


def test_example_config_descriptions_short():
    c = json.load(open(os.path.join(D, "gateway.example.json")))
    assert all(len(v) <= 300 for v in c["descriptions"].values())
    for k in ("search_tools", "call_tool", "skills", "share_file"): assert k in c["descriptions"], k
    assert "pc_Skill" in c["hide"] and "pc_Skill" not in c["policy"]["write"]
    assert "skills" in c["policy"]["read"] and "share_file" in c["policy"]["read"]
    assert c["policy"]["max_result_chars"] == 12000 and c["outbox"]["ttl_hours"] == 24 and c["skills"]["roots"]


def test_instructions_loaded():
    assert GW.instructions and "search_tools" in GW.instructions and "NEEDS APPROVAL" in GW.instructions
    assert len(GW.instructions) < 2500


def test_truncation_and_small_untouched():
    async def go():
        async with Client(GW) as c:
            out = await call(c, "data_big", {"n": 100000})
            text = out[len("RAN: "):]
            assert len(text) < 12000 and text.startswith("HEAD-") and "-TAIL" in text[-2700:], len(text)
            assert "[gateway: trimmed" in text and "narrow" in text
            assert text.count("x") >= 11000
            assert (await call(c, "data_small", {})) == "RAN: tiny result"
            assert len(await call(c, "data_big", {"n": 11999})) == 11999 + 5     # just under the limit: untouched
        last = [json.loads(l) for l in open(gateway.AUDIT)]
        big = [r for r in last if r.get("tool") == "data_big" and r.get("verdict") == "ok" and r["chars_in"] == 100000][-1]
        assert big["chars_out"] < 12000 and "ms" in big
    run(go())


def test_trim_result_non_text_passes():
    from fastmcp.tools.base import ToolResult
    from mcp.types import ImageContent, TextContent
    img = ImageContent(type="image", data="A" * 50000, mimeType="image/png")
    r = ToolResult(content=[img, TextContent(type="text", text="y" * 30000)])
    cin, cout = gateway.trim_result(r, 12000)
    assert r.content[0].data == "A" * 50000 and cin == 30000 and cout < 12000
    assert gateway.trim_result(r, 0)[0] == cout     # limit 0 = off
    r2 = ToolResult(content="z" * 30000); gateway.trim_result(r2, 0); assert len(r2.content[0].text) == 30000


def test_unknown_tool_suggestions():
    async def go():
        async with Client(GW) as c:
            out = await call(c, "pc_run_powershel", {"command": "dir"})
            assert out.startswith("ERR:") and "Unknown tool pc_run_powershel. Closest:" in out and "pc_run_powershell" in out, out
            out = await call(c, "take_screenshot", {})
            assert "Unknown tool" in out and "web_browser_screenshot" in out, out
            assert "NEEDS APPROVAL" not in out
            assert "not available" in (await call(c, "web_get_current_time", {}))     # hidden keeps its own message
    run(go())


def test_skills_search_load_and_traversal():
    async def go():
        async with Client(GW) as c:
            r = json.loads((await c.call_tool("skills", {"action": "search", "query": "hire quote delivery"})).content[0].text)
            assert r[0]["name"] == "quote-builder" and r[0]["path"].endswith("SKILL.md") and len(r[0]["description"]) <= 140
            r = json.loads((await c.call_tool("skills", {"action": "search", "query": "release checklist ci"})).content[0].text)
            assert r[0]["name"] == "release-check" and "Release checklist for tagging" in r[0]["description"], r
            r = json.loads((await c.call_tool("skills", {"action": "search", "query": "pump seal leak"})).content[0].text)
            assert r[0]["name"] == "bad-front" and r[0]["description"].startswith("Diagnose pump seal"), r      # fallback: dir name + first paragraph
            assert len(json.loads((await c.call_tool("skills", {"action": "search", "query": ""})).content[0].text)) == 3
            body = (await c.call_tool("skills", {"action": "load", "query": "quote-builder"})).content[0].text
            assert "Step 1: ask the dates." in body and "description:" not in body and not body.startswith("---")
            assert "Reference files are under" in body and "quote-builder" in body
            for bad in ("../secret", "..", "../../etc/passwd", "quote-builder/../../x", "C:\\Windows\\x", "/etc/passwd", "nope", ""):
                try: await c.call_tool("skills", {"action": "load", "query": bad}); raise AssertionError("loaded " + bad)
                except AssertionError: raise
                except Exception as e: assert "Unknown skill" in str(e), (bad, str(e))
            try: await c.call_tool("skills", {"action": "delete", "query": "x"}); raise AssertionError("bad action accepted")
            except AssertionError: raise
            except Exception: pass
    run(go())


def test_skills_reindex_missing_root_and_trim():
    import skills, shutil
    root2 = os.path.join(TMP, "skills2"); shutil.copytree(ROOT, root2, symlinks=True)
    def add(d, text):
        os.makedirs(os.path.join(root2, d), exist_ok=True); open(os.path.join(root2, d, "SKILL.md"), "w").write(text)
    ix = skills.SkillIndex([root2, os.path.join(TMP, "nothing-here")])
    assert len(ix.search("")) == 3
    add("late-skill", "---\nname: late-skill\ndescription: Added after the first index\n---\nbody\n")
    assert ix.search("added after")[0]["name"] == "late-skill"          # picked up without restart
    add("late-skill", "---\nname: late-skill\ndescription: x\n---\n" + "L" * 50000)
    out = ix.load("late-skill", 12000)
    assert len(out) < 12000 and "[gateway: trimmed" in out and out.count("L") > 8000
    assert skills.parse_frontmatter("no front")[0] == {}
    assert skills.first_paragraph("---\nunterminated front\n\nreal text") == "unterminated front"
    os.makedirs(os.path.join(root2, "escape")); os.symlink(os.path.join(TMP, "secret.txt"), os.path.join(root2, "escape", "SKILL.md"))
    assert "escape" not in [s["name"] for s in ix.search("")] + [s["name"] for s in ix.search("secret")]   # symlink out of root skipped


def test_ready_line_in_audit():
    async def go():
        async with Client(GW) as c: await c.list_tools()
    run(go())
    lines = [json.loads(l) for l in open(gateway.AUDIT)]
    ready = [r for r in lines if r.get("event") == "ready"]
    assert ready and ready[0]["why"].startswith("ready: ") and " tools from 3 servers in " in ready[0]["why"], ready


def test_audit_chain_intact():
    prev = "0" * 64
    for l in open(gateway.AUDIT):
        r = json.loads(l); h = r.pop("hash")
        assert r["prev"] == prev and hashlib.sha256(json.dumps(r, sort_keys=True, ensure_ascii=False).encode()).hexdigest() == h
        prev = h


# ---- approval flow (adapted from proto/t3.py) ----
B = "http://127.0.0.1:18095"
def post(path, body=None, cookie=None, xrw=True):
    h = {"Content-Type": "application/json"}
    if xrw: h["X-Requested-With"] = "approvals"
    if cookie: h["Cookie"] = cookie
    req = urllib.request.Request(B + path, data=json.dumps(body or {}).encode(), headers=h, method="POST")
    try: r = urllib.request.urlopen(req); return r.status, r.headers.get("Set-Cookie"), r.read().decode()
    except urllib.error.HTTPError as e: return e.code, None, e.read().decode()
def get(path, cookie=None):
    req = urllib.request.Request(B + path, headers={"Cookie": cookie} if cookie else {})
    try: r = urllib.request.urlopen(req); return r.status, r.read().decode()
    except urllib.error.HTTPError as e: return e.code, e.read().decode()


def test_approval_flow_still_works():
    async def go():
        async with Client(GW) as c:
            assert "no PIN" in await call(c, "pc_run_powershell", {"command": "dir"}) or "not set up" in await call(c, "pc_run_powershell", {"command": "dir0"})
            salt = secrets.token_bytes(16); pin = "test-" + secrets.token_hex(4)
            json.dump({"salt": salt.hex(), "iterations": 200000, "hash": hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 200000).hex()}, open(approvals.PIN_FILE, "w"))
            m = await call(c, "pc_run_powershell", {"command": "dir"}); assert "request " in m, m
            pid = m.split("request ")[1].split(":")[0]
            assert get("/approvals/pending.json")[0] in (401, 403)
            assert post("/approvals/%s/approve" % pid)[0] in (401, 403)
            st, ck, _ = post("/approvals/login", {"pin": pin}); assert st == 200; cookie = ck.split(";")[0]
            assert json.loads(get("/approvals/pending.json", cookie)[1])[0]["tool"] == "pc_run_powershell"
            assert (await call(c, "pc_run_powershell", {"command": "dir"})).startswith("ERR:")      # not approved yet
            assert post("/approvals/%s/approve" % pid, cookie=cookie)[0] == 200
            assert await call(c, "pc_run_powershell", {"command": "dir"}) == "RAN: ran dir"
            assert (await call(c, "pc_run_powershell", {"command": "dir"})).startswith("ERR:")      # single use
            m = await call(c, "pc_run_powershell", {"command": "Get-Date"}); pid2 = m.split("request ")[1].split(":")[0]
            post("/approvals/%s/deny" % pid2, cookie=cookie)
            assert "DENIED" in await call(c, "pc_run_powershell", {"command": "Get-Date"})
            assert await call(c, "web_browser_screenshot", {"url": "x"}) == "RAN: shot x"             # read intent: no approval
            assert "recursive delete" in await call(c, "pc_run_powershell", {"command": "Remove-Item C:/x -Recurse"})
        os.remove(approvals.PIN_FILE)
    run(go())


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted((k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)):
        try: fn(); print("PASS", name)
        except Exception: fails += 1; print("FAIL", name); traceback.print_exc()
    print("\n%d failed" % fails if fails else "\nall passed"); os._exit(1 if fails else 0)
