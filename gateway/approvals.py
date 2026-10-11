"""Out-of-band approvals for the lazy tool gateway.

A tool call that changes something (write/destructive intent, or an "approval" deny rule) is not run straight away. The gateway
records it here and tells the model to ask the user. The user opens the approvals page on their phone (tailnet only, behind a PIN
the model never sees), approves it once or allows that tool for a short time, and the model repeats the same call, which now runs.
The model cannot approve its own calls: approval needs the PIN, and the pending list lives only in this process's memory.

Page: http://127.0.0.1:8093/approvals (published on the tailnet through the voice server's /tts/approvals route).
PIN: set once on the PC with set-approval-pin.ps1 (stored as a PBKDF2 hash in approval-pin.json). No PIN set = nothing can be approved.
"""
import fnmatch, hashlib, hmac, html, json, mimetypes, os, re, secrets, shutil, sys, threading, time, urllib.error, urllib.request
from urllib.parse import quote, unquote, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PIN_FILE = os.path.join(HERE, "approval-pin.json")
PORT = int(os.environ.get("GW_APPROVAL_PORT", "8093"))
# Where the user approves. The phone instance (behind mcpo) is published on the tailnet; a desktop agent instance runs its
# own page on another port, e.g. GW_APPROVAL_PORT=8094 and GW_APPROVAL_URL=http://127.0.0.1:8094/approvals
PAGE_URL = os.environ.get("GW_APPROVAL_URL", "https://<this PC>.ts.net:8445/tts/approvals")
_bound = {"ok": False, "err": ""}
PENDING_TTL = 15 * 60        # an unanswered request expires after 15 minutes
APPROVED_TTL = 10 * 60       # an approval must be used within 10 minutes
SESSION_TTL = 12 * 3600      # PIN login lasts 12 hours on that phone
MAX_FAILS, LOCK_S = 5, 15 * 60
sys.path.insert(0, HERE)
import outbox
OUT_CSP = "sandbox allow-scripts allow-forms allow-popups allow-downloads"   # model-authored HTML gets an opaque origin: no cookies
GOV_MODE_FILE = os.environ.get("GOV_MODE_FILE", r"C:\AI\governor\mode.txt")
MODES = ("AUTO", "MAX", "BALANCED", "LEAN")

# ---- Control Centre (spec sections 6.3 to 6.5) ----
STATE_DIR = os.environ.get("GW_STATE_DIR") or os.path.join(HERE, "state")
KILL_FILE = os.path.join(HERE, "KILL")
GOV_REQUEST_FILE = os.environ.get("GOV_REQUEST_FILE", r"C:\AI\governor\request.json")
GOV_PROFILES = os.environ.get("GOV_PROFILES", r"C:\AI\governor\profiles.json")
GOV_SLOTS_DIR = os.environ.get("GOV_SLOTS_DIR", "")            # empty: read slots.dir from profiles.json
LLAMA_URL = os.environ.get("CC_LLAMA_URL", "http://127.0.0.1:10001")
CURRENT_JSON = os.environ.get("CC_CURRENT_JSON", r"C:\AI\governor\public\current.json")
RATE = {"control": 2.0, "model": 5.0, "slot": 5.0, "kill": 5.0, "start": 10.0, "cancel": 5.0}   # seconds between calls, per action
BODY_MAX = 16384
MODEL_ACTIONS = ("load", "unload", "reload")
EFFORTS = ("xhigh", "medium", "low")
SLOT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,119}$")
RUN_ID_RE = re.compile(r"^[0-9a-f]{8}$")
_agent = None      # the agent.Agent of this process (set by agent.register through attach())
_guard = None      # the gateway Guard: owns the hash-chained audit log
_extra_max = {}    # route key -> max POST body in bytes (uploads); everything else is capped at BODY_MAX
GPU_BUSY = None   # set by studio.register: callable returning True while a video render holds the GPU (mode/model changes are refused)
_extra = {}        # "GET /approvals/x" or "POST /approvals/x" -> handler(req) -> (status, body, ctype); filled by register_extra()
_rate = {}
_audit_lock = threading.RLock()

_lock = threading.Lock()
_pending = {}    # id -> {id, key, tool, args, why, created, state: pending|approved|denied, decided}
_allow = {}      # tool name -> expiry (allow this tool for a while)
_sessions = {}   # token -> expiry
_fails = {"n": 0, "until": 0.0}
_once = {}       # call key -> count: calls made by the agent loop; "Allow 15 min" tool windows do not apply to them
_once_run = {}   # call key -> (run id, step) of the agent run making that call (shown on the approval card)


