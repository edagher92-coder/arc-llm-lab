"""Server-side `agent` tool for the lazy tool gateway: one phone message runs a disciplined plan -> act -> verify loop
against the local model (an OpenAI-compatible endpoint, e.g. llama-swap on :8090) and returns one compact result.

Why server-side: the phone model (Open WebUI) lacks the harness discipline, not the plumbing. Here we control the prompt, the
reasoning effort per step, result trimming, context hygiene, approvals and audit. The loop never calls a downstream server
directly: every tool call goes back THROUGH the gateway (an in-memory FastMCP client), so Guard (kill switch, deny rules, intent
classes, approvals, loop breaker), result trimming and the hash-chained audit all apply exactly as for the phone.

Result (JSON string): {status: done|paused|failed|step_limit, summary, links, steps, id}  (+ approvals: [ids] when paused).
Resume: agent(resume=<id>) continues a paused (waiting for approval) or step_limit run; the same call is retried after approval.

Policy note (gateway.py classifies `agent` as "read"): the tool itself changes nothing; each inner call is vetted by Guard on
its own (a write inside the loop returns NEEDS APPROVAL and pauses the run). Asking for approval on `agent` as well would
double-prompt the user for no extra safety.
"""
import asyncio, hashlib, json, os, re, secrets, threading, time, urllib.error, urllib.request

import approvals, skills

EFFORTS = ("xhigh", "medium", "low")      # the only reasoning_effort values the server accepts; anything else is an HTTP 500
RESULT_CAP = 6000                         # chars of one tool result fed back to the model
KEEP_VERBATIM = 4                         # newest tool results kept whole; older ones become one-line summaries
OLD_PREFIX = "[earlier result] "
KEEP_FILES = 50
GUARD_MSG = "You already ran this exact call; use its result or change approach."
URL_RE = re.compile(r"https?://[^\s)>\]\"'`]+")
APPROVAL_RE = re.compile(r"^NEEDS APPROVAL \(request ([0-9a-f]{4,12}): ([^)]*)\)")   # only the gateway's own message, at the very start
FORBIDDEN = {"agent", "call_tool", "search_tools"}      # never valid as the target of a call_tool made by the agent
ID_RE = re.compile(r"^[0-9a-f]{8}$")
MAX_CONCURRENT = 3                                       # GUI-started background runs at once


class Busy(Exception):
    """launch() refused: that run is already going, or too many runs are going."""


class AgentError(Exception):
    pass


class Cfg:
    def __init__(self, c):
        c = c or {}
        self.base_url = str(c.get("base_url") or "http://127.0.0.1:8090/v1").rstrip("/")
        self.model = str(c.get("model") or "qwen3.8-27b")
        self.api_key_file = c.get("api_key_file") or ""
        self.max_steps_cap = max(1, int(c.get("max_steps_cap") or 30))
        self.timeout_s = max(5, float(c.get("timeout_s") or 900))
        self.effort_plan = c.get("reasoning_effort_plan") if c.get("reasoning_effort_plan") in EFFORTS else "xhigh"
        self.effort_act = c.get("reasoning_effort_act") if c.get("reasoning_effort_act") in EFFORTS else "medium"
        self.max_tokens = int(c["max_tokens"]) if c.get("max_tokens") else None
        self.system_file = c.get("system_file") or os.path.join("prompts", "agent-system.md")

    def api_key(self):
        try:
            return open(self.api_key_file, encoding="utf-8-sig").read().strip() if self.api_key_file else ""
        except OSError:
            return ""


