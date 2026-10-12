"""Agent loop tests: plain asserts, a scripted mock OpenAI server, real gateway (Guard, approvals, audit) with dummy MCP servers.
Run: python tests/test_agent.py"""
import asyncio, hashlib, json, os, sys, tempfile, threading, time, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="agtest-")
PY = sys.executable
GUARD_MSG = "You already ran this exact call; use its result or change approach."


# ---------------- mock OpenAI server ----------------
class Mock:
    def __init__(self):
        self.script, self.default, self.requests, self.auth, self.delay = [], None, [], [], 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body); outer.auth.append(self.headers.get("Authorization"))
                time.sleep(outer.delay)
                if outer.script: item = outer.script.pop(0)
                elif outer.default: item = outer.default(len(outer.requests))
                else: item = text("(mock script exhausted)")
                if isinstance(item, tuple) and item[0] == "http":
                    self.send_response(item[1]); self.end_headers(); self.wfile.write(b'{"error":"boom"}'); return
                b = json.dumps({"choices": [{"message": item}], "usage": {"prompt_tokens": 100, "completion_tokens": 10}}).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
                self.end_headers(); self.wfile.write(b)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d/v1" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def reset(self, script=(), default=None):
        self.delay = 0
        self.script, self.default, self.requests, self.auth = list(script), default, [], []

    def efforts(self):
        return [r["chat_template_kwargs"]["reasoning_effort"] for r in self.requests]


