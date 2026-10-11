"""Lazy tool gateway for a local LLM: a constant, tiny tool surface in front of many MCP servers.

Why: Qwen's chat template writes every tool schema at the very start of the prompt, so any change to the tool
set throws away the whole prompt cache, and every loaded schema costs tokens on every request. This gateway
shows the model only a few pinned basics plus `search_tools` and `call_tool`. Everything else costs nothing
until the model searches for it; search results land at the end of the conversation, so the cache survives.

Built on FastMCP (Apache-2.0): create_proxy + BM25SearchTransform + Middleware. Guard ideas from
mcpproxy-go (read/write/destructive intent) and agentguard (kill switch, hash-chained audit log, loop breaker).

Run:   uv run --with fastmcp==3.4.8 python gateway.py [gateway.json]      (stdio MCP server)
Behind mcpo:  "gw": {"command": "...python.exe", "args": ["C:/AI/gateway/gateway.py"]}
Manual control: edit gateway.json (pin / hide / deny), or create the KILL file to stop all tool calls.
"""
import time
T0 = time.time()
import asyncio, difflib, fnmatch, hashlib, json, os, re, sys
from collections import deque

from mcp.types import TextContent
from fastmcp.exceptions import ToolError
from fastmcp.server import create_proxy
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.transforms import Transform
from fastmcp.server.transforms.search import BM25SearchTransform
import fastmcp.server.transforms.search.bm25 as _bm25
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import approvals, skills

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "gateway.json")
CFG = json.load(open(CFG_PATH, encoding="utf-8-sig"))
POLICY = CFG.get("policy", {})
STATE = os.environ.get("GW_STATE_DIR") or os.path.join(HERE, "state"); os.makedirs(STATE, exist_ok=True)
AUDIT = os.path.join(STATE, "audit.jsonl")
KILL = os.path.join(HERE, "KILL")
META = {"search_tools", "call_tool"}
MAX_CHARS = int(POLICY.get("max_result_chars", 12000) or 0)   # 0 = never trim results


def match_any(name, patterns):
    """Case-insensitive glob match (tool names are mixed case, e.g. pc_PowerShell)."""
    n = name.lower()
    return any(fnmatch.fnmatchcase(n, p.lower()) for p in patterns or [])


# ---------- better search: aliases + light stemming on top of FastMCP's BM25 ----------
_orig_extract = _bm25._extract_searchable_text
_orig_tokenize = _bm25._tokenize
ALIASES = CFG.get("aliases", {})


def _alias_text(tool):
    extra = [v for k, v in ALIASES.items() if fnmatch.fnmatchcase(tool.name, k)]
    return _orig_extract(tool) + (" " + " ".join(extra) if extra else "")


def _stem(t):
    for suf in ("ing", "ies", "es", "ed", "s"):
        if len(t) > len(suf) + 2 and t.endswith(suf):
            return t[: -len(suf)] + ("y" if suf == "ies" else "")
    return t


_bm25._extract_searchable_text = _alias_text
_bm25._tokenize = lambda text: [_stem(t) for t in _orig_tokenize(text)]


# ---------- hide tools nobody should see (agent-only, dangerous or duplicate) ----------
class Hide(Transform):
    async def transform_tools(self, tools):
        return [t for t in tools if not match_any(t.name, CFG.get("hide"))]


class Search(BM25SearchTransform):
    """BM25 search over the full catalogue minus hidden tools (the catalogue lookup bypasses other transforms)."""
    guard = None
    ready = False

    async def _get_visible_tools(self, ctx):
        return [t for t in await super()._get_visible_tools(ctx) if not match_any(t.name, CFG.get("hide"))]

    async def transform_tools(self, tools):
        """`tools` is the full catalogue here, so the first listing tells us how many tools came up and how long it took."""
        if not self.ready:
            self.ready = True
            n = len([t for t in tools if not match_any(t.name, CFG.get("hide"))])
            m = len([k for k, v in CFG.get("servers", {}).items() if not v.get("disabled")])
            msg = "ready: %d tools from %d servers in %.1f s" % (n, m, time.time() - T0)
            print(msg, file=sys.stderr)
            if self.guard: self.guard.audit(event="ready", why=msg)
        return await super().transform_tools(tools)