# ---------- model call (stdlib, run in a thread) ----------
def chat(cfg, messages, tools, effort, timeout, tool_choice=None):
    body = {"model": cfg.model, "messages": messages, "stream": False,
            "chat_template_kwargs": {"reasoning_effort": effort}}
    if tools:
        body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
    if cfg.max_tokens:
        body["max_tokens"] = cfg.max_tokens
    headers = {"Content-Type": "application/json"}
    key = cfg.api_key()
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(cfg.base_url + "/chat/completions", data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=max(1.0, timeout)) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise AgentError("model HTTP %d: %s" % (e.code, e.read().decode("utf-8", "replace")[:200]))
    except Exception as e:   # refused, timeout, bad JSON
        raise AgentError("model unreachable or bad reply (%s: %s)" % (type(e).__name__, str(e)[:160]))


# ---------- helpers ----------
def blob(args):
    return json.dumps(args, sort_keys=True, ensure_ascii=False)


def digest(args):
    return hashlib.sha1(blob(args).encode()).hexdigest()[:8]


def effective(name, args):
    """call_tool(name=X, arguments=Y) is really X(Y): judge, count and summarise it as X."""
    if name == "call_tool" and isinstance(args, dict):
        return str(args.get("name") or ""), (args.get("arguments") if isinstance(args.get("arguments"), dict) else {})
    return name, args if isinstance(args, dict) else {}


def blocked_target(name, args):
    """Recursion guard, independent of Guard: refuse `agent` anywhere, and any call_tool whose target is call_tool, search_tools or agent
    (so call_tool -> call_tool -> agent is stopped at the first hop). Returns the offending name or None."""
    n = str(name or "").strip().lower()
    if n == "agent":
        return "agent"
    if n == "call_tool":      # target call_tool/search_tools/agent is refused at this first hop, so deeper nesting can never be reached
        t = str((args or {}).get("name") if isinstance(args, dict) else "").strip().lower()
        if t in FORBIDDEN:
            return t
    return None


def result_text(res):
    return "\n".join(getattr(c, "text", "") for c in (getattr(res, "content", None) or []) if getattr(c, "text", None) is not None)


def compact_history(messages, meta, keep=KEEP_VERBATIM, chars=200):
    """Context hygiene: keep the newest `keep` tool results whole; older ones become one line (tool, args digest, first chars).
    Done in place and kept, so the older part of the prompt only changes once per message (decode slows as context grows)."""
    idx = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    for i in idx[:-keep] if keep else idx:
        m = messages[i]
        if str(m.get("content", "")).startswith(OLD_PREFIX):
            continue
        info = meta.get(m.get("tool_call_id"), {})
        first = re.sub(r"\s+", " ", str(m.get("content", ""))).strip()[:chars]
        m["content"] = "%s%s(%s): %s" % (OLD_PREFIX, info.get("name", "?"), info.get("digest", "-"), first)


def claims_without_evidence(text, ok_calls):
    """Does the final reply claim a deliverable (link, path, created/saved/...) that no successful tool call backs up?"""
    urls = [u.rstrip(".,;:") for u in URL_RE.findall(text)]
    paths = re.findall(r"[A-Za-z]:\\[^\s\"'<>|*?]+", text)
    verbs = re.search(r"\b(created|built|saved|wrote|written|deployed|shared|published|generated|uploaded)\b", text, re.I)
    if not (urls or paths or verbs):
        return False
    results = "\n".join(c["text"] for c in ok_calls)
    if urls and not all(u in results for u in urls):
        return True
    if paths and not all(p.rstrip(".,;:") in results or p.rstrip(".,;:") in "\n".join(c["args"] for c in ok_calls) for p in paths):
        return True
    return not any(c["name"] not in ("search_tools", "skills") for c in ok_calls)


def to_openai(tools):
    return [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                              "parameters": t.inputSchema or {"type": "object", "properties": {}}}} for t in tools]


