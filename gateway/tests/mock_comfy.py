"""Tiny stand-in for ComfyUI's HTTP API, used by test_video.py. Usage: python mock_comfy.py <port> <mode> <logfile>
modes: ok | error | crash (exits after accepting a prompt) | hang (never finishes) | slow (finishes after 2 s)"""
import json, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
PORT, MODE, LOG = int(sys.argv[1]), sys.argv[2], sys.argv[3]
HIST = {}
def log(x): open(LOG, "a").write(x + "\n")
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, obj, code=200, raw=None):
        b = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.startswith("/system_stats"): return self.send({"system": {"os": "mock"}})
        if self.path.startswith("/history/"):
            pid = self.path.split("/")[-1]; h = HIST.get(pid)
            if h and MODE == "slow" and time.time() < h["ready"]: return self.send({})
            if h and MODE in ("hang", "crash"): return self.send({})
            return self.send({pid: h["entry"]} if h else {})
        if self.path.startswith("/view"): return self.send(None, raw=b"FAKEMP4DATA")
        self.send({}, 404)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/interrupt": log("interrupt"); return self.send({})
        if self.path == "/prompt":
            blob = json.dumps(body["prompt"]); log("prompt " + blob)
            if "{{" in blob: return self.send({"error": "unfilled placeholder", "node_errors": {"1": "x"}}, 400)
            pid = "p%d" % (len(HIST) + 1)
            if MODE == "error":
                HIST[pid] = {"ready": 0, "entry": {"status": {"status_str": "error", "messages": [["execution_error", {"exception_message": "OOM on XPU"}]]}, "outputs": {}}}
            else:
                HIST[pid] = {"ready": time.time() + 2, "entry": {"status": {"status_str": "success", "messages": []},
                             "outputs": {"9": {"videos": [{"filename": "clip_00001.mp4", "subfolder": "", "type": "output"}]}}}}
            if MODE == "crash": threading.Timer(0.3, lambda: __import__("os")._exit(3)).start()
            return self.send({"prompt_id": pid, "node_errors": {}})
        self.send({}, 404)
ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
