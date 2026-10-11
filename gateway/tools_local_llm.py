"""ask_local: delegate cheap, private, low-stakes subtasks to the local Qwen 3.8 model behind llama-swap.

Config read (all from the existing "video" block's "llm" section, via video.Cfg; nothing new to configure):
  video.llm.swap_url            llama-swap base URL
  video.llm.api_key_file        Bearer key (video.Cfg.api_key(); never logged or returned)
  video.llm.model_id            model id; the no-thinking preset "<model_id>:code" is used unless video.llm.ask_local_model overrides it
  video.llm.governor_mode_file  governor mode file; OFF (or a video job / ComfyUI session / GPU lock) means "paused"
Policy: ask_local belongs in policy.read. Called from gateway.build() right after tools_video_mcp.register. Docs: docs/LOCAL-LLM.md.
"""
import json, re, socket, time, urllib.error, urllib.request

import video

TASKS = ("summarise", "classify", "draft", "rewrite", "extract_noncritical")
MAX_OUT = 20000
PAUSED_NOTE = "Qwen is paused while video renders; do it yourself or use the cloud tier"
STAKES = re.compile(r"\b(price[sd]?|pricing|quot(?:e|es|ed|ing|ation)s?|invoice[sd]?|invoicing|refunds?|payments?|AUD|GST|legal|contracts?|tax(?:es)?)\b|\$\s*\d|\d\s*\$", re.I)


def _j(x):
    return json.dumps(x, separators=(",", ":"))


def _http(url, body, headers, timeout):
    """POST json -> (status, parsed json or {}). Raises urllib.error.HTTPError / URLError / TimeoutError. Replaced in tests."""
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=dict(headers, **{"Content-Type": "application/json"}), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        t = r.read()
        return r.status, (json.loads(t) if t.strip()[:1] == b"{" else {})


def _is_timeout(e):
    return isinstance(e, (socket.timeout, TimeoutError)) or (isinstance(e, urllib.error.URLError) and isinstance(e.reason, (socket.timeout, TimeoutError)))


def register(server, q, base_dir, cfg=None):
    """Add ask_local to `server`. Uses Queue q's config/state when the video block exists, else builds video.Cfg from cfg["video"]. No-op if neither."""
    if q is not None:
        lc = q.cfg
    elif cfg and "video" in cfg:
        lc = video.Cfg(cfg.get("video"), base_dir)
    else:
        return
    llm = (cfg or {}).get("video", {}).get("llm", {}) if cfg else {}
    model = str(llm.get("ask_local_model") or (lc.model_id + ":code" if lc.model_id else "")).strip()

    def paused():
        try:
            m = (open(lc.mode_file).read().strip() or "MAX") if lc.mode_file else ""
        except OSError:
            m = ""
        if m.upper() == "OFF":
            return True
        if q is not None:
            try:
                return bool(q.busy() or q.session_info().get("active") or q.mode_get().get("view") == "video")
            except Exception:
                return False
        return False

    @server.tool(name="ask_local", description=(
        "Ask the local Qwen 3.8 model running on the owner's PC (private, free, slower than the cloud model). Its output is a DRAFT you must check yourself. "
        "Good for: summarise, classify, draft, rewrite, extract_noncritical (task=...). "
        "NEVER use it for money, pricing, quotes, invoices, legal, irreversible actions, customer-facing final copy, or critical extraction (names, amounts, dates, specs); "
        "prompts mentioning those are refused. Returns JSON {ok, status: ok|paused|busy|timeout|error|refused, text, model, elapsed_ms, note}. "
        "status paused = the GPU is on video work: do the task yourself or use the cloud tier."))
    def ask_local(prompt: str, task: str = "draft", system: str = "", max_tokens: int = 1024, timeout_s: int = 120) -> str:
        t0 = time.time()

        def out(status, text="", note=""):
            return _j({"ok": status == "ok", "status": status, "text": text, "model": model, "elapsed_ms": int((time.time() - t0) * 1000), "note": note})

        task = str(task or "").strip().lower()
        if task not in TASKS:
            return out("refused", note="task must be one of: " + ", ".join(TASKS))
        if STAKES.search("%s\n%s" % (system or "", prompt or "")):
            return out("refused", note="prompt looks like money/pricing/quote/invoice/legal/tax work; local Qwen must not be used for it")
        if not str(prompt or "").strip():
            return out("refused", note="empty prompt")
        if paused():
            return out("paused", note=PAUSED_NOTE)
        try:
            mt = max(1, min(4096, int(max_tokens)))
        except (TypeError, ValueError):
            mt = 1024
        try:
            to = max(5, min(600, int(timeout_s)))
        except (TypeError, ValueError):
            to = 120
        msgs = ([{"role": "system", "content": str(system)}] if str(system or "").strip() else []) + [{"role": "user", "content": str(prompt)}]
        body = {"model": model, "messages": msgs, "max_tokens": mt, "temperature": 0.2, "chat_template_kwargs": {"enable_thinking": False}}
        key = lc.api_key()
        h = {"Authorization": "Bearer " + key} if key else {}
        try:
            _, d = _http(lc.swap_url + "/v1/chat/completions", body, h, to)
        except urllib.error.HTTPError as e:
            return out("busy" if e.code in (429, 503) else "error", note="HTTPError %s" % e.code)
        except Exception as e:
            return out("timeout" if _is_timeout(e) else "error", note=type(e).__name__)
        try:
            text = str(d["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError):
            return out("error", note="malformed response")
        note = "DRAFT from local Qwen: check before use"
        if len(text) > MAX_OUT:
            text, note = text[:MAX_OUT], note + "; output truncated to %d chars" % MAX_OUT
        return out("ok", text, note)

    return ask_local
