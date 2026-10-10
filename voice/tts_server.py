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

def make_handler(synth, whisper_url=WHISPER_URL):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype, extra=None):
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items(): self.send_header(k, v)
            self.end_headers(); self.wfile.write(body)
        def log_message(self, *a): pass
        def _body(self, limit):
            n = int(self.headers.get("Content-Length", 0))
            if n > limit: return None
            return self.rfile.read(n) if n else b""
        def do_GET(self):
            if self.path.split("?")[0].rstrip("/").endswith("/voices"):
                self._send(200, json.dumps({k: v[2] for k, v in VOICES.items()}).encode(), "application/json")
            else:
                self._send(200, b"ok", "text/plain")
        def do_POST(self):
            path = self.path.split("?")[0].rstrip("/")
            try:
                if path.endswith("/audio/transcriptions"): return self._transcribe()
                # /tts, /v1/audio/speech, and (as in the original server) any other POST path: `tailscale serve --set-path=/tts`
                # can strip the mount path, so the phone voice page may arrive as POST / .
                return self._speak()
            except Exception as e:
                self._send(500, str(e).encode(), "text/plain")
        def _speak(self):
            raw = self._body(MAX_JSON)
            if raw is None: return self._send(413, b"request too large", "text/plain")
            req = json.loads(raw or b"{}")
            text = clean(str(req.get("text") or req.get("input") or ""))[:1200]
            if not text: return self._send(400, b"no text", "text/plain")
            vid, lang, _ = resolve_voice(req.get("voice"))
            speed = min(1.4, max(0.8, float(req.get("speed", 1.05))))
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
