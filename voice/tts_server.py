"""Private voice adapter: Kokoro-82M text to speech (ONNX, CPU) plus a speech-to-text pass-through to whisper.cpp.
Listens on 127.0.0.1:8092 only. Both the phone voice page (voice.html) and Open WebUI can use it.

  GET  /voices                          -> JSON {voice id: description}
  POST /tts                             -> audio/wav    body: {"text" | "input": "...", "voice": "emma", "speed": 1.05}
                                           (any POST path other than the transcription route is treated as /tts, as before)
  POST /v1/audio/speech                 -> audio/wav    same body (OpenAI-compatible; "model" and "response_format" are accepted and ignored: the reply is always WAV)
  POST /v1/audio/transcriptions         -> forwards the request body and Content-Type unchanged to whisper.cpp
                                           (default http://127.0.0.1:8091/inference) and returns its reply (JSON {"text": ...})

Voices: the short names below, a Kokoro voice id such as bf_emma, or an OpenAI voice name (alloy, echo, fable, onyx, nova, shimmer),
which are mapped to the closest curated voice. Unknown names fall back to emma.
Environment: WHISPER_URL overrides the whisper.cpp address; TTS_PORT overrides 8092; OMP_NUM_THREADS defaults to 6.
Setup: voice/setup-tts.ps1 creates the venv and downloads kokoro-v1.0.onnx and voices-v1.0.bin next to this file."""
import io, json, os, re, threading, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
WHISPER_URL = os.environ.get("WHISPER_URL", "http://127.0.0.1:8091/inference")
APPROVALS_URL = os.environ.get("APPROVALS_URL", "http://127.0.0.1:8093")  # optional: the tool gateway's approval page, shown at /tts/approvals
PORT = int(os.environ.get("TTS_PORT", "8092"))
MAX_JSON = 64 * 1024            # a speech request is a few hundred characters
MAX_AUDIO = 25 * 1024 * 1024    # same ceiling as the OpenAI transcription API
VOICES = {  # curated natural English voices: name -> (Kokoro voice id, language, description)
    "emma": ("bf_emma", "en-gb", "Emma - British female, warm"),
    "isabella": ("bf_isabella", "en-gb", "Isabella - British female, bright"),
    "george": ("bm_george", "en-gb", "George - British male, calm"),
    "lewis": ("bm_lewis", "en-gb", "Lewis - British male, deep"),
    "heart": ("af_heart", "en-us", "Heart - American female, natural"),
    "michael": ("am_michael", "en-us", "Michael - American male"),
}
ALIASES = {"alloy": "heart", "echo": "michael", "fable": "george", "onyx": "lewis", "nova": "emma", "shimmer": "isabella"}
BY_KOKORO_ID = {v[0]: k for k, v in VOICES.items()}

def resolve_voice(name):
    name = str(name or "emma").strip().lower()
    name = ALIASES.get(name, BY_KOKORO_ID.get(name, name))
    return VOICES.get(name, VOICES["emma"])

def clean(t):
    """Strip markdown that sounds wrong when read aloud."""
    t = re.sub(r"```.*?```", " code block omitted. ", t, flags=re.S)
    t = re.sub(r"[*_#`>|]", " ", t).replace("&", " and ")
    return re.sub(r"\s+", " ", t).strip()

def make_kokoro_synth():
    """Load Kokoro once and return synth(text, kokoro_voice_id, lang, speed) -> WAV bytes."""
    os.environ.setdefault("OMP_NUM_THREADS", "6")
    import numpy as np, soundfile as sf
    from kokoro_onnx import Kokoro
    kokoro = Kokoro(os.path.join(HERE, "kokoro-v1.0.onnx"), os.path.join(HERE, "voices-v1.0.bin"))
    lock = threading.Lock()
    def synth(text, voice, lang, speed):
        with lock:
            samples, sr = kokoro.create(text, voice=voice, speed=speed, lang=lang)
        buf = io.BytesIO(); sf.write(buf, np.asarray(samples, dtype=np.float32), sr, format="WAV", subtype="PCM_16")
        return buf.getvalue()
    synth("Ready.", "bf_emma", "en-gb", 1.0)  # warm-up
    return synth

