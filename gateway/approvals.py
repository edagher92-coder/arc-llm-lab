"""Out-of-band approvals for the lazy tool gateway.

A tool call that changes something (write/destructive intent, or an "approval" deny rule) is not run straight away. The gateway
records it here and tells the model to ask the user. The user opens the approvals page on their phone (tailnet only, behind a PIN
the model never sees), approves it once or allows that tool for a short time, and the model repeats the same call, which now runs.
The model cannot approve its own calls: approval needs the PIN, and the pending list lives only in this process's memory.

Page: http://127.0.0.1:8093/approvals (published on the tailnet through the voice server's /tts/approvals route).
PIN: set once on the PC with set-approval-pin.ps1 (stored as a PBKDF2 hash in approval-pin.json). No PIN set = nothing can be approved.
"""
import hashlib, hmac, html, json, mimetypes, os, secrets, shutil, sys, threading, time
from urllib.parse import quote, unquote
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

_lock = threading.Lock()
_pending = {}    # id -> {id, key, tool, args, why, created, state: pending|approved|denied, decided}
_allow = {}      # tool name -> expiry (allow this tool for a while)
_sessions = {}   # token -> expiry
_fails = {"n": 0, "until": 0.0}


def call_key(tool, args):
    return hashlib.sha256((tool + "\n" + json.dumps(args, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()


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
        if _allow.get(tool, 0) > now:
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
            _pending[pid] = dict(id=pid, key=key, tool=tool, args=args, why=why, created=now, state="pending", decided=None)
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
                out = [dict(id=v["id"], tool=v["tool"], why=v["why"], age=int(now - v["created"]),
                            args=json.dumps(v["args"], indent=1, ensure_ascii=False)[:4000]) for v in _pending.values() if v["state"] == "pending"]
            return self._send(200, json.dumps(out))
        self._send(404, "{}")

    def do_POST(self):
        r = self._route()
        if self.headers.get("X-Requested-With") != "approvals":   # blocks plain cross-site form posts
            return self._send(403, "{}")
        n = min(int(self.headers.get("Content-Length") or 0), 4096)
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
            try: m = str(json.loads(body or b"{}").get("mode", "")).upper()
            except Exception: m = ""
            if m not in MODES: return self._send(400, '{"error":"mode must be AUTO, MAX, BALANCED or LEAN"}')
            with open(GOV_MODE_FILE, "w", encoding="ascii") as f: f.write(m + "\n")
            return self._send(200, json.dumps({"mode": m}))
        parts = r.split("/")   # ['', 'approvals', id, action]
        if len(parts) == 4 and parts[3] in ("approve", "allow", "deny"):
            if not self._authed(): return self._send(401, "{}")
            with _lock:
                v = _pending.get(parts[2])
                if not v or v["state"] != "pending": return self._send(404, "{}")
                v["decided"] = now
                if parts[3] == "deny": v["state"] = "denied"
                else:
                    v["state"] = "approved"
                    if parts[3] == "allow": _allow[v["tool"]] = now + 15 * 60
            return self._send(200, "{}")
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
