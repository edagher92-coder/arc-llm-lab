"""Studio code tab backend: POST /approvals/studio/api/chat (SSE proxy to the local Qwen behind llama-swap) and GET /approvals/studio/code.js.

Contract: docs/STUDIO-P2-CONTRACTS.md section 4 (events think / delta / usage / timings / done; 400 / 409 paused / 429 busy / 502).
Config: everything comes from the existing video.llm block (video.Cfg): swap_url, api_key_file (video.Cfg.api_key(), the Bearer key is added
server-side only and never appears in any response or event), model_id, governor_mode_file. Presets: "code" -> "<model_id>:code", "plan" -> "<model_id>:plan".
Pause detection mirrors tools_local_llm.register().paused(): governor mode OFF, a video job queued or active, a ComfyUI session or GPU lock, or Video mode.
One chat at a time (429 busy). The stream shares approvals.STREAM_MAX with the metrics stream. Closing the browser connection closes the upstream
connection, which makes llama.cpp cancel generation.
"""
import http.client, json, os, queue, re, socket, threading, time, urllib.parse

import video

T = "/approvals/studio"
PRESETS = ("code", "plan")
MAX_TOKENS = 8192
DEFAULT_TOKENS = 2048
MAX_INPUT = 256 * 1024          # bytes of message and context text together
MAX_FILES = 8
MAX_BODY = MAX_INPUT + 64 * 1024   # JSON overhead and escapes on top of the text cap
ROLES = ("user", "assistant", "system")
PING_S = 15.0
CONNECT_S = 10.0
HEADERS_S = 300.0               # llama-swap may have to load the model first
MAX_STREAM_S = 1800.0
CODE_JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "studio", "code.js")


def _j(code, obj):
    return code, json.dumps(obj, separators=(",", ":")), "application/json"


def _ev(name, data):
    return ("event: %s\ndata: %s\n\n" % (name, json.dumps(data, separators=(",", ":")))).encode("utf-8")


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _fence(text):
    run = max([len(m) for m in re.findall(r"`+", text)] or [0])
    return "`" * max(3, run + 1)