def call_key(tool, args):
    return hashlib.sha256((tool + "\n" + json.dumps(args, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()


class once_only:
    """Context manager used by agent.py around its own tool calls: while active, a tool-wide allow window is ignored for that exact
    call, so the agent needs approve-once for every change. The phone's normal behaviour is unchanged."""
    def __init__(self, tool, args, run=None, step=None): self.key, self.run, self.step = call_key(tool, args), run, step
    def __enter__(self):
        with _lock:
            _once[self.key] = _once.get(self.key, 0) + 1
            if self.run: _once_run[self.key] = (self.run, self.step)
    def __exit__(self, *e):
        with _lock:
            _once[self.key] = _once.get(self.key, 1) - 1
            if _once[self.key] <= 0: _once.pop(self.key, None); _once_run.pop(self.key, None)


def _gc(now):
    for k in [k for k, v in _pending.items() if (v["state"] == "pending" and now - v["created"] > PENDING_TTL)
              or (v["state"] != "pending" and now - (v["decided"] or now) > APPROVED_TTL)]:
        _pending.pop(k, None)
    for k in [k for k, v in _allow.items() if v < now]:
        _allow.pop(k, None)
    for k in [k for k, v in _sessions.items() if v < now]:
        _sessions.pop(k, None)


def request(tool, args, why):
    """Called by the guard. Returns ("run", None) if approved (consumes a one-time approval), else ("wait", message)."""
    now = time.time(); key = call_key(tool, args)
    with _lock:
        _gc(now)
        if _allow.get(tool, 0) > now and key not in _once:
            return "run", None
        for v in _pending.values():
            if v["key"] == key and v["state"] == "approved":
                _pending.pop(v["id"], None)          # single use
                return "run", None
            if v["key"] == key and v["state"] == "denied":
                _pending.pop(v["id"], None)
                return "wait", "DENIED by the user. Do not retry this call; ask the user what they want instead."
        if _started and not _bound["ok"]:
            return "wait", "NEEDS APPROVAL, but this gateway cannot take approvals: " + _bound["err"] + ". Tell the user; do not try another way."
        if not os.path.exists(PIN_FILE):
            return "wait", ("NEEDS APPROVAL, but approvals are not set up on this PC (no PIN). Tell the user this action needs "
                            "approval and that they can enable approvals by running C:/AI/gateway/set-approval-pin.ps1 on the PC.")
        existing = next((v for v in _pending.values() if v["key"] == key and v["state"] == "pending"), None)
        pid = existing["id"] if existing else secrets.token_hex(3)
        if not existing:
            run = _once_run.get(key)
            _pending[pid] = dict(id=pid, key=key, tool=tool, args=args, why=why, created=now, state="pending", decided=None,
                                 origin="agent" if key in _once else "phone", run=run[0] if run else None, step=run[1] if run else None,
                                 intent=_intent(tool, why))
    return "wait", ("NEEDS APPROVAL (request %s: %s). Tell the user in one short line what you want to do and ask them to approve "
                    "request %s on their approvals page (%s). After they say it is approved, "
                    "repeat exactly the same call. Do not try another way to do it." % (pid, why, pid, PAGE_URL))


# ---------------- PIN ----------------
def _pin_ok(pin):
    try:
        j = json.load(open(PIN_FILE, encoding="utf-8-sig"))
        h = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(j["salt"]), int(j["iterations"])).hex()
        return hmac.compare_digest(h, j["hash"])
    except Exception:
        return False


# ---------------- Control Centre: shared helpers ----------------
def attach(agent=None, guard=None, state_dir=None, kill=None):
    """Called by agent.register(): gives the Control Centre routes the run store, the gateway's hash-chained audit and the KILL path."""
    global _agent, _guard, STATE_DIR, KILL_FILE
    if agent is not None: _agent = agent
    if guard is not None:
        _guard = guard
        if not getattr(guard, "_cc_locked", False):       # the chain is read-modify-write: serialise it across the agent thread and the HTTP threads
            orig = guard.audit
            def locked(**rec):
                with _audit_lock: return orig(**rec)
            guard.audit = locked; guard._cc_locked = True
    if state_dir: STATE_DIR = state_dir
    if kill: KILL_FILE = kill


def register_extra(table, max_body=None):
    """Hook for other lanes (Files, notifications). `table` maps "GET /approvals/<path>" or "POST /approvals/<path>" (a '*' matches anything)
    to handler(req) -> (status:int, body:bytes|str, ctype:str) with req = {"path", "query" (dict of lists), "body" (parsed JSON object,
    {} if none), "raw" (bytes), "authed" (bool)}. For POST routes this module already enforced the X-Requested-With header (403) and the
    PIN session (401) before calling the handler. GET handlers get req["authed"] and decide for themselves. Built-in routes cannot be replaced.
    req also carries "headers" (lowercase names). A handler may return ({"file": path, "ctype": ..., "download": name|None}, ) as its body to
    stream a file with Range support (needed for video seeking on iOS). max_body={route: bytes} raises the POST body cap for those routes."""
    for k, h in dict(table).items():
        m = re.match(r"^(GET|POST) (/approvals/\S+)$", str(k))
        if not m or not callable(h):
            raise ValueError("bad extra route %r" % (k,))
        _extra[k] = h
        if max_body and k in max_body: _extra_max[k] = int(max_body[k])


def _extra_for(method, r):
    h = _extra.get(method + " " + r)
    if h: return h
    for k, v in _extra.items():
        if "*" in k and k.startswith(method + " ") and fnmatch.fnmatchcase(method + " " + r, k): return v
    return None


def audit(**rec):
    if _guard:
        try: _guard.audit(**rec)
        except Exception: pass


def _audit_tail(max_bytes=1500000):
    """Last records of audit.jsonl (a partial first line is dropped). Read-only."""
    p = os.path.join(STATE_DIR, "audit.jsonl")
    try:
        with open(p, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - max_bytes))
            data = f.read()
    except OSError:
        return []
    lines = data.split(b"\n")
    if size > max_bytes: lines = lines[1:]
    out = []
    for l in lines:
        try: out.append(json.loads(l))
        except ValueError: pass
    return out


def _intent(tool, why=""):
    try: cls = _guard.intent(tool) if _guard else ""
    except Exception: cls = ""
    if cls == "destructive" or re.search(r"\b(delet|remov|destroy|erase|wipe|format|purge|uninstall|kill)", why or "", re.I):
        return "destructive"
    return "write"


def _clip(o, n=4000, depth=0):
    if isinstance(o, str): return o if len(o) <= n else o[:n] + "...[+%d chars]" % (len(o) - n)
    if depth > 6: return "..."
    if isinstance(o, dict): return {str(k)[:100]: _clip(v, n, depth + 1) for k, v in list(o.items())[:60]}
    if isinstance(o, list): return [_clip(v, n, depth + 1) for v in o[:60]]
    return o


def _preview(args):
    if isinstance(args, dict):
        for k in ("path", "file_path", "command", "url", "name"):
            if isinstance(args.get(k), str): return args[k][:160]
    return json.dumps(args, ensure_ascii=False)[:160]


def _card(v, now):
    return dict(id=v["id"], tool=v["tool"], why=v["why"], age=int(now - v["created"]), ttl=max(0, int(PENDING_TTL - (now - v["created"]))),
                intent=v.get("intent", "write"), origin=v.get("origin", "phone"), run=v.get("run"), step=v.get("step"),
                once_only=v.get("origin") == "agent", args=json.dumps(v["args"], indent=1, ensure_ascii=False)[:4000], args_obj=_clip(v["args"]))


def _rl(name):
    """0 if allowed now, else seconds to wait. Per action name, process wide (one owner, one PIN)."""
    now = time.time()
    with _lock:
        wait = RATE.get(name, 0) - (now - _rate.get(name, 0))
        if wait > 0: return int(wait) + 1
        _rate[name] = now
    return 0


def _http(method, url, body=None, timeout=3.0):
    """(status, parsed JSON or text). Raises OSError when the server cannot be reached."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    except Exception as e:
        raise OSError("%s: %s" % (type(e).__name__, str(e)[:120]))
    try: return code, json.loads(raw.decode("utf-8", "replace") or "null")
    except ValueError: return code, raw.decode("utf-8", "replace")[:200]


def _atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="ascii") as f: f.write(text)
    os.replace(tmp, path)


# ---------------- Control Centre: runs (6.5) ----------------
def _read_run(aid):
    if not RUN_ID_RE.match(aid or ""): return None
    try: return json.load(open(os.path.join(STATE_DIR, "agent-%s.json" % aid), encoding="utf-8"))
    except (OSError, ValueError): return None


def _status(st):
    """A run that is paused or at its cap but already relaunched shows as running at once (the file catches up a moment later)."""
    if _agent and st.get("status") in ("paused", "step_limit"):
        with _agent.lock:
            if st.get("id") in _agent.active: return "running"
    return st.get("status", "failed")


def run_summary(st):
    """The list row. Never includes `messages` (the whole transcript, tool output and all)."""
    return dict(id=st.get("id"), task=str(st.get("task", ""))[:300], status=_status(st), steps=st.get("steps", 0), created=st.get("created"),
                updated=st.get("updated"), approvals=list(st.get("approvals") or [])[:3], links=[str(u)[:400] for u in (st.get("links") or [])[:20]],
                summary=str(st.get("summary", ""))[:400], effort=st.get("effort") or "")


def list_runs():
    try: names = [n for n in os.listdir(STATE_DIR) if re.match(r"^agent-[0-9a-f]{8}\.json$", n)]
    except OSError: return []
    names.sort(key=lambda n: os.path.getmtime(os.path.join(STATE_DIR, n)), reverse=True)
    out = []
    for n in names[:50]:
        st = _read_run(n[6:14])
        if st: out.append(run_summary(st))
    return out


def run_detail(aid):
    st = _read_run(aid)
    if not st: return None
    d = run_summary(st)
    d["summary"] = str(st.get("summary", ""))[:1500]
    plan = []
    for m in st.get("messages") or []:
        if m.get("role") == "assistant" and not m.get("tool_calls") and m.get("content"):
            for line in str(m["content"]).splitlines():
                mm = re.match(r"^\s*(\d{1,2})[.)]\s+(.+)$", line)
                if mm and len(plan) < 12: plan.append({"n": int(mm.group(1)), "text": mm.group(2).strip()[:200]})
            break
    tl = []
    for r in _audit_tail():
        if r.get("id") == aid and r.get("event") in ("agent_start", "agent_step", "agent_end"):
            tl.append({k: r.get(k) for k in ("event", "step", "kind", "call", "verdict", "tok_in", "tok_out", "effort", "status") if r.get(k) is not None}
                      | {"t": r.get("ts"), "ms": r.get("call_ms") if r.get("call_ms") is not None else r.get("ms"),
                         "why": str(r.get("why", ""))[:200] if r.get("event") != "agent_step" else None})
    d["timeline"] = tl[-200:]
    done = sum(1 for r in tl if r.get("call") and r.get("verdict") == "ok")        # plan progress is INFERRED from successful calls
    for i, it in enumerate(plan):
        stt = d["status"]
        it["state"] = "done" if (i < done or stt == "done") else ("paused" if i == done and stt == "paused" else
                       "running" if i == done and stt == "running" else "todo")
    d["plan"], d["plan_inferred"] = plan, True
    d["pending"] = None
    if d["status"] == "paused" and d["approvals"]:
        now = time.time()
        with _lock:
            v = _pending.get(d["approvals"][0])
            d["pending"] = _card(v, now) if v and v["state"] == "pending" else {"id": d["approvals"][0], "expired": True}
    pc = st.get("pending")
    if pc: d["call"] = {"tool": str(pc.get("name", ""))[:80], "args": json.dumps(_clip(pc.get("args")), ensure_ascii=False)[:1500]}
    return d


def history(limit=20):
    out = []
    for r in reversed(_audit_tail()):
        if r.get("tool") == "cc.approval":
            out.append(dict(t=r.get("ts"), decision=r.get("decision"), tool=r.get("target"), id=r.get("req"), origin=r.get("origin"), preview=r.get("preview", "")))
            if len(out) >= limit: break
    return out


# ---------------- Control Centre: POST handlers (all called only after header + session checks) ----------------
def _slots_dir():
    if GOV_SLOTS_DIR: return GOV_SLOTS_DIR
    try: return json.load(open(GOV_PROFILES, encoding="utf-8-sig")).get("slots", {}).get("dir") or ""
    except (OSError, ValueError): return ""


def cc_control(data):
    act = data.get("action")
    if act not in ("reasoning_end", "cancel"): return 400, {"error": "action must be reasoning_end or cancel"}
    w = _rl("control")
    if w: return 429, {"error": "one control action per 2 s", "retry_after": w}
    try:
        if act == "reasoning_end":
            try: cur = json.load(open(CURRENT_JSON, encoding="utf-8-sig"))
            except (OSError, ValueError): cur = {}
            if not cur.get("id") or not cur.get("thinking"): return 409, {"error": "the model is not thinking right now"}
            code, res = _http("POST", LLAMA_URL.rstrip("/") + "/v1/chat/completions/control", {"id": str(cur["id"]), "action": "reasoning_end"})
            ok = 200 <= code < 300
        else:
            code, slots = _http("GET", LLAMA_URL.rstrip("/") + "/slots")
            busy = [s for s in slots if isinstance(s, dict) and s.get("is_processing")] if isinstance(slots, list) else []
            if code != 200 or not busy: return 409, {"error": "nothing is generating right now"}
            code, res = _http("POST", LLAMA_URL.rstrip("/") + "/slots/%d?action=erase" % int(busy[0].get("id", 0)))
            ok = 200 <= code < 300
    except OSError as e:
        audit(tool="cc.control", intent="write", by="phone", action=act, verdict="error", why=str(e)[:160])
        return 502, {"error": "llama-server is not answering (%s)" % e}
    audit(tool="cc.control", intent="write", by="phone", action=act, verdict="ok" if ok else "error", why="" if ok else "HTTP %d" % code)
    return (200, {"ok": True, "action": act}) if ok else (502, {"error": "llama-server refused (HTTP %d)" % code})


def cc_model(data):
    act = data.get("action")
    if act not in MODEL_ACTIONS: return 400, {"error": "action must be load, unload or reload"}
    if GPU_BUSY and GPU_BUSY(): return 409, {"error": "a video render has the GPU"}
    w = _rl("model")
    if w: return 429, {"error": "one model action per 5 s", "retry_after": w}
    t = int(time.time())
    try: _atomic_write(GOV_REQUEST_FILE, json.dumps({"action": act, "t": t, "by": "cc"}) + "\n")
    except OSError as e: return 500, {"error": "cannot write the governor request (%s)" % (e.strerror or e)}
    audit(tool="cc.model", intent="write", by="phone", action=act)
    return 200, {"requested": act, "t": t}


def cc_slot_delete(name):
    stem = re.sub(r"\.(bin|json)$", "", name, flags=re.I)
    if not SLOT_NAME_RE.match(stem) or ".." in stem: return 400, {"error": "bad slot file name"}
    d = _slots_dir()
    if not d or not os.path.isdir(d): return 404, {"error": "no slots folder is configured"}
    w = _rl("slot")
    if w: return 429, {"error": "one delete per 5 s", "retry_after": w}
    root, gone = os.path.realpath(d), []
    for ext in (".bin", ".json"):
        p = os.path.join(d, stem + ext)
        if os.path.islink(p) or not os.path.isfile(p) or os.path.dirname(os.path.realpath(p)) != root: continue
        os.remove(p); gone.append(stem + ext)
    if not gone: return 404, {"error": "no such saved context"}
    audit(tool="cc.slot.delete", intent="destructive", by="phone", target=stem, files=gone)
    return 200, {"deleted": gone}


def cc_kill(data):
    on = data.get("on")
    if not isinstance(on, bool): return 400, {"error": "on must be true or false"}
    w = _rl("kill")
    if w: return 429, {"error": "one kill-switch change per 5 s", "retry_after": w}
    try:
        if on:
            with open(KILL_FILE, "w") as f: f.write("created from the Control Centre\n")
        elif os.path.exists(KILL_FILE): os.remove(KILL_FILE)
    except OSError as e: return 500, {"error": "cannot change the KILL file (%s)" % (e.strerror or e)}
    audit(tool="cc.kill", intent="write", by="phone", on=on)
    return 200, {"kill": os.path.exists(KILL_FILE)}


def _no_agent(): return 503, {"error": "the agent is not enabled on this gateway"}


def cc_agent_start(data):
    if not _agent: return _no_agent()
    import agent as _ag
    task = data.get("task")
    if not isinstance(task, str) or not task.strip(): return 400, {"error": "task is required"}
    if len(task) > 4000: return 400, {"error": "task is longer than 4000 characters"}
    effort = data.get("effort") or ""
    if effort and effort not in EFFORTS: return 400, {"error": "effort must be low, medium or xhigh"}
    ms = data.get("max_steps", 20)
    if isinstance(ms, bool) or not isinstance(ms, int) or ms < 1: return 400, {"error": "max_steps must be a positive integer"}
    ms = min(ms, _agent.cfg.max_steps_cap)
    w = _rl("start")
    if w: return 429, {"error": "one new run per 10 s", "retry_after": w}
    st = _agent.new_state(task, effort); _agent.save(st)
    try: _agent.launch(max_steps=ms, effort=effort, state=st)
    except _ag.Busy as e:
        try: os.remove(_agent.path(st["id"]))
        except OSError: pass
        return 429, {"error": "not started: %s" % e}
    audit(tool="cc.agent.start", intent="write", by="phone", id=st["id"], effort=effort or None, why=task.strip()[:100])
    return 200, {"id": st["id"]}


def cc_agent_resume(aid, data):
    if not _agent: return _no_agent()
    import agent as _ag
    st = _read_run(aid)
    if not st: return 404, {"error": "unknown run"}
    if st.get("status") not in ("paused", "step_limit") or _status(st) == "running": return 409, {"error": "this run cannot be resumed (%s)" % _status(st)}
    note = str(data.get("note") or "")[:2000]
    ms = data.get("max_steps", 20)
    if isinstance(ms, bool) or not isinstance(ms, int) or ms < 1: return 400, {"error": "max_steps must be a positive integer"}
    try: _agent.launch(task=note, resume=aid, max_steps=min(ms, _agent.cfg.max_steps_cap))
    except _ag.Busy as e: return 429, {"error": "not resumed: %s" % e}
    audit(tool="cc.agent.resume", intent="write", by="phone", id=aid)
    return 200, {"id": aid, "status": "running"}


def cc_agent_cancel(aid):
    if not _agent: return _no_agent()
    st = _read_run(aid)
    if not st: return 404, {"error": "unknown run"}
    w = _rl("cancel")
    if w: return 429, {"error": "one cancel per 5 s", "retry_after": w}
    res = _agent.request_cancel(aid)
    if not res: return 409, {"error": "this run already ended (%s)" % st.get("status")}
    if res == "cancelled":       # a paused run's open approval request goes with it
        with _lock:
            for rid in st.get("approvals") or []: _pending.pop(rid, None)
    audit(tool="cc.agent.cancel", intent="write", by="phone", id=aid, state=res)
    return 200, {"id": aid, "status": res}


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Approvals</title><style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#14171c;--mute:#5b6470;--ok:#0b7a3e;--no:#b42318;--line:#d9dde3}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#181b21;--ink:#e8eaee;--mute:#9aa3ae;--ok:#3fbf7a;--no:#ff6b5e;--line:#2a2f37}}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 system-ui,sans-serif}main{max-width:640px;margin:0 auto;padding:16px}
h1{font-size:1.25rem;margin:.2em 0 .8em}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin:0 0 12px}
.t{font-weight:600}.why{color:var(--mute);font-size:.9rem;margin:.2em 0 .5em}pre{white-space:pre-wrap;word-break:break-word;font-size:.85rem;margin:0 0 10px;max-height:40vh;overflow:auto}
button{font:inherit;border:0;border-radius:10px;padding:10px 14px;margin:0 6px 6px 0;color:#fff;cursor:pointer}.ok{background:var(--ok)}.no{background:var(--no)}.alt{background:#44506a}
input{font:inherit;padding:10px;border-radius:10px;border:1px solid var(--line);width:10em;background:var(--card);color:var(--ink)}.m{color:var(--mute)}
</style></head><body><main><h1>Tool approvals</h1><div id="login" hidden><p>Enter your approval PIN.</p>
<form id="f"><input id="pin" type="password" inputmode="numeric" autocomplete="one-time-code" aria-label="Approval PIN"> <button class="ok">Unlock</button></form><p id="lm" class="m"></p></div>
<div id="list"></div><p class="m">Approve once runs that exact call once. Allow 15 min lets that tool run without asking for 15 minutes.</p></main>
<script>
const $=s=>document.querySelector(s);const H={'Content-Type':'application/json','X-Requested-With':'approvals'};
async function load(){const r=await fetch('approvals/pending.json',{headers:H});if(r.status===401){$('#login').hidden=false;$('#list').innerHTML='';return;}
$('#login').hidden=true;const j=await r.json();const L=$('#list');L.innerHTML=j.length?'':'<p class="m">Nothing waiting.</p>';
for(const p of j){const d=document.createElement('div');d.className='card';d.innerHTML='<div class="t"></div><div class="why"></div><pre></pre>';
d.querySelector('.t').textContent=p.tool+'  (request '+p.id+', '+p.age+'s ago)';d.querySelector('.why').textContent=p.why;d.querySelector('pre').textContent=p.args;
for(const [a,c,l] of [['approve','ok','Approve once'],['allow','alt','Allow 15 min'],['deny','no','Deny']]){const b=document.createElement('button');b.className=c;b.textContent=l;
b.onclick=async()=>{await fetch('approvals/'+p.id+'/'+a,{method:'POST',headers:H});load();};d.appendChild(b);}L.appendChild(d);}}
$('#f').onsubmit=async e=>{e.preventDefault();const r=await fetch('approvals/login',{method:'POST',headers:H,body:JSON.stringify({pin:$('#pin').value})});
$('#pin').value='';$('#lm').textContent=r.ok?'':(await r.text());load();};
load();setInterval(load,3000);
</script></body></html>"""


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype="application/json", headers=()):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store"); self.send_header("X-Frame-Options", "DENY")
        for k, v in headers: self.send_header(k, v)
        self.end_headers(); self.wfile.write(b)

    def _authed(self):
        c = self.headers.get("Cookie", "")
        tok = next((p.split("=", 1)[1] for p in c.split(";") if p.strip().startswith("gwa=")), "")
        with _lock:
            return bool(tok) and _sessions.get(tok, 0) > time.time()

    def _route(self):
        p = self.path.split("?")[0].rstrip("/")
        i, o = p.find("/approvals"), p.find("/outbox/")
        if o >= 0 and (i < 0 or o < i):
            return p[o:]
        return p[i:] if i >= 0 else p

    def _outbox(self, r):
        """GET /outbox/<token>/<relpath...>: stream a shared file. Every response carries the sandbox CSP."""
        sec = [("Content-Security-Policy", OUT_CSP), ("X-Content-Type-Options", "nosniff"), ("Cache-Control", "no-store")]
        def fail(code, msg):
            b = msg.encode()
            self.send_response(code); self.send_header("Content-Type", "text/plain; charset=utf-8"); self.send_header("Content-Length", str(len(b)))
            for k, v in sec: self.send_header(k, v)
            self.end_headers(); self.wfile.write(b)
        parts = r.split("/")          # ['', 'outbox', token, *rel]
        token = unquote(parts[2]) if len(parts) > 2 else ""
        segs = [unquote(x) for x in parts[3:]]
        if any("/" in x or "\\" in x for x in segs):
            return fail(404, "not found")
        code, path = outbox.lookup_status(outbox.get_dir(), token, "/".join(segs))
        if code == 410: return fail(410, "this link has expired")
        if code != 200: return fail(404, "not found")
        try:
            f = open(path, "rb")
        except OSError:
            return fail(404, "not found")
        with f:
            ctype = (mimetypes.guess_type(path)[0] or "application/octet-stream")
            ext = os.path.splitext(path)[1].lower()
            ctype = {".html": "text/html", ".htm": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
                     ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                     ".pdf": "application/pdf", ".md": "text/markdown", ".txt": "text/plain", ".zip": "application/zip"}.get(ext, ctype)
            if ctype.startswith("text/") or ctype in ("application/json", "image/svg+xml") or ctype == "text/javascript":
                charset = "; charset=utf-8" if ctype.startswith("text/") or ctype == "application/json" else ""
                ctype_h = ctype + charset
            else:
                ctype_h = ctype
            inline = ctype in ("text/html", "text/plain", "text/markdown", "application/pdf", "image/svg+xml") or ctype.startswith("image/")
            site_asset = ext in (".js", ".mjs", ".css", ".json", ".woff", ".woff2", ".ttf", ".otf", ".wasm", ".map", ".ico")
            size = os.fstat(f.fileno()).st_size
            self.send_response(200); self.send_header("Content-Type", ctype_h); self.send_header("Content-Length", str(size))
            if not inline and not site_asset:
                nm = os.path.basename(path)
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(nm))
            for k, v in sec: self.send_header(k, v)
            self.end_headers()
            shutil.copyfileobj(f, self.wfile, 1 << 20)

    def do_GET(self):
        r = self._route()
        if r.startswith("/outbox/"):
            return self._outbox(r)
        if r == "/approvals":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if r == "/approvals/pending.json":
            if not self._authed(): return self._send(401, "[]")
            now = time.time()
            with _lock:
                _gc(now)
                out = [_card(v, now) for v in sorted(_pending.values(), key=lambda v: v["created"]) if v["state"] == "pending"]
            return self._send(200, json.dumps(out), headers=[("X-Session-Expires", str(self._session_exp()))])
        if r == "/approvals/history.json":      # the decisions log, read back from audit.jsonl (session only: it carries tool arguments)
            if not self._authed(): return self._send(401, "[]")
            return self._send(200, json.dumps(history()))
        if r == "/approvals/agent/runs.json":
            if not self._authed(): return self._send(401, "[]")
            return self._send(200, json.dumps(list_runs()))
        m = re.match(r"^/approvals/agent/([0-9a-f]{8})\.json$", r)
        if m:
            if not self._authed(): return self._send(401, "{}")
            d = run_detail(m.group(1))
            return self._send(200, json.dumps(d)) if d else self._send(404, '{"error":"unknown run"}')
        h = _extra_for("GET", r)
        if h: return self._extra(h, r, b"")
        self._send(404, "{}")

    def _session_exp(self):
        c = self.headers.get("Cookie", "")
        tok = next((p.split("=", 1)[1] for p in c.split(";") if p.strip().startswith("gwa=")), "")
        with _lock: return int(_sessions.get(tok, 0))

    def _extra(self, h, r, body):
        q = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
        try: parsed = json.loads(body or b"{}")
        except ValueError: parsed = {}
        req = {"path": r, "query": q, "body": parsed if isinstance(parsed, dict) else {}, "raw": body, "authed": self._authed(),
               "headers": {k.lower(): v for k, v in self.headers.items()}}
        try: code, out, ctype = h(req)
        except Exception as e:
            return self._send(500, json.dumps({"error": "handler failed: %s" % type(e).__name__}))
        if isinstance(out, dict) and "file" in out:
            return self._serve_file(out["file"], out.get("ctype") or ctype, out.get("download"), req["headers"].get("range", ""))
        self._send(code, out, ctype)

    def _serve_file(self, path, ctype, download, rng):
        """Stream a file with single-range support (206), so <video> can seek on iOS/Safari. The route handler has already authorised the path."""
        try: f = open(path, "rb")
        except OSError: return self._send(404, '{"error":"not found"}')
        with f:
            size = os.fstat(f.fileno()).st_size; start, end, code = 0, size - 1, 200
            m = re.match(r"^bytes=(\d*)-(\d*)$", rng.strip()) if rng else None
            if m and (m.group(1) or m.group(2)):
                if m.group(1): start = int(m.group(1)); end = int(m.group(2)) if m.group(2) else size - 1
                else: start = max(0, size - int(m.group(2))); end = size - 1
                end = min(end, size - 1)
                if start > end or start >= size:
                    self.send_response(416); self.send_header("Content-Range", "bytes */%d" % size); self.send_header("Content-Length", "0"); self.end_headers(); return
                code = 206
            n = end - start + 1
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(n)); self.send_header("Accept-Ranges", "bytes")
            if code == 206: self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
            self.send_header("Cache-Control", "private, max-age=3600"); self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("X-Frame-Options", "DENY")
            if download: self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(download))
            self.end_headers(); f.seek(start); left = n
            try:
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk: break
                    self.wfile.write(chunk); left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError, OSError): pass

    def do_POST(self):
        r = self._route()
        if self.headers.get("X-Requested-With") != "approvals":   # blocks plain cross-site form posts
            return self._send(403, "{}")
        cap = BODY_MAX
        for k in (("POST " + r),):
            if k in _extra_max: cap = _extra_max[k]
        n = max(0, int(self.headers.get("Content-Length") or 0))
        if n > cap and cap != BODY_MAX: return self._send(413, '{"error":"too large"}')     # upload routes refuse; others keep the old silent cap
        n = min(n, cap)
        body = self.rfile.read(n) if n else b""
        now = time.time()
        if r == "/approvals/login":
            if _fails["until"] > now:
                return self._send(429, "Too many wrong PINs. Try again in %d minutes." % (int(_fails["until"] - now) // 60 + 1), "text/plain")
            try: pin = str(json.loads(body or b"{}").get("pin", ""))
            except Exception: pin = ""
            if not os.path.exists(PIN_FILE):
                return self._send(403, "No PIN set. Run C:/AI/gateway/set-approval-pin.ps1 on the PC.", "text/plain")
            if not _pin_ok(pin):
                _fails["n"] += 1
                if _fails["n"] >= MAX_FAILS: _fails.update(n=0, until=now + LOCK_S)
                return self._send(401, "Wrong PIN.", "text/plain")
            _fails["n"] = 0; tok = secrets.token_urlsafe(32)
            with _lock: _sessions[tok] = now + SESSION_TTL
            return self._send(200, "{}", headers=[("Set-Cookie", "gwa=%s; Path=/; Max-Age=%d; HttpOnly; Secure; SameSite=Strict" % (tok, SESSION_TTL))])
        if r == "/approvals/mode":   # switch the governor profile; same effect as `qwen mode <x>`, needs the PIN session
            if not self._authed(): return self._send(401, '{"error":"log in with your PIN on the approvals page first"}')
            if GPU_BUSY and GPU_BUSY(): return self._send(409, '{"error":"a video render has the GPU"}')
            try: m = str(json.loads(body or b"{}").get("mode", "")).upper()
            except Exception: m = ""
            if m not in MODES: return self._send(400, '{"error":"mode must be AUTO, MAX, BALANCED or LEAN"}')
            with open(GOV_MODE_FILE, "w", encoding="ascii") as f: f.write(m + "\n")
            return self._send(200, json.dumps({"mode": m}))
        parts = r.split("/")   # ['', 'approvals', id, action]
        if len(parts) == 4 and parts[3] in ("approve", "allow", "deny") and parts[2] != "agent":
            if not self._authed(): return self._send(401, "{}")
            with _lock:
                v = _pending.get(parts[2])
                if not v or v["state"] != "pending": return self._send(404, "{}")
                v["decided"] = now
                act = parts[3]
                if act == "allow" and v.get("origin") == "agent": act = "approve"      # agent calls are approve-once only: no tool-wide window
                if act == "deny": v["state"] = "denied"
                else:
                    v["state"] = "approved"
                    if act == "allow": _allow[v["tool"]] = now + 15 * 60
                rec = dict(tool="cc.approval", intent="write", by="phone", decision=act, target=v["tool"], req=v["id"], origin=v.get("origin"),
                           preview=_preview(v["args"]))
            audit(**rec)
            return self._send(200, "{}")
        # ---- Control Centre writes: header checked above, session checked here, then the handler ----
        cc = None
        if r in ("/approvals/control", "/approvals/model", "/approvals/kill", "/approvals/agent/start"): cc = r
        elif len(parts) == 5 and parts[2] == "slots" and parts[4] == "delete": cc = "slot"
        elif len(parts) == 5 and parts[2] == "agent" and parts[4] in ("resume", "cancel"): cc = parts[4]
        if cc or _extra_for("POST", r):
            if not self._authed(): return self._send(401, '{"error":"log in with your PIN first"}')
            if not cc: return self._extra(_extra_for("POST", r), r, body)
            try: data = json.loads(body or b"{}")
            except ValueError: data = None
            if not isinstance(data, dict): return self._send(400, '{"error":"body must be a JSON object"}')
            try:
                if cc == "/approvals/control": code, out = cc_control(data)
                elif cc == "/approvals/model": code, out = cc_model(data)
                elif cc == "/approvals/kill": code, out = cc_kill(data)
                elif cc == "/approvals/agent/start": code, out = cc_agent_start(data)
                elif cc == "slot": code, out = cc_slot_delete(unquote(parts[3]))
                elif cc == "resume": code, out = cc_agent_resume(parts[3], data)
                else: code, out = cc_agent_cancel(parts[3])
            except Exception as e:
                code, out = 500, {"error": "failed: %s" % type(e).__name__}
            return self._send(code, json.dumps(out))
        self._send(404, "{}")


_started = False
def start():
    global _started
    if _started: return
    _started = True
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), _H)
    except OSError as e:   # port taken (another gateway instance): run without a page; changes then fail safe
        _bound["err"] = "approvals page could not start on port %d (%s); set GW_APPROVAL_PORT to a free port" % (PORT, e)
        sys.stderr.write("gateway: " + _bound["err"] + "\n")
        return
    _bound["ok"] = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