def text(s): return {"role": "assistant", "content": s}
def tool(name, args, content=""):
    return {"role": "assistant", "content": content,
            "tool_calls": [{"id": "c%d" % abs(hash(name + json.dumps(args))), "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}
def via(target, args): return tool("call_tool", {"name": target, "arguments": args})
PLAN = text("1. read the file\n2. answer")


MOCK = Mock()
KEYF = os.path.join(TMP, "api-key.txt"); open(KEYF, "w").write("k123\n")
CFGF = os.path.join(TMP, "gw.json")
json.dump({
    "name": "gw", "max_results": 3,
    "servers": {"pc": {"command": PY, "args": [os.path.join(D, "proto", "dummy_a.py")]},
                "web": {"command": PY, "args": [os.path.join(D, "proto", "dummy_b.py")]},
                "data": {"command": PY, "args": [os.path.join(D, "proto", "dummy_c.py")]},
                "doc": {"command": PY, "args": [os.path.join(D, "proto", "dummy_d.py")]}},
    "pin": ["pc_read_file", "agent"], "hide": ["web_get_current_time"],
    "policy": {"read": ["*read_file", "*screenshot*", "data_*", "doc_*", "agent"], "write": ["*powershell*"], "destructive": [],
               "max_identical_calls": 3, "max_calls_per_window": 500, "max_result_chars": 12000},
    "agent": {"base_url": MOCK.url, "api_key_file": KEYF, "max_steps_cap": 30, "timeout_s": 30}}, open(CFGF, "w"))
sys.argv = ["gateway.py", CFGF]
sys.path.insert(0, D)
import socket
def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
for _m in ("gateway", "approvals", "skills", "outbox", "agent", "studio", "video", "tts_server", "cc_notify", "tools_video_mcp", "tools_local_llm", "build_workflow"):
    sys.modules.pop(_m, None)     # other test files in the same process may have imported these with their own port/state
os.environ["GW_APPROVAL_PORT"] = str(_free_port())
os.environ["GW_STATE_DIR"] = os.path.join(TMP, "state")
import gateway, approvals, agent
from fastmcp import Client
approvals.PIN_FILE = os.path.join(TMP, "approval-pin.json")
GW = gateway.build()


def run(coro): return asyncio.run(coro)
def audit_lines(): return [json.loads(l) for l in open(gateway.AUDIT)] if os.path.exists(gateway.AUDIT) else []


SEQ = 0
def go_agent(script=(), default=None, **args):
    """Run one agent() call through the gateway. Returns (result dict, audit records written during the call)."""
    MOCK.reset(script, default)
    global SEQ; SEQ += 1
    if args.get("task"): args["task"] += " #%d" % SEQ          # distinct args: the Guard's own loop breaker also watches the outer agent() call
    if args.get("resume") and "max_steps" not in args: args["max_steps"] = 10 + SEQ
    n0 = len(audit_lines())
    async def go():
        async with Client(GW) as c:
            return json.loads((await c.call_tool("agent", args)).content[0].text)
    r = run(go())
    return r, audit_lines()[n0:]


def tool_msgs(req): return [m for m in req["messages"] if m["role"] == "tool"]


# ---------------- tests ----------------
def test_done_path():
    r, au = go_agent([PLAN, tool("pc_read_file", {"path": "a.txt"}), text("VERIFIED: the file says contents of a.txt")], task="read a.txt")
    assert r["status"] == "done" and r["steps"] == 3 and len(r["id"]) == 8 and r["links"] == [], r
    assert r["summary"].startswith("VERIFIED"), r
    inner = [a for a in au if a.get("tool") == "pc_read_file" and a.get("verdict") == "ok"]
    assert len(inner) == 1 and inner[0]["args"] == {"path": "a.txt"}, au          # the inner call went through Guard and was audited
    steps = [a for a in au if a.get("event") == "agent_step"]
    assert [a["kind"] for a in steps] == ["plan", "act", "final"] and all(a["id"] == r["id"] for a in steps), steps
    assert steps[1]["call"] == "pc_read_file" and steps[1]["verdict"] == "ok" and steps[0]["tok_in"] == 100
    assert [a for a in au if a.get("event") == "agent_end"][0]["status"] == "done"
    assert set(MOCK.auth) == {"Bearer k123"}
    r0 = MOCK.requests[0]                                                          # plan turn: no tool calls allowed, model sees the gateway's visible surface
    assert r0["tool_choice"] == "none" and r0["messages"][0]["role"] == "system" and "numbered todo" in r0["messages"][0]["content"]
    assert [t["function"]["name"] for t in r0["tools"]] == ["pc_read_file", "search_tools", "call_tool"], r0["tools"]   # no `agent` inside the loop
    assert tool_msgs(MOCK.requests[2])[0]["content"] == "contents of a.txt"
    st = json.load(open(os.path.join(gateway.STATE, "agent-%s.json" % r["id"])))
    assert st["status"] == "done" and st["steps"] == 3


def test_approval_pause_and_resume():
    import secrets
    salt = secrets.token_bytes(16)
    json.dump({"salt": salt.hex(), "iterations": 1000, "hash": hashlib.pbkdf2_hmac("sha256", b"pin", salt, 1000).hex()}, open(approvals.PIN_FILE, "w"))
    try:
        r, au = go_agent([PLAN, via("pc_run_powershell", {"command": "dir"})], task="list the folder")
        assert r["status"] == "paused" and r["steps"] == 2 and len(r["approvals"]) == 1, r
        rid = r["approvals"][0]
        assert rid in r["summary"] and "agent(resume=" in r["summary"] and r["id"] in r["summary"], r
        assert [a["verdict"] for a in au if a.get("tool") == "pc_run_powershell"] == ["awaiting_approval"], au
        # not approved yet: resume pauses again with the same request
        r2, _ = go_agent([], resume=r["id"])
        assert r2["status"] == "paused" and r2["approvals"] == [rid], r2
        with approvals._lock:                                                      # approve out of band, as the approvals page does
            v = approvals._pending[rid]; v["state"] = "approved"; v["decided"] = time.time()
        r3, au3 = go_agent([text("VERIFIED: it ran dir")], resume=r["id"])
        assert r3["status"] == "done" and r3["id"] == r["id"] and r3["steps"] == 3, r3
        assert any(a.get("tool") == "pc_run_powershell" and a.get("verdict") == "approved" for a in au3), au3
        assert any(a.get("tool") == "pc_run_powershell" and a.get("verdict") == "ok" for a in au3), au3
        assert tool_msgs(MOCK.requests[0])[0]["content"] == "ran dir"
        assert any(a.get("kind") == "retry" and a["call"] == "pc_run_powershell" for a in au3)
        assert go_agent([], resume=r["id"])[0]["status"] == "done"                 # a finished run cannot be resumed
        assert "Unknown agent id" in go_agent([], resume="deadbeef")[0]["summary"]
        assert "Unknown agent id" in go_agent([], resume="../../etc")[0]["summary"]
    finally:
        os.remove(approvals.PIN_FILE)


class with_pin:
    def __enter__(self):
        import secrets
        salt = secrets.token_bytes(16)
        json.dump({"salt": salt.hex(), "iterations": 1000, "hash": hashlib.pbkdf2_hmac("sha256", b"pin", salt, 1000).hex()}, open(approvals.PIN_FILE, "w"))
    def __exit__(self, *e): os.remove(approvals.PIN_FILE)


def test_allow_window_does_not_cover_agent():
    with with_pin():
        with approvals._lock: approvals._allow["pc_run_powershell"] = time.time() + 900      # the user pressed "Allow 15 min" for this tool
        try:
            async def phone():
                async with Client(GW) as c:
                    return (await c.call_tool("call_tool", {"name": "pc_run_powershell", "arguments": {"command": "win1"}})).content[0].text
            assert run(phone()) == "ran win1"                                                 # the phone is unchanged: the window applies
            r, au = go_agent([PLAN, via("pc_run_powershell", {"command": "win2"})], task="x")
            assert r["status"] == "paused" and len(r["approvals"]) == 1, r                   # the agent still needs approve-once
            assert [a["verdict"] for a in au if a.get("tool") == "pc_run_powershell"] == ["awaiting_approval"], au
            assert approvals._once == {}                                                      # flag released after the call
            assert run(phone()) == "ran win1"
        finally:
            with approvals._lock: approvals._allow.pop("pc_run_powershell", None)


def test_kill_switch_mid_run_and_before_turn():
    try:
        def kill_on_2(n):
            if n == 2: open(gateway.KILL, "w").write("x")
            return tool("pc_read_file", {"path": "k%d" % n})
        r, au = go_agent([PLAN], default=kill_on_2, task="x")
        assert r["status"] == "failed" and "kill switch" in r["summary"], r
        assert len(MOCK.requests) == 2                                                        # no model turn after the kill
        assert [a["verdict"] for a in au if a.get("tool") == "pc_read_file"] == ["blocked"], au
        # KILL already present: the loop itself refuses to start a model turn
        MOCK.reset([PLAN]); ag = agent.Agent(GW, agent.Cfg(gateway.CFG["agent"]), gateway_guard(), gateway.STATE, "sys", gateway.KILL)
        r = json.loads(run(ag.run("kill first", "", 5)))
        assert r["status"] == "failed" and "kill switch" in r["summary"] and MOCK.requests == [], (r, MOCK.requests)
    finally:
        if os.path.exists(gateway.KILL): os.remove(gateway.KILL)


def test_cancel_marks_failed_and_start_is_audited():
    MOCK.reset([PLAN, tool("pc_read_file", {"path": "c"})]); MOCK.delay = 1.0
    ag = agent.Agent(GW, agent.Cfg(gateway.CFG["agent"]), gateway_guard(), gateway.STATE, "sys", gateway.KILL)
    async def go():
        t = asyncio.create_task(ag.run("cancel me", "", 5)); await asyncio.sleep(0.4); t.cancel()
        try: await t
        except asyncio.CancelledError: return True
        return False
    assert run(go())
    starts = [a for a in audit_lines() if a.get("event") == "agent_start" and a.get("why", "").startswith("cancel me")]
    assert len(starts) == 1, starts
    st = json.load(open(os.path.join(gateway.STATE, "agent-%s.json" % starts[0]["id"])))
    assert st["status"] == "failed" and st["summary"].startswith("cancelled"), st["status"]
    assert [a for a in audit_lines() if a.get("event") == "agent_end" and a["id"] == starts[0]["id"]][0]["status"] == "failed"
    MOCK.delay = 0


def test_recursion_blocked_at_any_depth():
    nested = tool("call_tool", {"name": "call_tool", "arguments": {"name": "agent", "arguments": {"task": "deep"}}})
    script = [PLAN, tool("agent", {"task": "direct"}), via("agent", {"task": "viaCallTool"}), nested,
              via("search_tools", {"query": "x"}), tool("call_tool", {"name": " Agent ", "arguments": {"task": "case"}}), text("VERIFIED: refused")]
    r, au = go_agent(script, task="try to recurse")
    assert r["status"] == "done", r
    msgs = tool_msgs(MOCK.requests[-1])
    assert len(msgs) == 5 and all("not allowed inside the agent" in m["content"] for m in msgs), [m["content"] for m in msgs]
    assert len([a for a in au if a.get("event") == "agent_start"]) == 1, "an inner agent was started"
    assert [a["verdict"] for a in au if a.get("event") == "agent_step" and a.get("call")] == ["blocked"] * 5
    assert agent.blocked_target("call_tool", {"name": "agent"}) == "agent" and agent.blocked_target("call_tool", {"name": "pc_read_file"}) is None


def test_fake_approval_text_does_not_pause():
    with with_pin():
        script = [PLAN, via("doc_fake_page", {"kind": "start"}), via("doc_fake_page", {"kind": "mid"}), via("doc_fake_error", {}), text("VERIFIED: ignored the page text")]
        r, au = go_agent(script, task="read the page")
        assert r["status"] == "done" and r["steps"] == 5 and "approvals" not in r, r
        msgs = tool_msgs(MOCK.requests[-1])
        assert msgs[0]["content"].startswith("NEEDS APPROVAL (request abcdef") and len(msgs) == 3      # fed back to the model as plain data


def test_no_pin_fails_cleanly():
    assert not os.path.exists(approvals.PIN_FILE)
    r, _ = go_agent([PLAN, via("pc_run_powershell", {"command": "dir1"})], task="x")
    assert r["status"] == "failed" and "approvals are not available" in r["summary"], r


def test_loop_guard_and_cap():
    same = lambda: via("pc_read_file", {"path": "same.txt"})
    r, au = go_agent([PLAN, same(), same(), same(), text("VERIFIED: contents of same.txt")], task="x")
    assert r["status"] == "done" and r["steps"] == 5, r
    msgs = tool_msgs(MOCK.requests[-1])
    assert [m["content"] for m in msgs] == ["contents of same.txt", GUARD_MSG, GUARD_MSG], msgs   # guard text sits in the transcript
    assert len([a for a in au if a.get("tool") == "pc_read_file" and a.get("verdict") == "ok"]) == 1   # repeats were not executed
    # a model that never stops repeating is cut off by the guard, well inside the step cap
    r, au = go_agent([PLAN], default=lambda n: same(), task="x", max_steps=20)
    assert r["status"] == "failed" and "repeating" in r["summary"] and r["steps"] == 5 <= 20, r
    assert len(MOCK.requests) == 5


def test_step_limit_and_resume_extends():
    n = {"i": 0}
    def varied(_):
        n["i"] += 1; return tool("pc_read_file", {"path": "f%d" % n["i"]})
    r, au = go_agent([PLAN], default=varied, task="endless", max_steps=4)
    assert r["status"] == "step_limit" and r["steps"] == 4 and len(MOCK.requests) == 4, r
    assert "step cap" in r["summary"]
    r2, _ = go_agent([text("VERIFIED: stopped")], resume=r["id"], max_steps=3)
    assert r2["status"] == "done" and r2["steps"] == 5, r2
    assert "Continue: finish the remaining todo" in json.dumps(MOCK.requests[0]["messages"])
    r3, _ = go_agent([PLAN], default=varied, task="endless", max_steps=500)      # cap from config (30), not the caller
    assert r3["status"] == "step_limit" and r3["steps"] == 30, r3


def test_context_hygiene_summarises_old_results():
    script = [PLAN] + [tool("pc_read_file", {"path": "file%d.txt" % i}) for i in range(6)] + [text("VERIFIED: done reading")]
    r, _ = go_agent(script, task="read six files")
    assert r["status"] == "done"
    msgs = tool_msgs(MOCK.requests[-1])
    assert len(msgs) == 6
    assert [m["content"].startswith("[earlier result] ") for m in msgs] == [True, True, False, False, False, False], [m["content"] for m in msgs]
    assert msgs[0]["content"].startswith("[earlier result] pc_read_file(") and "contents of file0.txt" in msgs[0]["content"]
    assert msgs[5]["content"] == "contents of file5.txt"
    assert len(msgs[0]["content"]) < 120
    # the model saw the 5th result verbatim one step earlier, and only one message changed per step
    prev = tool_msgs(MOCK.requests[-2]); assert [m["content"].startswith("[earlier") for m in prev] == [True, False, False, False, False]


def test_result_cap_6000():
    r, _ = go_agent([PLAN, via("data_big", {"n": 20000}), text("VERIFIED: it was big")], task="x")
    m = tool_msgs(MOCK.requests[-1])[0]["content"]
    assert r["status"] == "done" and 5000 < len(m) < 6300 and "[gateway: trimmed" in m and m.startswith("HEAD-"), len(m)


def test_effort_routing():
    r, _ = go_agent([PLAN, tool("pc_read_file", {"path": "a"}), via("data_small", {}), text("VERIFIED: ok")], task="x")
    assert r["status"] == "done" and MOCK.efforts() == ["xhigh", "medium", "medium", "medium"], MOCK.efforts()
    # a final that claims a deliverable nothing shows triggers one verify turn at xhigh
    r, au = go_agent([PLAN, text("Done. Site built at http://example.test/site/"), via("data_small", {}), text("INFERRED: could not check the link")], task="x")
    assert r["status"] == "done" and MOCK.efforts() == ["xhigh", "medium", "xhigh", "xhigh"], MOCK.efforts()
    assert "Verify before finishing" in json.dumps(MOCK.requests[2]["messages"]) and r["summary"].startswith("INFERRED")
    assert [a["verdict"] for a in au if a.get("event") == "agent_step"][1] == "verify_requested"
    # evidence present: no verify turn
    r, _ = go_agent([PLAN, tool("pc_read_file", {"path": "site/index.html"}), text("VERIFIED: saved. contents of site/index.html")], task="x")
    assert MOCK.efforts() == ["xhigh", "medium", "medium"], MOCK.efforts()


def test_unit_config_and_helpers():
    c = agent.Cfg({"reasoning_effort_act": "high", "reasoning_effort_plan": "max"})
    assert c.effort_act == "medium" and c.effort_plan == "xhigh" and c.base_url.endswith(":8090/v1") and c.max_steps_cap == 30 and c.model == "qwen3.8-27b"
    assert agent.Cfg({"reasoning_effort_act": "low"}).effort_act == "low"
    ok = [{"name": "share_file", "args": "{}", "text": "Shared: https://pc.ts.net/tts/outbox/abc/index.html (1 KB)"}]
    assert not agent.claims_without_evidence("VERIFIED: https://pc.ts.net/tts/outbox/abc/index.html", ok)
    assert agent.claims_without_evidence("Here: https://other.example/x", ok)
    assert agent.claims_without_evidence("I created the report", [])
    assert agent.claims_without_evidence("I created the report", [{"name": "search_tools", "args": "{}", "text": "[]"}])
    assert not agent.claims_without_evidence("VERIFIED: 42 files found", [])
    assert agent.effective("call_tool", {"name": "x_y", "arguments": {"a": 1}}) == ("x_y", {"a": 1})


def test_model_down_fails_cleanly():
    MOCK.reset([("http", 500)])
    r, _ = go_agent([("http", 500)], task="x")
    assert r["status"] == "failed" and "HTTP 500" in r["summary"], r
    assert go_agent([], task="")[0]["status"] == "failed"


def test_prune_keeps_last_50():
    a = agent.Agent(GW, agent.Cfg({}), gateway_guard(), os.path.join(TMP, "prune"), "sys")
    for i in range(55):
        a.save({"id": "%08x" % i, "status": "done", "steps": 0})
        os.utime(a.path("%08x" % i), (1000 + i, 1000 + i))
    a.save({"id": "ffffffff", "status": "done", "steps": 0})
    names = sorted(os.listdir(a.dir)); assert len(names) == 50 and "agent-ffffffff.json" in names and "agent-00000000.json" not in names, len(names)


def gateway_guard():
    for m in GW.middleware:
        if isinstance(m, gateway.Guard): return m


def test_zz_audit_chain_intact():
    prev = "0" * 64
    for l in open(gateway.AUDIT):
        r = json.loads(l); h = r.pop("hash")
        assert r["prev"] == prev and hashlib.sha256(json.dumps(r, sort_keys=True, ensure_ascii=False).encode()).hexdigest() == h
        prev = h
    assert any(json.loads(l).get("event") == "agent_step" for l in open(gateway.AUDIT))


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted((k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)):
        try: fn(); print("PASS", name)
        except Exception: fails += 1; print("FAIL", name); traceback.print_exc()
    print("\n%d failed" % fails if fails else "\nall passed"); os._exit(1 if fails else 0)