def build_messages(msgs, files):
    """Validated message list (system/user/assistant) with context files injected as fenced blocks into the last user message. Raises ValueError."""
    if not isinstance(msgs, list) or not msgs:
        raise ValueError("messages must be a non-empty list")
    out = []
    for m in msgs:
        if not isinstance(m, dict) or m.get("role") not in ROLES or not isinstance(m.get("content"), str):
            raise ValueError("each message needs a role (user, assistant or system) and a text content")
        out.append({"role": m["role"], "content": m["content"]})
    if out[-1]["role"] != "user":
        raise ValueError("the last message must be from the user")
    if files is None:
        files = []
    if not isinstance(files, list) or len(files) > MAX_FILES:
        raise ValueError("context_files must be a list of at most %d files" % MAX_FILES)
    blocks = []
    for f in files:
        if not isinstance(f, dict) or not isinstance(f.get("text"), str):
            raise ValueError("each context file needs a name and text")
        name = re.sub(r"[\x00-\x1f`]", " ", str(f.get("name") or "file"))[:120].strip() or "file"
        fc = _fence(f["text"])
        blocks.append("File: %s\n%s\n%s\n%s" % (name, fc, f["text"], fc))
    total = sum(len(m["content"].encode("utf-8")) for m in out) + sum(len(b.encode("utf-8")) for b in blocks)
    if total > MAX_INPUT:
        raise OverflowError("input is %d KB; the limit is %d KB" % (total // 1024, MAX_INPUT // 1024))
    if blocks:
        out[-1]["content"] = "\n\n".join(blocks) + "\n\n" + out[-1]["content"]
    return out


class ChatStream:
    """Iterator of SSE bytes for one chat. close() is idempotent and works even if iteration never started (approvals closes it on a 429 stream cap)."""

    def __init__(self, conn, sock, resp, release):
        self.conn, self.sock, self.resp, self._release = conn, sock, resp, release
        self.q, self.stop, self.done = queue.Queue(), threading.Event(), False
        self.t0 = time.time()
        self.th = threading.Thread(target=self._read, name="studio-chat-read", daemon=True)
        self._gen = self._run()
        self._cl = threading.Lock()
        self.th.start()

    def _read(self):
        try:
            while not self.stop.is_set():
                line = self.resp.readline()
                if not line:
                    break
                self.q.put(line)
        except Exception as e:
            self.q.put(e)
        self.q.put(None)

    def __iter__(self):
        return self._gen

    def _run(self):
        usage = timings = None
        finish = None
        err = None
        yield b"retry: 3000\n\n"
        try:
            while True:
                if time.time() - self.t0 > MAX_STREAM_S:
                    err = "chat stream time limit reached"
                    break
                try:
                    item = self.q.get(timeout=PING_S)
                except queue.Empty:
                    yield b": ping\n\n"
                    continue
                if item is None:
                    break
                if isinstance(item, Exception):
                    err = "the language model stopped answering"
                    break
                line = item.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    c = json.loads(data)
                except ValueError:
                    continue
                if not isinstance(c, dict):
                    continue
                if isinstance(c.get("error"), (dict, str)):
                    err = "the language model reported an error"
                    break
                for ch in c.get("choices") or []:
                    d = ch.get("delta") or {}
                    r = d.get("reasoning_content") or d.get("reasoning")
                    if isinstance(r, str) and r:
                        yield _ev("think", {"text": r})
                    t = d.get("content")
                    if isinstance(t, str) and t:
                        yield _ev("delta", {"text": t})
                    if ch.get("finish_reason"):
                        finish = ch["finish_reason"]
                if isinstance(c.get("usage"), dict):
                    usage = c["usage"]
                if isinstance(c.get("timings"), dict):
                    timings = c["timings"]
            if err is None and finish is None and usage is None and timings is None:
                err = "the language model closed the stream early"
            tm = timings or {}
            if usage is not None or tm:
                u = usage or {}
                pt = _num(u.get("prompt_tokens")); ct = _num(u.get("completion_tokens"))
                yield _ev("usage", {"prompt_tokens": pt if pt is not None else _num(tm.get("prompt_n")),
                                    "completion_tokens": ct if ct is not None else _num(tm.get("predicted_n"))})
            if tm:
                yield _ev("timings", {"prompt_ms": _num(tm.get("prompt_ms")), "prompt_per_s": _num(tm.get("prompt_per_second")),
                                      "predicted_ms": _num(tm.get("predicted_ms")), "predicted_per_s": _num(tm.get("predicted_per_second")),
                                      "draft_n": _num(tm.get("draft_n")), "draft_accepted": _num(tm.get("draft_n_accepted"))})
            if err:
                yield _ev("error", {"error": err})
                yield _ev("done", {"finish_reason": "error", "error": err})
            else:
                yield _ev("done", {"finish_reason": "length" if finish == "length" else "stop"})
        finally:
            self._cleanup()

    def _cleanup(self):
        with self._cl:
            if self.done:
                return
            self.done = True
        self.stop.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)       # wakes the reader thread and tells llama-swap the client is gone
        except OSError:
            pass
        try:
            self.conn.close()
        except Exception:
            pass
        self._release()

    def close(self):
        try:
            self._gen.close()
        except Exception:
            pass
        self._cleanup()


def routes(cfg, queue_, base_dir=None):
    """Route table {"METHOD /path": handler}."""
    if queue_ is not None:
        lc = queue_.cfg
    elif cfg and "video" in cfg:
        lc = video.Cfg(cfg.get("video"), base_dir or os.path.dirname(os.path.abspath(__file__)))
    else:
        return {}
    gate = threading.Lock()

    def need(req):
        return None if (req.get("authed") or req.get("tier") in ("pin", "ts")) else _j(401, {"error": "log in with your PIN first"})

    def paused():
        try:
            m = (open(lc.mode_file).read().strip() or "MAX") if lc.mode_file else ""
        except OSError:
            m = ""
        if m.upper() == "OFF":
            return True
        if queue_ is not None:
            try:
                return bool(queue_.busy() or queue_.session_info().get("active") or queue_.mode_get().get("view") == "video")
            except Exception:
                return False
        return False

    def chat(req):
        bad = need(req)
        if bad:
            return bad
        b = req["body"]
        preset = b.get("preset")
        if preset not in PRESETS:
            return _j(400, {"error": "preset must be one of: " + ", ".join(PRESETS)})
        if not lc.model_id:
            return _j(502, {"error": "no language model is configured"})
        try:
            msgs = build_messages(b.get("messages"), b.get("context_files"))
        except OverflowError as e:
            return _j(413, {"error": str(e)})
        except ValueError as e:
            return _j(400, {"error": str(e)})
        try:
            mt = int(b.get("max_tokens") or DEFAULT_TOKENS)
        except (TypeError, ValueError):
            return _j(400, {"error": "max_tokens must be a number"})
        mt = max(1, min(MAX_TOKENS, mt))
        body = {"model": "%s:%s" % (lc.model_id, preset), "messages": msgs, "max_tokens": mt, "stream": True, "stream_options": {"include_usage": True}}
        if b.get("temperature") is not None:
            try:
                body["temperature"] = max(0.0, min(2.0, float(b["temperature"])))
            except (TypeError, ValueError):
                return _j(400, {"error": "temperature must be a number"})
        if paused():
            return _j(409, {"error": "Qwen is paused: the GPU is on video work. Switch the GPU to Qwen to chat.", "reason": "paused"})
        if not gate.acquire(blocking=False):
            return _j(429, {"error": "another chat is generating; wait for it to finish", "reason": "busy", "retry_after": 5})
        released = []

        def release():
            if not released:
                released.append(1)
                gate.release()

        conn = None
        try:
            u = urllib.parse.urlsplit(lc.swap_url)
            cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
            conn = cls(u.hostname, u.port or (443 if u.scheme == "https" else 80), timeout=CONNECT_S)
            conn.connect()
            sock = conn.sock                                     # http.client drops conn.sock after a Connection: close reply; keep our own
            sock.settimeout(HEADERS_S)
            h = {"Content-Type": "application/json", "Accept": "text/event-stream"}
            key = lc.api_key()
            if key:
                h["Authorization"] = "Bearer " + key
            conn.request("POST", (u.path.rstrip("/") or "") + "/v1/chat/completions", json.dumps(body).encode("utf-8"), h)
            resp = conn.getresponse()
            if resp.status != 200:
                code = resp.status
                try:
                    resp.read(2048)
                except Exception:
                    pass
                conn.close(); release()
                if code in (429, 503):
                    return _j(429, {"error": "the language model is busy", "reason": "busy", "retry_after": 5})
                return _j(502, {"error": "the language model did not answer"})
            sock.settimeout(None)
        except Exception:
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass
            release()
            return _j(502, {"error": "the language model did not answer"})
        return 200, {"stream": ChatStream(conn, sock, resp, release)}, "text/event-stream"

    def codejs(req):
        try:
            with open(CODE_JS, "rb") as f:
                data = f.read()
        except OSError:
            return _j(404, {"error": "code.js missing"})
        return 200, data, "application/javascript; charset=utf-8"

    return {"POST " + T + "/api/chat": chat, "GET " + T + "/code.js": codejs}


def register(server_or_extra, cfg, queue_, base_dir=None):
    """server_or_extra: the approvals module (anything with register_extra). Returns the route table (empty when there is no video.llm config)."""
    table = routes(cfg, queue_, base_dir)
    if not table:
        return table
    keys = list(table)
    try:
        server_or_extra.register_extra(table, {"POST " + T + "/api/chat": MAX_BODY}, ts_ok=keys)
    except TypeError:
        server_or_extra.register_extra(table, {"POST " + T + "/api/chat": MAX_BODY})
    return table