GOV_DIR = os.environ.get("GOVERNOR_DIR", r"C:\AI\governor")

def live_stats():
    """Read-only snapshot for the live stats page: llama-server /slots and /metrics plus the governor status."""
    out = {"t": time.time()}
    try: out["gov"] = json.load(open(os.path.join(GOV_DIR, "public", "status.json"), encoding="utf-8-sig"))
    except Exception: out["gov"] = {}
    try: port = int(json.load(open(os.path.join(GOV_DIR, "running.json"), encoding="utf-8-sig")).get("port", 10001))
    except Exception: port = 10001
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/slots" % port, timeout=3) as r: sl = json.loads(r.read())[0]
        nt = sl.get("next_token") or {}
        nt = nt[0] if isinstance(nt, list) and nt else nt
        out["slot"] = {"busy": sl.get("is_processing"), "n_ctx": sl.get("n_ctx"), "prompt": sl.get("n_prompt_tokens"),
                       "prompt_done": sl.get("n_prompt_tokens_processed"), "cached": sl.get("n_prompt_tokens_cache"),
                       "decoded": (nt or {}).get("n_decoded"), "max_new": (sl.get("params") or {}).get("n_predict")}
    except Exception as e:
        out["slot"] = {"error": str(e)[:120]}
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/metrics" % port, timeout=3) as r:
            m = {}
            for line in r.read().decode().splitlines():
                if line.startswith("llamacpp:") and "{" not in line:
                    k, v = line.split(" ", 1); m[k[9:]] = float(v)
        out["metrics"] = m
    except Exception as e:
        out["metrics"] = {"error": str(e)[:120]}
    return out