class Agent:
    def __init__(self, server, cfg, guard, state_dir, system_prompt, kill=None):
        self.server, self.cfg, self.guard, self.dir, self.system, self.kill = server, cfg, guard, state_dir, system_prompt, kill
        self.active, self.lock = {}, threading.Lock()      # run id -> start time, for every run in this process
        os.makedirs(self.dir, exist_ok=True)

    # ----- persistence -----
    def path(self, aid):
        return os.path.join(self.dir, "agent-%s.json" % aid)

    def save(self, st):
        st["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        tmp = self.path(st["id"]) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        os.replace(tmp, self.path(st["id"]))
        files = sorted((os.path.join(self.dir, n) for n in os.listdir(self.dir) if re.match(r"^agent-[0-9a-f]{8}\.json$", n)),
                       key=lambda p: os.path.getmtime(p))
        for p in files[:-KEEP_FILES]:
            try: os.remove(p)
            except OSError: pass

    def load(self, aid):
        if not ID_RE.match(aid or ""):
            return None
        try:
            return json.load(open(self.path(aid), encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def cancel_path(self, aid):
        return os.path.join(self.dir, "agent-%s.cancel" % aid)

    def request_cancel(self, aid):
        """Per-run cancel. A running loop sees the file before its next model turn and ends as `cancelled` (within one step);
        a run that is not executing (paused for approval, or at the step cap) is closed right here. Returns the state or None."""
        if not ID_RE.match(aid or ""):
            return None
        with self.lock:
            live = aid in self.active
        if live:
            with open(self.cancel_path(aid), "w") as f: f.write("cancel\n")
            return "cancelling"
        st = self.load(aid)
        if not st or st.get("status") not in ("paused", "step_limit"):
            return None
        st["pending"] = None
        self.finish(st, "cancelled", "Cancelled by the user.")
        return "cancelled"

    def new_state(self, task, effort="", rid=None):
        return {"id": rid or secrets.token_hex(4), "task": task.strip(), "status": "running", "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "messages": [{"role": "system", "content": self.system},
                             {"role": "user", "content": task.strip() + "\n\nFirst reply: your numbered todo (at most 6 items), no tool calls."}],
                "meta": {}, "pending": None, "seen": {}, "steps": 0, "plan_done": False, "verify_pending": False, "verify_done": False,
                "links": [], "ok_calls": [], "approvals": [], "last_text": "", "summary": "",
                "effort": effort if effort in EFFORTS else ""}

    def launch(self, task="", resume="", max_steps=20, effort="", state=None):
        """Run in a background thread with its own event loop (the Control Centre's start/resume). The run is registered as active
        before this returns, so a second launch of the same id or a fourth concurrent run raises Busy."""
        rid = state["id"] if state else resume
        with self.lock:
            if rid in self.active: raise Busy("that run is already going")
            if len(self.active) >= MAX_CONCURRENT: raise Busy("%d runs are already going" % len(self.active))
            self.active[rid] = time.time()
        def target():
            try: asyncio.run(self.run(task, resume, max_steps, effort, state=state, launched=True))
            except BaseException: pass
            finally:
                with self.lock: self.active.pop(rid, None)
        threading.Thread(target=target, name="agent-" + rid, daemon=True).start()
        return rid

    # ----- audit / result -----
    def audit(self, st, **kw):
        self.guard.audit(tool="agent", intent="read", event=kw.pop("event", "agent_step"), id=st["id"], **kw)

    def finish(self, st, status, summary, **extra):
        st["status"], st["summary"] = status, summary[:1500]
        self.save(st)
        try: os.remove(self.cancel_path(st["id"]))
        except OSError: pass
        self.audit(st, event="agent_end", status=status, steps=st["steps"], why=summary[:200])
        out = {"status": status, "summary": st["summary"], "links": st["links"], "steps": st["steps"], "id": st["id"]}
        out.update(extra)
        return json.dumps(out, ensure_ascii=False, separators=(",", ":"))

    # ----- one tool call, through the gateway -----
    async def call(self, client, name, args):
        try:
            r = await client.call_tool(name, args, raise_on_error=False)
            return result_text(r), bool(r.is_error)
        except Exception as e:
            return str(e), True

    async def exec_pending(self, st, client):
        """Run the pending tool call. Returns (final_json_or_None, verdict, ms)."""
        p = st["pending"]
        name, args = effective(p["name"], p["args"])
        sig = name + "\n" + blob(args)
        t0 = time.time()
        if p.get("bad_args"):
            text, err, verdict = "Tool arguments were not valid JSON. Send arguments as a JSON object.", True, "bad_args"
        elif blocked_target(p["name"], p["args"]):
            text, err, verdict = "%s is not allowed inside the agent. Use the other tools." % blocked_target(p["name"], p["args"]), True, "blocked"
        elif not p.get("retry") and st["seen"].get(sig, 0) >= 1:
            st["seen"][sig] += 1
            if st["seen"][sig] >= 4:
                st["pending"] = None
                return self.finish(st, "failed", "Stopped: the model kept repeating %s with the same arguments." % name), "stuck", 0
            text, err, verdict = GUARD_MSG, True, "repeat"
        else:
            with approvals.once_only(name, args, run=st["id"], step=st["steps"]):     # the user's "Allow 15 min" windows never cover the agent: approve-once only
                text, err = await self.call(client, p["name"], p["args"])
            verdict = "error" if err else "ok"
            if err and text.lstrip().startswith("KILLED"):
                st["pending"] = None
                return self.finish(st, "failed", "kill switch: " + text[:200]), "killed", int((time.time() - t0) * 1000)
            m = APPROVAL_RE.match(text) if err else None      # a page or file that merely contains the phrase cannot fake a pause
            if m:
                with approvals._lock: real = m.group(1) in approvals._pending      # ...and the request id must be one the gateway really issued
                m = m if real else None
            if err and not m and text.startswith("NEEDS APPROVAL, but"):   # no PIN or no approvals page: nothing the user can approve
                st["pending"] = None
                return self.finish(st, "failed", "Needs approval but approvals are not available: " + text[:300]), "no_approval", int((time.time() - t0) * 1000)
            if m:
                rid, why = m.group(1), m.group(2)
                p["retry"] = True
                st["approvals"] = [rid]
                msg = ("Paused: %s needs approval (request %s%s). Tell the user to approve request %s on their approvals page, "
                       "then call agent(resume=\"%s\")." % (name, rid, ": " + why if why else "", rid, st["id"]))
                return self.finish(st, "paused", msg, approvals=[rid]), "paused", int((time.time() - t0) * 1000)
            st["seen"][sig] = st["seen"].get(sig, 0) + 1
            if not err:
                st["ok_calls"].append({"name": name, "args": blob(args)[:500], "text": text[:2000]})
                st["ok_calls"] = st["ok_calls"][-40:]
                if name.endswith("share_file"):
                    for u in URL_RE.findall(text):
                        u = u.rstrip(".,;:")
                        if u not in st["links"]: st["links"].append(u)
        st["messages"].append({"role": "tool", "tool_call_id": p["id"], "content": skills.trim(text, RESULT_CAP) or "(empty result)"})
        st["meta"][p["id"]] = {"name": name, "digest": digest(args)}
        st["pending"], st["approvals"] = None, []
        return None, verdict, int((time.time() - t0) * 1000)

    def cancelled(self, st):
        return os.path.exists(self.cancel_path(st["id"]))

    # ----- the loop -----
    async def run_loop(self, st, client, tools, max_steps):
        cfg = self.cfg
        budget_end = st["steps"] + max_steps
        deadline = time.time() + cfg.timeout_s
        if self.cancelled(st):
            return self.finish(st, "cancelled", "Cancelled by the user.")
        if st["pending"]:      # resumed after approval: retry the same call first
            en = effective(st["pending"]["name"], st["pending"]["args"])[0]
            out, verdict, ms = await self.exec_pending(st, client)
            self.audit(st, step=st["steps"], kind="retry", call=en, call_ms=ms, verdict=verdict)
            if out: return out
        while True:
            if st["steps"] >= budget_end:
                return self.finish(st, "step_limit", "Stopped at the step cap (%d steps) before finishing. Last reply: %s" % (st["steps"], st["last_text"][:400] or "(none)"))
            if self.kill and os.path.exists(self.kill):
                return self.finish(st, "failed", "kill switch: the gateway KILL file is present.")
            if self.cancelled(st):
                return self.finish(st, "cancelled", "Cancelled by the user.")
            remaining = deadline - time.time()
            if remaining <= 0:
                return self.finish(st, "failed", "Timed out after %d s. Last reply: %s" % (cfg.timeout_s, st["last_text"][:300] or "(none)"))
            kind = "plan" if not st["plan_done"] else "verify" if st["verify_pending"] else "act"
            effort = st.get("effort") or (cfg.effort_plan if kind in ("plan", "verify") else cfg.effort_act)
            compact_history(st["messages"], st["meta"])
            t0 = time.time()
            try:
                resp = await asyncio.to_thread(chat, cfg, st["messages"], tools, effort, remaining, "none" if kind == "plan" else None)
                msg = resp["choices"][0]["message"]
            except (AgentError, KeyError, IndexError, TypeError) as e:
                return self.finish(st, "failed", "Model call failed: %s" % e)
            st["steps"] += 1
            content, calls = (msg.get("content") or "").strip(), msg.get("tool_calls") or []
            if content: st["last_text"] = content
            usage = resp.get("usage") or {}
            rec = dict(step=st["steps"], kind=kind, effort=effort, ms=int((time.time() - t0) * 1000),
                       tok_in=usage.get("prompt_tokens"), tok_out=usage.get("completion_tokens"))
            if not calls:
                if kind == "plan":
                    st["plan_done"] = True
                    st["messages"] += [{"role": "assistant", "content": content or "(no plan)"},
                                       {"role": "user", "content": "Plan noted. Do the first item now: one tool call."}]
                    self.audit(st, verdict="plan", **rec)
                    continue
                if not content:
                    st["messages"].append({"role": "user", "content": "Your reply was empty. Make one tool call, or give the final answer labelled VERIFIED or INFERRED."})
                    self.audit(st, verdict="empty", **rec)
                    continue
                st["messages"].append({"role": "assistant", "content": content})
                if not st["verify_done"] and claims_without_evidence(content, st["ok_calls"]):
                    st["verify_done"] = st["verify_pending"] = True
                    st["messages"].append({"role": "user", "content": (
                        "Verify before finishing: your reply claims a deliverable but no tool result in this run shows it. Make one tool call "
                        "that checks it (list the folder, read the file, or share_file), or restate the claim as INFERRED. "
                        "Then give the final answer labelled VERIFIED or INFERRED.")})
                    self.audit(st, verdict="verify_requested", **rec)
                    continue
                rec["kind"] = "final"
                self.audit(st, verdict="final", **rec)
                if not re.search(r"\b(VERIFIED|INFERRED)\b", content):
                    content += "\n[INFERRED: no label given]"
                return self.finish(st, "done", content)
            st["plan_done"] = True
            call = calls[0]     # one tool call per step: extra calls in the same reply are dropped
            fn = call.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
                bad = not isinstance(args, dict)
            except ValueError:
                args, bad = {}, True
            cid = call.get("id") or "call_" + secrets.token_hex(4)
            st["messages"].append({"role": "assistant", "content": content,
                                   "tool_calls": [{"id": cid, "type": "function", "function": {"name": fn.get("name", ""), "arguments": json.dumps(args if not bad else {}, ensure_ascii=False)}}]})
            st["pending"] = {"id": cid, "name": fn.get("name", ""), "args": args if not bad else {}, "bad_args": bad}
            out, verdict, ms = await self.exec_pending(st, client)
            en, _ = effective(fn.get("name", ""), args if not bad else {})
            self.audit(st, call=en, call_ms=ms, verdict=verdict, **rec)
            if out: return out

    # ----- entry point -----
    async def run(self, task, resume, max_steps, effort="", state=None, launched=False):
        from fastmcp import Client
        cfg = self.cfg
        max_steps = max(1, min(int(max_steps or 20), cfg.max_steps_cap))
        rid_own = None
        if resume:
            st = self.load(resume.strip())
            if not st:
                return json.dumps({"status": "failed", "summary": "Unknown agent id %r." % resume[:40], "links": [], "steps": 0, "id": resume[:40]})
            if st["status"] not in ("paused", "step_limit"):
                return json.dumps({"status": st["status"], "summary": "Cannot resume: this run already ended (%s). %s" % (st["status"], st.get("summary", "")[:300]),
                                   "links": st["links"], "steps": st["steps"], "id": st["id"]}, ensure_ascii=False, separators=(",", ":"))
            with self.lock:
                if st["id"] in self.active and not launched:
                    return json.dumps({"status": st["status"], "summary": "Cannot resume: this run is already going.", "links": st["links"], "steps": st["steps"], "id": st["id"]})
            if effort in EFFORTS: st["effort"] = effort
            if st["status"] == "step_limit":
                st["messages"].append({"role": "user", "content": "Continue: finish the remaining todo items."})
            if task.strip():
                st["messages"].append({"role": "user", "content": "Update from the user: " + task.strip()})
            st["status"] = "running"
        else:
            if not task.strip() and not state:
                return json.dumps({"status": "failed", "summary": "Give a task, or resume=<id>.", "links": [], "steps": 0, "id": ""})
            st = state or self.new_state(task, effort)
        with self.lock:
            if st["id"] not in self.active:      # launched runs are registered by launch(); direct calls register themselves
                self.active[st["id"]] = time.time(); rid_own = st["id"]
        self.save(st)
        self.audit(st, event="agent_start", resume=bool(resume), steps=st["steps"], effort=st.get("effort") or None, why=st["task"][:100])   # the id is recoverable even if the caller times out
        try:
            async with Client(self.server) as client:      # in-memory: goes through the gateway's transforms and Guard
                tools = to_openai([t for t in await client.list_tools() if t.name != "agent"])
                return await self.run_loop(st, client, tools, max_steps)
        except Exception as e:
            return self.finish(st, "failed", "Agent error: %s: %s" % (type(e).__name__, str(e)[:300]))
        finally:
            if rid_own:
                with self.lock: self.active.pop(rid_own, None)
            if st["status"] == "running":      # cancelled (caller disconnected or timed out) or any other abnormal exit: never leave `running`
                try: self.finish(st, "failed", "cancelled: the run was interrupted before it finished (resume is not possible).")
                except Exception: pass


def register(server, cfg, guard, state_dir, base_dir, kill=None):
    """Add the `agent` tool when the config has an "agent" block (opt-in). Returns the Agent, or None."""
    if "agent" not in cfg:
        return None
    ac = Cfg(cfg.get("agent"))
    p = ac.system_file if os.path.isabs(ac.system_file) else os.path.join(base_dir, ac.system_file)
    try:
        system = open(p, encoding="utf-8-sig").read().strip()
    except OSError:
        system = "You are an autonomous agent. Plan first (numbered todo), make one tool call per step, never claim done without evidence from a tool result, label the final answer VERIFIED or INFERRED."
    ag = Agent(server, ac, guard, state_dir, system, kill)
    approvals.attach(agent=ag, guard=guard, state_dir=state_dir, kill=kill)     # the Control Centre routes need the run store, audit chain and KILL path

    @server.tool(name="agent", description="Run a multi-step task to the end on the PC. task = what to do; resume = id of a paused run.")
    async def agent(task: str = "", resume: str = "", max_steps: int = 20) -> str:
        return await ag.run(task or "", resume or "", max_steps)

    return ag