class Describe(Transform):
    """Replace the descriptions of search_tools, call_tool, skills and pinned tools with the usage rules from CFG["descriptions"].
    Only text changes: names and schemas stay as they are, and the order is fixed (pins in config order, then search_tools, call_tool),
    so the tool block at the top of the prompt is byte-identical on every request and the prompt cache survives."""
    def text_for(self, name):
        d = CFG.get("descriptions") or {}
        if name in d: return d[name]
        for pat, text in d.items():
            if match_any(name, [pat]): return text
        return None

    async def list_tools(self, tools):
        pins = {n: i for i, n in enumerate(CFG.get("pin", []))}
        out = [t.model_copy(update={"description": self.text_for(t.name)}) if self.text_for(t.name) else t for t in tools]
        out.sort(key=lambda t: (0, pins[t.name], "") if t.name in pins else
                 (1, ("search_tools", "call_tool").index(t.name), "") if t.name in META else (2, 0, t.name))
        return out


def compact(tools):
    """Search results go into the conversation, so keep them short: name, trimmed description, input schema."""
    out = []
    for t in tools:
        schema = json.loads(json.dumps(t.parameters or {}))
        for p in (schema.get("properties") or {}).values():
            if isinstance(p, dict):
                p.pop("title", None)
                if len(p.get("description", "")) > 160: p["description"] = p["description"][:157] + "..."
        schema.pop("title", None)
        d = (t.description or "").strip().split("\n\n")[0]
        out.append({"name": t.name, "description": d[:300], "input_schema": schema})
    return json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\nTo use one: call_tool(name=<name>, arguments={...matching input_schema})."


def trim_result(res, limit):
    """Cut every text block longer than `limit` to head + tail + a note; other content passes. Returns (chars_in, chars_out)."""
    cin = cout = 0
    for c in getattr(res, "content", None) or []:
        if isinstance(c, TextContent):
            cin += len(c.text)
            if limit and len(c.text) > limit:
                c.text = skills.trim(c.text, limit)
                res.structured_content = None     # would duplicate the full text
            cout += len(c.text)
    return cin, cout