STATS_PAGE = b"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Qwen live stats</title><style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#14171c;--mute:#5b6470;--acc:#0071c5;--line:#d9dde3}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#181b21;--ink:#e8eaee;--mute:#9aa3ae;--acc:#4ea3ff;--line:#2a2f37}}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.4 system-ui,sans-serif}main{max-width:720px;margin:0 auto;padding:16px}
h1{font-size:1.2rem;margin:.2em 0 .8em}.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.c{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}.v{font-size:1.6rem;font-weight:650;font-variant-numeric:tabular-nums}
.l{color:var(--mute);font-size:.85rem}.modes{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 14px}.modes button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:10px;padding:8px 14px;cursor:pointer}.modes button[aria-pressed=true]{background:var(--acc);border-color:var(--acc);color:#fff}.bar{height:10px;background:var(--line);border-radius:6px;overflow:hidden;margin-top:6px}.bar i{display:block;height:100%;background:var(--acc)}
</style></head><body><main><h1>Qwen live stats <span id="st" class="l"></span></h1>
<div class="modes" id="modes"></div><p class="l" id="mmsg"></p><div class="g">
<div class="c"><div class="l">Generating now</div><div class="v" id="tps">-</div><div class="l">tokens/s (this reply)</div></div>
<div class="c"><div class="l">This reply</div><div class="v" id="dec">-</div><div class="l">tokens written</div></div>
<div class="c"><div class="l">Context in use</div><div class="v" id="ctx">-</div><div class="bar"><i id="ctxb" style="width:0"></i></div></div>
<div class="c"><div class="l">Prompt from cache</div><div class="v" id="cache">-</div><div class="l" id="cachel"></div></div>
<div class="c"><div class="l">Average generation</div><div class="v" id="avg">-</div><div class="l">tok/s since load</div></div>
<div class="c"><div class="l">Average prompt reading</div><div class="v" id="pavg">-</div><div class="l">tok/s since load</div></div>
<div class="c"><div class="l">Draft tokens accepted</div><div class="v" id="acc">-</div><div class="l">DFlash2 speculative decoding</div></div>
<div class="c"><div class="l">GPU memory free</div><div class="v" id="vram">-</div><div class="l" id="prof"></div></div>
</div><p class="l">Updates every second. Read-only.</p></main><script>
let last=null;const $=i=>document.getElementById(i);const f=(n,d=0)=>n==null||isNaN(n)?'-':(+n).toLocaleString(undefined,{maximumFractionDigits:d});
async function tick(){try{const j=await (await fetch('stats.json',{cache:'no-store'})).json();const s=j.slot||{},m=j.metrics||{},g=j.gov||{};
$('st').textContent=s.busy?'- working':'- idle';
if(s.busy&&last&&last.busy&&s.decoded>=last.decoded){const dt=j.t-last.t;if(dt>0)$('tps').textContent=f((s.decoded-last.decoded)/dt,1)}else if(!s.busy)$('tps').textContent='-';
$('dec').textContent=f(s.decoded);const used=(s.prompt||0)+(s.decoded||0);$('ctx').textContent=f(used)+' / '+f(s.n_ctx);$('ctxb').style.width=(s.n_ctx?Math.min(100,100*used/s.n_ctx):0)+'%';
$('cache').textContent=s.prompt?f(100*(s.cached||0)/s.prompt)+'%':'-';$('cachel').textContent=f(s.cached)+' of '+f(s.prompt)+' prompt tokens';
$('avg').textContent=m.tokens_predicted_seconds_total?f(m.tokens_predicted_total/m.tokens_predicted_seconds_total,1):'-';
$('pavg').textContent=m.prompt_seconds_total?f(m.prompt_tokens_total/m.prompt_seconds_total,0):'-';
$('acc').textContent=m.spec_decode_num_draft_tokens_total?f(100*m.spec_decode_num_accepted_tokens_total/m.spec_decode_num_draft_tokens_total)+'%':'-';
$('vram').textContent=g.vram_free_gib!=null?f(g.vram_free_gib,2)+' GiB':'-';$('prof').textContent=(g.profile||'')+(g.n_ctx?' - ctx '+f(g.n_ctx):'');
last={t:j.t,busy:s.busy,decoded:s.decoded};}catch(e){$('st').textContent='- not reachable'}}
let curMode='';const MODES=['AUTO','MAX','BALANCED','LEAN'];
function drawModes(){$('modes').innerHTML='';for(const m of MODES){const b=document.createElement('button');b.textContent=m;b.setAttribute('aria-pressed',m===curMode);
b.onclick=async()=>{const r=await fetch('approvals/mode',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'approvals'},body:JSON.stringify({mode:m})});
if(r.ok){curMode=m;$('mmsg').textContent='Mode set to '+m+'. A different context size applies when the model next reloads; it never interrupts a reply.'}
else if(r.status===401){$('mmsg').innerHTML='Log in with your PIN on the <a href="approvals">approvals page</a> first, then come back.'}
else{$('mmsg').textContent='Could not switch: '+r.status}drawModes();};$('modes').appendChild(b);}}
const _t=tick;tick=async()=>{await _t();try{const j=await (await fetch('stats.json',{cache:'no-store'})).json();const g=j.gov||{};if(g.mode&&g.mode!==curMode){curMode=g.mode;drawModes()}}catch(e){}};
drawModes();tick();setInterval(tick,1000);
</script></body></html>"""

def make_handler(synth, whisper_url=WHISPER_URL):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype, extra=None):
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items(): self.send_header(k, v)
            self.end_headers(); self.wfile.write(body)
        def log_message(self, *a): pass
        def _body(self, limit):
            if "chunked" in self.headers.get("Transfer-Encoding", "").lower(): raise ValueError("chunked uploads are not supported; send Content-Length")
            n = int(self.headers.get("Content-Length", 0))
            if n < 0 or n > limit: self.close_connection = True; return None
            return self.rfile.read(n) if n else b""
        def _approvals(self, method):
            """Pass /approvals* through to the tool gateway's approval page (tailnet users reach it as /tts/approvals)."""
            body = self._body(8192) if method == "POST" else None
            hdrs = {k: self.headers[k] for k in ("Content-Type", "Cookie", "X-Requested-With") if self.headers.get(k)}
            req = urllib.request.Request(APPROVALS_URL + self.path, data=body, method=method, headers=hdrs)
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    extra = {"Set-Cookie": r.headers["Set-Cookie"]} if r.headers.get("Set-Cookie") else {}
                    self._send(r.status, r.read(), r.headers.get("Content-Type", "text/plain"), extra)
            except urllib.error.HTTPError as e:
                self._send(e.code, e.read(), e.headers.get("Content-Type", "text/plain"))
            except urllib.error.URLError:
                self._send(502, b"the tool gateway is not running", "text/plain")
        def _outbox(self):
            """Pass /outbox* through to the gateway's approvals server (shared files/websites), streaming the body."""
            hdrs = {}
            req = urllib.request.Request(APPROVALS_URL + self.path, method="GET", headers=hdrs)   # no cookies: outbox links are token-only
            try:
                r = urllib.request.urlopen(req, timeout=60)
            except urllib.error.HTTPError as e:
                r = e
            except urllib.error.URLError:
                return self._send(502, b"the tool gateway is not running", "text/plain")
            try:
                self.send_response(r.status if hasattr(r, "status") else r.code)
                for k in ("Content-Type", "Content-Length", "Content-Disposition", "Content-Security-Policy",
                          "X-Content-Type-Options"):
                    if r.headers.get(k): self.send_header(k, r.headers[k])
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk: break
                    self.wfile.write(chunk)
            finally:
                r.close()
        def do_GET(self):
            if self.path.startswith("/approvals"): return self._approvals("GET")
            if self.path.startswith("/outbox"): return self._outbox()
            p = self.path.split("?")[0].rstrip("/")
            if p.endswith("/stats.json"): return self._send(200, json.dumps(live_stats()).encode(), "application/json")
            if p.endswith("/stats"): return self._send(200, STATS_PAGE, "text/html; charset=utf-8")
            if self.path.split("?")[0].rstrip("/").endswith("/voices"):
                self._send(200, json.dumps({k: v[2] for k, v in VOICES.items()}).encode(), "application/json")
            else:
                self._send(200, b"ok", "text/plain")
        def do_POST(self):
            path = self.path.split("?")[0].rstrip("/")
            if path.startswith("/approvals"): return self._approvals("POST")
            try:
                if path.endswith("/audio/transcriptions"): return self._transcribe()
                # /tts, /v1/audio/speech, and (as in the original server) any other POST path: `tailscale serve --set-path=/tts`
                # can strip the mount path, so the phone voice page may arrive as POST / .
                return self._speak()
            except ValueError as e:
                self._send(400, str(e).encode(), "text/plain")
            except Exception as e:
                self._send(500, str(e).encode(), "text/plain")
        def _speak(self):
            raw = self._body(MAX_JSON)
            if raw is None: return self._send(413, b"request too large", "text/plain")
            try: req = json.loads(raw or b"{}"); speed = float(req.get("speed") or 1.05)
            except (ValueError, TypeError, AttributeError): return self._send(400, b"bad request body", "text/plain")
            text = clean(str(req.get("text") or req.get("input") or ""))[:1200]
            if not text: return self._send(400, b"no text", "text/plain")
            vid, lang, _ = resolve_voice(req.get("voice"))
            speed = min(1.4, max(0.8, speed))
            t = time.time(); body = synth(text, vid, lang, speed)
            self._send(200, body, "audio/wav", {"X-Synth-Seconds": "%.2f" % (time.time() - t)})
        def _transcribe(self):
            body = self._body(MAX_AUDIO)
            if body is None: return self._send(413, b"audio too large (25 MB limit)", "text/plain")
            req = urllib.request.Request(whisper_url, data=body, method="POST", headers={"Content-Type": self.headers.get("Content-Type", "application/octet-stream")})
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    self._send(r.status, r.read(), r.headers.get("Content-Type", "application/json"))
            except urllib.error.HTTPError as e:
                self._send(e.code, e.read(), e.headers.get("Content-Type", "text/plain"))
            except urllib.error.URLError as e:
                self._send(502, ("speech-to-text server not reachable at %s: %s" % (whisper_url, e.reason)).encode(), "text/plain")
    return H

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), make_handler(make_kokoro_synth())).serve_forever()
