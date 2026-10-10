"""Private neural TTS for Qwen Voice (Kokoro-82M, ONNX, CPU). POST /tts {"text","voice","speed"} -> audio/wav. GET /voices."""
import io, json, os, re, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import numpy as np, soundfile as sf
from kokoro_onnx import Kokoro

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("OMP_NUM_THREADS", "6")
kokoro = Kokoro(os.path.join(HERE, "kokoro-v1.0.onnx"), os.path.join(HERE, "voices-v1.0.bin"))
LOCK = threading.Lock()
VOICES = {  # curated natural English voices
    "emma": ("bf_emma", "en-gb", "Emma - British female, warm"),
    "isabella": ("bf_isabella", "en-gb", "Isabella - British female, bright"),
    "george": ("bm_george", "en-gb", "George - British male, calm"),
    "lewis": ("bm_lewis", "en-gb", "Lewis - British male, deep"),
    "heart": ("af_heart", "en-us", "Heart - American female, natural"),
    "michael": ("am_michael", "en-us", "Michael - American male"),
}

def clean(t):
    t = re.sub(r"```.*?```", " code block omitted. ", t, flags=re.S)
    t = re.sub(r"[*_#`>|]", " ", t)
    t = t.replace("&", " and ").replace("$", " dollars ") if False else t.replace("&", " and ")
    return re.sub(r"\s+", " ", t).strip()

class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.rstrip("/").endswith("/voices"):
            self._send(200, json.dumps({k: v[2] for k, v in VOICES.items()}).encode(), "application/json")
        else:
            self._send(200, b"ok", "text/plain")
    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0)); req = json.loads(self.rfile.read(n) or b"{}")
            text = clean(str(req.get("text", "")))[:1200]
            if not text: return self._send(400, b"no text", "text/plain")
            vid, lang, _ = VOICES.get(req.get("voice", "emma"), VOICES["emma"])
            speed = float(req.get("speed", 1.05)); speed = min(1.4, max(0.8, speed))
            t = time.time()
            with LOCK:
                samples, sr = kokoro.create(text, voice=vid, speed=speed, lang=lang)
            buf = io.BytesIO(); sf.write(buf, np.asarray(samples, dtype=np.float32), sr, format="WAV", subtype="PCM_16")
            self.send_response(200); self.send_header("Content-Type", "audio/wav"); body = buf.getvalue()
            self.send_header("Content-Length", str(len(body))); self.send_header("X-Synth-Seconds", f"{time.time()-t:.2f}")
            self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)
        except Exception as e:
            self._send(500, str(e).encode(), "text/plain")

if __name__ == "__main__":
    kokoro.create("Ready.", voice="bf_emma", speed=1.0, lang="en-gb")  # warm-up
    ThreadingHTTPServer(("127.0.0.1", 8092), H).serve_forever()