# ---------- guard: kill switch, deny rules, intent classes, loop breaker, hash-chained audit ----------
class Guard(Middleware):
    def __init__(self):
        self.search, self.names = None, set()
        self.recent = deque(maxlen=200)
        self.prev = "0" * 64
        if os.path.exists(AUDIT):
            try:
                last = open(AUDIT, encoding="utf-8").read().strip().splitlines()[-1]
                self.prev = json.loads(last)["hash"]
            except Exception:
                pass

    def audit(self, **rec):
        rec = dict(ts=time.strftime("%Y-%m-%dT%H:%M:%S"), prev=self.prev, **rec)
        rec["hash"] = hashlib.sha256(json.dumps(rec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        self.prev = rec["hash"]
        with open(AUDIT, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def intent(self, name):
        for cls in ("destructive", "write", "read"):
            if match_any(name, POLICY.get(cls)):
                return cls
        return POLICY.get("default_intent", "write")

    async def known(self, ctx, target):
        """Is `target` a real tool? Cached names first; one catalogue fetch on a miss (so a newly started server is picked up)."""
        if target in self.names:
            return True
        self.names = {t.name for t in await self.search.get_tool_catalog(ctx)}
        return target in self.names

    async def suggest(self, ctx, target):
        tools = await self.search._get_visible_tools(ctx)
        names = [t.name for t in tools] + [n for n in CFG.get("pin", []) if n in self.names]
        low = {n.lower(): n for n in names}
        close = [low[m] for m in difflib.get_close_matches(target.lower(), list(low), n=3, cutoff=0.5)]
        words = re.sub(r"[_\W]+", " ", re.sub(r"([a-z])([A-Z])", r"\1 \2", target))
        found = close + [t.name for t in await self.search._search(tools, words) if t.name not in close]
        return "Unknown tool %s. Closest: %s. Use search_tools to see arguments." % (target, ", ".join(found[:3]) or "(none)")

    def check(self, name, args, count=True):
        if os.path.exists(KILL):
            return "KILLED: the gateway kill switch is on (delete C:/AI/gateway/KILL to resume)"
        if match_any(name, CFG.get("hide")):
            return "not available: %s is hidden by policy" % name
        if match_any(name, POLICY.get("deny_tools")):
            return "denied by policy: %s" % name
        blob = json.dumps(args, ensure_ascii=False)
        for rule in POLICY.get("deny_args", []):
            if match_any(name, rule.get("tools", ["*"])) and re.search(rule["pattern"], blob, re.I):
                if rule.get("verdict") == "approval":
                    return ("approve", rule.get("why", "needs approval"))
                return "denied by policy (%s): %s" % (rule.get("why", "dangerous argument"), name)
        cls = self.intent(name)
        if not count:
            return None
        now = time.time()
        self.recent.append((now, name, blob))
        win = [r for r in self.recent if now - r[0] < POLICY.get("loop_window_s", 300)]
        if len(win) > POLICY.get("max_calls_per_window", 60):
            return "rate limit: too many tool calls in a short time; stop and summarise for the user"
        for pat, cap in (POLICY.get("per_tool_limits") or {}).items():
            if match_any(name, [pat]) and sum(1 for r in win if match_any(r[1], [pat])) > cap:
                return "rate limit for %s: too many calls in a short time; stop and check with the user" % pat
        if sum(1 for r in win if r[1] == name and r[2] == blob) >= POLICY.get("max_identical_calls", 4):
            return "loop detected: the same call was repeated; change approach or report the problem"
        if cls == "destructive" and not POLICY.get("allow_destructive", False):
            return ("approve", "%s deletes or removes something" % name)
        if cls in POLICY.get("confirm_intents", ["write", "destructive"]):
            return ("approve", "%s changes something on the PC or in a browser" % name)
        return None

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        name = context.message.name
        args = dict(context.message.arguments or {})
        if name == "call_tool":  # defence in depth: vet the target here too (FastMCP re-enters with the real name)
            target, targs = str(args.get("name") or ""), dict(args.get("arguments") or {})
            why = self.check(target, targs, count=False)
            if why and not isinstance(why, tuple):
                self.audit(tool=target, intent=self.intent(target), args=targs, verdict="blocked", why=why)
                raise ToolError(why)
            if self.search and not isinstance(why, tuple) and not await self.known(context.fastmcp_context, target):
                msg = await self.suggest(context.fastmcp_context, target)
                self.audit(tool=target, intent="unknown", args=targs, verdict="blocked", why=msg[:200])
                raise ToolError(msg)
            return await call_next(context)
        if name in META:
            return await call_next(context)
        why = self.check(name, args)
        if isinstance(why, tuple):  # needs the user's approval, given out of band on the approvals page
            state, msg = approvals.request(name, args, why[1])
            if state != "run":
                if self.recent: self.recent.pop()   # waiting for the user is not a repeat: don't let it trip the loop breaker
                self.audit(tool=name, intent=self.intent(name), args=args, verdict="awaiting_approval", why=msg[:200])
                raise ToolError(msg)
            self.audit(tool=name, intent=self.intent(name), args=args, verdict="approved")
        elif why:
            self.audit(tool=name, intent=self.intent(name), args=args, verdict="blocked", why=why)
            raise ToolError(why)
        t0 = time.time()
        try:
            res = await call_next(context)
            cin, cout = trim_result(res, MAX_CHARS)
            self.audit(tool=name, intent=self.intent(name), args=args, verdict="ok", ms=int((time.time() - t0) * 1000),
                       chars_in=cin, chars_out=cout)
            return res
        except Exception as e:
            self.audit(tool=name, intent=self.intent(name), args=args, verdict="error", why=str(e)[:300])
            raise


def register_local(server):
    """Local tools that live in the gateway itself: skills (here) and share_file (outbox.py, if present next to this file)."""
    skills.register(server, CFG, MAX_CHARS)
    try:
        import outbox
    except ImportError as e:
        print("outbox not loaded: %s" % e, file=sys.stderr)
        return
    outbox.register(server, CFG)


def _probe_servers(servers):
    """Optional servers (e.g. the user's Chrome, which waits for the browser extension) must answer list_tools within
    probe_timeout_s or they are skipped, so one absent app can never stall the whole gateway. Probes run in parallel."""
    import asyncio
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    async def one(name, v):
        try:
            env = dict(os.environ, **(v.get("env") or {}))
            async with Client(StdioTransport(command=v["command"], args=v.get("args", []), env=env, keep_alive=False)) as c:
                await asyncio.wait_for(c.list_tools(), timeout=v.get("probe_timeout_s", 12))
            return name
        except BaseException as e:   # timeout, crash, missing binary
            sys.stderr.write("gateway: optional server %s skipped (%s)\n" % (name, type(e).__name__))
            return None
    async def run_all():
        return await asyncio.gather(*(asyncio.wait_for(one(n, v), v.get("probe_timeout_s", 12) + 5) for n, v in servers.items()), return_exceptions=True)
    import concurrent.futures
    try:   # own thread + loop, so this works whether or not the caller already runs an event loop
        with concurrent.futures.ThreadPoolExecutor(1) as ex:
            res = ex.submit(asyncio.run, run_all()).result()
    except Exception as e:
        sys.stderr.write("gateway: probe failed (%s); optional servers skipped\n" % type(e).__name__)
        return set()
    return {r for r in res if isinstance(r, str)}


def build():
    """One persistent stdio client per downstream server (kept alive between calls), mounted under its name: tools are <server>_<tool>."""
    from fastmcp import FastMCP, Client
    from fastmcp.client.transports import StdioTransport
    prompt = os.path.join(HERE, CFG.get("instructions_file", os.path.join("prompts", "phone-system.md")))
    instructions = open(prompt, encoding="utf-8-sig").read().strip() if os.path.exists(prompt) else None
    gw = FastMCP(CFG.get("name", "gateway"), instructions=instructions)
    probe = [n for n, v in CFG["servers"].items() if v.get("optional") and not v.get("disabled")]
    ok_optional = _probe_servers({n: CFG["servers"][n] for n in probe}) if probe else set()
    for name, v in CFG["servers"].items():
        if v.get("disabled") or (name in probe and name not in ok_optional):
            continue
        env = dict(os.environ, **(v.get("env") or {}))
        client = Client(StdioTransport(command=v["command"], args=v.get("args", []), env=env, keep_alive=True))
        gw.mount(create_proxy(client, name=name), namespace=name)
    register_local(gw)
    guard = Guard()
    search = Search(max_results=CFG.get("max_results", 4), always_visible=CFG.get("pin", []), search_result_serializer=compact)
    search.guard, guard.search = guard, search
    # Server-side agent loop (agent.py), opt-in via the "agent" config block. Policy: list `agent` under "read": the tool itself
    # changes nothing and every inner call goes back through this gateway's Guard (approvals, deny rules, trim, audit).
    import agent as _agent
    _agent.register(gw, CFG, guard, STATE, HERE, KILL)
    # Local video generation (video.py) and its browser front end (studio.py), opt-in via the "video" config block.
    # Policy: video_workflows, video_status, video_result and video_queue are "read"; video_generate and video_cancel stay "write" (PIN approval).
    import video as _video
    def _share_clip(path):
        try:
            import outbox
            return outbox.share(path, False, CFG)["url"]
        except Exception:
            return ""
    vq = _video.register(gw, CFG, STATE, HERE, KILL, share_fn=_share_clip)
    if vq is not None and vq.cfg.enabled:
        import studio as _studio
        _studio.register(approvals, vq, vq.cfg, HERE)
    gw.add_transform(Hide())
    gw.add_transform(search)
    gw.add_transform(Describe())
    gw.add_middleware(guard)
    approvals.start()
    return gw


if __name__ == "__main__":
    build().run(show_banner=False)
