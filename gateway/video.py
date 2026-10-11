"""Local video generation for the tool gateway: Qwen (or any MCP client) queues a job, a worker hands the GPU from the LLM to ComfyUI,
runs one workflow, collects the clip, frees the GPU completely and lets the governor reload the LLM.

Why a hand-off and not "run both": the Arc Pro B60 has 24 GB. A 27B model with its 64K cache fills it, and a 22B video model with its text
encoder needs most of it too. Killing the ComfyUI process is the only release of XPU memory that is guaranteed (unloading inside ComfyUI
has crashed on XPU), so every job starts ComfyUI and ends by killing it.

Safety: video_generate is a "write" tool, so the gateway asks for the owner's PIN approval before the job is queued (it interrupts the
LLM). The worker honours the gateway kill file, a per-job timeout, a queue cap and parameter limits, only reads input images from the
allowed folders, and restores the governor mode even if it crashes (a lock file records the previous mode; a restart repairs it).

Workflows are JSON files in workflows_dir: {"meta": {...params...}, "prompt": <ComfyUI API graph with {{placeholders}}>}. The meta block
makes each workflow self-describing, so the tool's arguments are validated and clamped before anything is queued.

Two-process split: a workflow whose meta has "stages": [name, ...] runs those stage graphs (workflows_dir/stages/<name>.json, falling back to
workflows_dir/<name>.json) in order under ONE job id and ONE GPU lease. ComfyUI is killed and restarted between stages, so the text encoder's
host RAM is returned to the OS before the big transformer loads (what Q6_K needs on 32 GB). The stages hand over through a conditioning file
(ElzSaveConditioning / ElzLoadConditioning) in a per-job folder that is deleted whatever the outcome. Workflows without "stages" are untouched.

Everything outside this file (llama-swap, ComfyUI, process control) is reached through small functions on `Env`, so the tests run the
whole lifecycle against mock servers.
"""
import copy, json, math, os, random, re, secrets, shutil, subprocess, sys, threading, time, urllib.error, urllib.parse, urllib.request

STATES = ("queued", "waiting", "starting", "running", "done", "failed", "cancelled")
ACTIVE = ("waiting", "starting", "running")
PH = re.compile(r"\{\{(\w+)\}\}")
FULL_PH = re.compile(r"^\{\{(\w+)\}\}$")
MEDIA_KEYS = ("videos", "gifs", "images", "audio")
DRIVE_MODES = ("all", "favourites", "off")
LLM_MODE = "MAX"                                   # the governor mode the LLM runs in when nothing overrides it (what _take_gpu falls back to)
VIDEO_MODE = "OFF"                                 # the governor mode that keeps the LLM off the GPU


class VideoError(Exception):
    pass


class VideoBusy(VideoError):
    """The request clashes with a queued/running job or an active ComfyUI session (HTTP 409)."""


class Cfg:
    def __init__(self, c, base_dir="."):
        c = c or {}
        j = lambda p: p if (not p or os.path.isabs(p)) else os.path.join(base_dir, p)
        self.comfy_dir = c.get("comfy_dir") or ""
        self.comfy_cmd = list(c.get("comfy_cmd") or [])
        self.comfy_env = dict(c.get("comfy_env") or {})
        self.comfy_url = str(c.get("comfy_url") or "http://127.0.0.1:8188").rstrip("/")
        self.workflows_dir = j(c.get("workflows_dir") or "workflows")
        self.input_dir = c.get("input_dir") or ""            # ComfyUI's input folder (images are copied here)
        self.out_dir = c.get("out_dir") or ""                # finished clips; point it inside the outbox's allowed folders so share_file links work
        self.allowed_roots = [os.path.realpath(p) for p in (c.get("allowed_roots") or [])]
        self.max_queue = max(1, int(c.get("max_queue") or 10))
        self.job_timeout_s = max(1.0, float(c.get("job_timeout_s") or 3600))
        self.start_timeout_s = max(5, float(c.get("start_timeout_s") or 300))
        try:
            self.comfy_settle_s = max(0.0, float(c.get("comfy_settle_s", 3.0)))      # pause after the LLM has exited, before ComfyUI is spawned (a spawn straight after the exit has stalled at start-up)
        except (TypeError, ValueError):
            self.comfy_settle_s = 3.0
        try:
            self.comfy_stall_s = max(0.05, float(c.get("comfy_stall_s", 45)))        # a fresh ComfyUI that wrote nothing to its log this long and does not answer is killed and spawned once more
        except (TypeError, ValueError):
            self.comfy_stall_s = 45.0
        self.poll_s = max(0.05, float(c.get("poll_s") or 3))
        self.tick_s = max(0.05, float(c.get("tick_s") or 5))
        self.keep_jobs = max(10, int(c.get("keep_jobs") or 200))
        llm = c.get("llm") or {}
        self.swap_url = str(llm.get("swap_url") or "http://127.0.0.1:8090").rstrip("/")
        self.api_key_file = llm.get("api_key_file") or ""
        self.model_id = llm.get("model_id") or ""
        self.llm_process = llm.get("process") or "llama-server.exe"
        self.quiet_s = max(0.0, float(llm.get("quiet_s", 90)))
        self.mode_file = llm.get("governor_mode_file") or ""
        self.unload_timeout_s = max(5, float(llm.get("unload_timeout_s") or 90))
        self.ntfy_url = str(c.get("ntfy_url") or "").strip()                 # push notification when a job ends (done or failed); empty = off
        self.ntfy_topic = str(c.get("ntfy_topic") or "").strip()
        self.ntfy_click_base = str(c.get("ntfy_click_base") or "").strip()  # base URL of the gateway, for the notification's tap target
        self.ntfy_include_prompt = bool(c.get("ntfy_include_prompt", False))
        self.drive_dir = str(c.get("drive_dir") or "").strip()                 # finished clips are copied here (a synced Google Drive folder); empty = off
        dm = str(c.get("drive_mode") or "off").strip().lower()
        self.drive_mode = dm if dm in DRIVE_MODES else "off"                    # "all" | "favourites" | "off"
        self.ffmpeg = str(c.get("ffmpeg_path") or c.get("ffmpeg") or "").strip()      # path to ffmpeg (bare "ffmpeg" = from PATH when loudnorm is on)
        self.loudnorm = bool(c.get("loudnorm", False))                         # level every clip's sound to -16 LUFS after the render
        if self.loudnorm and not self.ffmpeg:
            self.ffmpeg = "ffmpeg"
        self.loudnorm = self.loudnorm and bool(self.ffmpeg)
        try:
            self.session_idle_s = max(1.0, float(c.get("comfy_session_idle_min", 20)) * 60)       # interactive ComfyUI session: stop after this long with no activity
        except (TypeError, ValueError):
            self.session_idle_s = 1200.0
        self.tailnet_port = int(c["comfy_tailnet_port"]) if isinstance(c.get("comfy_tailnet_port"), int) and not isinstance(c.get("comfy_tailnet_port"), bool) else None
        try:
            self.session_watch_s = max(0.05, float(c.get("comfy_session_watch_s", 5)))      # how often a session looks at ComfyUI's /history for renders made in its own UI
        except (TypeError, ValueError):
            self.session_watch_s = 5.0
        self.keep_raw = bool(c.get("keep_raw", False))                          # keep the un-levelled original next to the clip as <name>_raw.mp4
        self.enabled = bool(self.comfy_cmd and self.comfy_dir)

    def api_key(self):
        try:
            return open(self.api_key_file, encoding="utf-8-sig").read().strip() if self.api_key_file else ""
        except OSError:
            return ""


# ---------- the outside world (replaced in tests) ----------
class Env:
    def http(self, method, url, body=None, headers=None, timeout=10):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        data = body.encode("utf-8") if isinstance(body, str) else body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)   # str/bytes go as they are (ntfy)
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            t = r.read()
        try:
            return json.loads(t) if t.strip()[:1] in (b"{", b"[") else {}
        except ValueError:
            return {}

    def popen(self, cmd, cwd, env, log_path):
        e = dict(os.environ)
        e.update(env)
        e.setdefault("PYTHONUNBUFFERED", "1")                 # start-up lines must reach comfy.log at once (an empty log is the stall signal)
        # stdin=DEVNULL: without it Windows hands the child this process's stdin, the MCP stdio pipe; a
        # child touching that pipe blocks behind our pending read, so ComfyUI hung before any output.
        return subprocess.Popen(cmd, cwd=cwd, env=e, stdin=subprocess.DEVNULL, stdout=open(log_path, "ab"), stderr=subprocess.STDOUT)

    def sleep(self, secs):
        time.sleep(secs)

    def kill_tree(self, proc):
        if proc is None or proc.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/f", "/t", "/pid", str(proc.pid)], capture_output=True)
        else:
            proc.terminate()
            try:
                proc.wait(10)
            except Exception:
                proc.kill()
        try:
            proc.wait(30)
        except Exception:
            pass

    def kill_pid(self, pid):
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/f", "/t", "/pid", str(int(pid))], capture_output=True)
            else:
                os.kill(int(pid), 9)
        except Exception:
            pass

    def run_cmd(self, cmd, timeout=600):
        """Run a helper program (ffmpeg). Returns (exit code, last of its stderr)."""
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return r.returncode, (r.stderr or b"").decode("utf-8", "replace")[-400:]

    def fetch(self, url, timeout=300):
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read()

    def process_running(self, image_name):
        if os.name != "nt":
            return False
        o = subprocess.run(["tasklist", "/fi", "imagename eq %s" % image_name, "/fo", "csv", "/nh"], capture_output=True, text=True).stdout
        return image_name.lower() in o.lower()


# ---------- workflow templates ----------
def load_workflows(d):
    out = {}
    if not d or not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        try:
            w = json.load(open(os.path.join(d, fn), encoding="utf-8-sig"))
            if isinstance(w.get("prompt"), dict) and isinstance(w.get("meta"), dict):
                out[fn[:-5]] = w
        except (OSError, ValueError):
            continue
    return out


STAGE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")


def load_stage(d, name):
    """One stage graph of a staged workflow: workflows_dir/stages/<name>.json (kept out of the Studio list), else workflows_dir/<name>.json."""
    if not isinstance(name, str) or not STAGE_NAME.fullmatch(name) or ".." in name:
        raise VideoError("invalid stage name %r" % (name,))
    for p in (os.path.join(d or "", "stages", name + ".json"), os.path.join(d or "", name + ".json")):
        if not os.path.isfile(p):
            continue
        try:
            w = json.load(open(p, encoding="utf-8-sig"))
        except (OSError, ValueError) as ex:
            raise VideoError("stage %r is unreadable (%s)" % (name, ex))
        if not (isinstance(w.get("prompt"), dict) and isinstance(w.get("meta"), dict) and w["prompt"]):
            raise VideoError("stage %r is not a workflow file with a prompt graph" % name)
        if w["meta"].get("stages"):
            raise VideoError("stage %r has stages of its own; stages do not nest" % name)
        return w
    raise VideoError("stage workflow %r not found (looked in %s)" % (name, os.path.join(d or "", "stages")))


def stage_names(wf):
    """The ordered stage names of a staged workflow, [] for an ordinary one. Raises VideoError for a malformed list."""
    st = ((wf or {}).get("meta") or {}).get("stages")
    if st in (None, [], ()):
        return []
    if not isinstance(st, list) or not all(isinstance(x, str) and x for x in st):
        raise VideoError("meta.stages must be a list of stage names")
    return list(st)


def stage_weights(meta, n):
    """Share of the 0-100 progress bar each stage owns. Default: the first (encode) stage 15 %, the rest split the other 85 %."""
    w = meta.get("stage_weights")
    if not (isinstance(w, list) and len(w) == n and all(isinstance(x, (int, float)) and x > 0 for x in w)):
        w = [100.0] if n == 1 else [15.0] + [85.0 / (n - 1)] * (n - 1)
    tot = float(sum(w))
    return [100.0 * x / tot for x in w]


def snap_frames(n, rule):
    """LTX and Wan want frame counts of the form 8k+1."""
    if rule == "8n+1":
        return max(9, int(round((n - 1) / 8.0)) * 8 + 1)
    return max(1, int(n))


def resolve_params(wf, raw, cfg):
    """Validate and clamp the caller's arguments against the workflow's meta. Returns (values, files) where files are images to copy."""
    try:
        return _resolve(wf, raw, cfg)
    except (ValueError, TypeError, OverflowError) as ex:
        raise VideoError("invalid parameter value (%s)" % ex)


def _resolve(wf, raw, cfg):
    meta, spec = wf["meta"], wf["meta"].get("params") or {}
    vals, files = {}, {}
    unknown = [k for k in raw if raw[k] not in (None, "", 0, -1) and k not in spec and k not in ("seconds",)]
    if unknown:
        raise VideoError("this workflow does not take: %s (it takes: %s)" % (", ".join(sorted(unknown)), ", ".join(sorted(spec))))
    for name, p in spec.items():
        v = raw.get(name)
        empty = v in (None, "") or (p.get("type") in ("int", "float") and v == 0 and p.get("zero_is_default", True))
        if name == "seed" and (v in (None, "", -1)):
            vals[name] = random.randint(0, 2 ** 31 - 1)
            continue
        if empty:
            if p.get("required"):
                raise VideoError("%s is required" % name)
            if "default" in p:
                vals[name] = p["default"]
            continue
        t = p.get("type", "str")
        if t == "int":
            v = int(v)
            vals[name] = max(int(p.get("min", v)), min(int(p.get("max", v)), v))
            if p.get("multiple_of"):
                m = int(p["multiple_of"])
                vals[name] = max(m, (vals[name] // m) * m)
        elif t == "float":
            if not math.isfinite(float(v)):
                raise VideoError("%s must be a finite number" % name)
            vals[name] = max(float(p.get("min", v)), min(float(p.get("max", v)), float(v)))
        elif t == "image":
            files[name] = str(v)
        else:
            s = str(v)
            vals[name] = s[: int(p.get("max_len", 2000))]
            if p.get("choices") and vals[name] not in [str(c) for c in p["choices"]]:      # an enum param (quality): refuse anything not listed
                raise VideoError("%s must be one of: %s" % (name, ", ".join(str(c) for c in p["choices"])))
    if isinstance(vals.get("seed"), int):
        vals["seed"] = max(0, min(2 ** 32 - 1, vals["seed"]))
    if meta.get("fps") and "seconds" in vals and "frames" not in spec:     # seconds feeds a graph node directly: keep fps*seconds = 8n
        fps = float(meta["fps"])
        vals["seconds"] = round(max(1, round(float(vals["seconds"]) * fps / 8)) * 8 / fps, 4)
    if "frames" in spec and not raw.get("frames") and raw.get("seconds"):
        fps = float(meta.get("fps", 24))
        want = snap_frames(float(raw["seconds"]) * fps + 1, meta.get("frames_rule"))
        vals["frames"] = max(int(spec["frames"].get("min", want)), min(int(spec["frames"].get("max", want)), want))
    elif "frames" in vals and meta.get("frames_rule"):
        vals["frames"] = snap_frames(vals["frames"], meta["frames_rule"])
    return vals, files


def fill_graph(graph, vals):
    """Substitute {{name}} placeholders. A string that is exactly one placeholder takes the value's own type (int stays int)."""
    def sub(x):
        if isinstance(x, dict):
            return {k: sub(v) for k, v in x.items()}
        if isinstance(x, list):
            return [sub(v) for v in x]
        if isinstance(x, str):
            m = FULL_PH.match(x)
            if m:
                if m.group(1) not in vals:
                    raise VideoError("workflow needs a value for %s" % m.group(1))
                return vals[m.group(1)]
            return PH.sub(lambda mm: str(vals.get(mm.group(1), mm.group(0))), x)
        return x
    return sub(copy.deepcopy(graph))


# ---------- queue + worker ----------
class Queue:
    def __init__(self, cfg, state_dir, kill_path=None, env=None, share=None):
        self.cfg, self.env, self.kill_path, self.share = cfg, env or Env(), kill_path, share
        self.dir = os.path.join(state_dir, "video")
        self.out_dir = cfg.out_dir or os.path.join(self.dir, "out")
        os.makedirs(self.dir, exist_ok=True)                  # not implied by out_dir when the clips live elsewhere
        os.makedirs(self.out_dir, exist_ok=True)
        self.jobs_path = os.path.join(self.dir, "jobs.json")
        self.lock_path = os.path.join(self.dir, "gpu.lock")
        self.log_path = os.path.join(self.dir, "comfy.log")
        self.cond_root = os.path.join(self.dir, "cond")      # per-job conditioning hand-over folders of staged workflows
        self.lock = threading.RLock()
        self.cancel = set()
        self.proc = None
        self.last_busy = time.time()
        self.jobs = self._load()
        self._stop = threading.Event()
        self.thread = None
        self.session = None                                   # the interactive ComfyUI session, or None (see session_start)
        self._sess_thread = None
        self.own_pids = set()                                 # ComfyUI prompt ids the queue itself submitted (the session watcher must not ingest those twice)
        self._recover()

    # -- persistence
    def _load(self):
        try:
            return json.load(open(self.jobs_path, encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _save(self):
        tmp = self.jobs_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._retained(), f)
        os.replace(tmp, self.jobs_path)

    def _retained(self):
        """What jobs.json keeps: the newest keep_jobs jobs plus every favourite, however old. Call with self.lock held."""
        newest = {id(j) for j in self.jobs[-self.cfg.keep_jobs:]}
        return [j for j in self.jobs if id(j) in newest or j.get("fav")]

    def _recover(self):
        """A crash must never leave the LLM unloaded or the governor stuck on OFF."""
        with self.lock:
            hit = False
            for j in self.jobs:
                if j["state"] in ACTIVE:
                    hit = True
                    j["state"], j["error"], j["ended"] = "failed", "the gateway restarted while this job was running", time.time()
            self._save()
            d = self._lock_read()
            if d and d.get("pid"):                           # the old ComfyUI is still holding the GPU
                self.env.kill_pid(d["pid"])
        shutil.rmtree(self.cond_root, ignore_errors=True)    # no job is active after a restart, so any hand-over file is an orphan
        self._restore_mode()

    # -- governor hand-off
    def _read_mode(self):
        try:
            return (open(self.cfg.mode_file).read().strip() or "MAX") if self.cfg.mode_file else None
        except OSError:
            return None

    def _lock_read(self):
        """gpu.lock is JSON {"mode": previous governor mode, "pid": ComfyUI pid}; an old plain-text lock holds just the mode."""
        try:
            t = open(self.lock_path).read().strip()
        except OSError:
            return None
        try:
            d = json.loads(t)
            if isinstance(d, dict):
                return d
        except ValueError:
            pass
        return {"mode": t or "MAX"}

    def _lock_set(self, **kw):
        d = self._lock_read() or {}
        d.update(kw)
        with open(self.lock_path, "w") as f:
            json.dump(d, f)

    def _take_gpu(self):
        if not self.cfg.mode_file:
            return
        if not os.path.exists(self.lock_path):                        # never overwrite the first-recorded mode
            prev = self._read_mode() or "MAX"
            if prev.upper() == "OFF":
                prev = (self._hold() or {}).get("prev") or "MAX"
            self._lock_set(mode=prev)
        open(self.cfg.mode_file, "w").write("OFF\n")

    def _restore_mode(self):
        d = self._lock_read()
        if d is None:
            return
        try:
            if self.cfg.mode_file and d.get("mode"):
                open(self.cfg.mode_file, "w").write((VIDEO_MODE if self._hold() else str(d["mode"])) + "\n")      # Video mode stays on until the owner switches back
            os.remove(self.lock_path)
        except OSError:
            pass

    # -- Video / LLM mode (the Studio's one-tap switch)
    @property
    def hold_path(self):
        return os.path.join(self.dir, "video_hold.json")

    def _hold(self):
        try:
            d = json.load(open(self.hold_path, encoding="utf-8"))
            return d if isinstance(d, dict) else None
        except (OSError, ValueError):
            return None

    def busy(self):
        """True while any job is queued or active, or ComfyUI holds the GPU lease."""
        with self.lock:
            return os.path.exists(self.lock_path) or any(j["state"] in ("queued",) + ACTIVE for j in self.jobs)

    def mode_get(self):
        """{"mode": raw governor mode or None, "view": "video" | "llm", "hold": bool}: what the governor file says right now."""
        m = self._read_mode()
        if self._hold() and (m or "").upper() != VIDEO_MODE and not os.path.exists(self.lock_path):
            try:
                os.remove(self.hold_path)                          # the owner changed the governor by hand: Video mode is over
            except OSError:
                pass
        return {"mode": m, "view": "video" if (m or "").upper() == VIDEO_MODE or os.path.exists(self.lock_path) else "llm", "hold": bool(self._hold())}

    def mode_set(self, target, warm=True):
        """Switch the GPU between Video and the LLM. Returns the new mode_get(); raises VideoError when it cannot be done.
        video: governor mode OFF (the LLM is released), remembering the mode to return to. llm: that mode is written back (MAX if there was none)
        and the model is warmed in the background. Refused while a job is queued or running, because a render owns the governor file then."""
        if target not in ("video", "llm"):
            raise VideoError("mode must be video or llm")
        if not self.cfg.mode_file:
            raise VideoError("the governor mode file is not configured (llm.governor_mode_file), so the GPU cannot be switched from here")
        with self.lock:
            if self.session:
                raise VideoBusy("a ComfyUI session is active; stop it first")
            if self.busy():
                raise VideoBusy("a video job is queued or rendering; wait for it to finish or cancel it first")
            cur = (self._read_mode() or LLM_MODE).upper()
            try:
                if target == "video":
                    if not self._hold():
                        with open(self.hold_path, "w", encoding="utf-8") as f:
                            json.dump({"prev": cur if cur != VIDEO_MODE else LLM_MODE, "t": time.time()}, f)
                    open(self.cfg.mode_file, "w").write(VIDEO_MODE + "\n")
                else:
                    h = self._hold() or {}
                    back = h.get("prev") if isinstance(h.get("prev"), str) and h.get("prev") else (LLM_MODE if cur == VIDEO_MODE else cur)
                    open(self.cfg.mode_file, "w").write(str(back).upper() + "\n")
                    try:
                        os.remove(self.hold_path)
                    except OSError:
                        pass
            except OSError as ex:
                raise VideoError("could not write the governor mode file (%s)" % (ex.strerror or ex))
        if target == "llm" and warm:
            threading.Thread(target=self._warm_llm, name="llm-warm", daemon=True).start()
        if target == "video":                                  # unload now, so the next job does not wait for it
            threading.Thread(target=self._preunload, name="llm-unload", daemon=True).start()
        return self.mode_get()

    def _preunload(self):
        try:
            self._unload_llm()
        except Exception as ex:
            sys.stderr.write("video: LLM pre-unload failed (%r)\n" % (ex,))

    def _warm_llm(self):
        """Ask the LLM for one token so llama-swap loads it now rather than on the first chat. Best effort."""
        c = self.cfg
        if not c.model_id:
            return
        try:
            h = {"Authorization": "Bearer " + c.api_key()} if c.api_key() else {}
            self.env.http("POST", c.swap_url + "/v1/chat/completions", {"model": c.model_id, "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}, headers=h, timeout=240)
        except Exception as ex:
            sys.stderr.write("video: LLM warm-up failed (%r)\n" % (ex,))

    # -- public API
    def submit(self, workflow, raw, files_ok=True):
        wfs = load_workflows(self.cfg.workflows_dir)
        if workflow not in wfs:
            raise VideoError("unknown workflow %r. Available: %s" % (workflow, ", ".join(sorted(wfs)) or "(none installed)"))
        for st in stage_names(wfs[workflow]):                # a staged workflow must have every stage in place before it is queued
            load_stage(self.cfg.workflows_dir, st)
        vals, files = resolve_params(wfs[workflow], raw, self.cfg)
        for name, path in files.items():
            files[name] = self._check_image(path)
        with self.lock:
            if sum(1 for j in self.jobs if j["state"] in ("queued",) + ACTIVE) >= self.cfg.max_queue:
                raise VideoError("the video queue is full (%d jobs); wait for one to finish" % self.cfg.max_queue)
            j = dict(id=secrets.token_hex(4), workflow=workflow, params=vals, files=files, state="queued", created=time.time(), note="")
            self.jobs.append(j)
            self._save()
            pos = sum(1 for x in self.jobs if x["state"] in ("queued",) + ACTIVE and x["created"] <= j["created"])
        return j["id"], pos, wfs[workflow]["meta"].get("est_minutes", "unknown")

    def _check_image(self, path):
        real = os.path.realpath(path)
        if not self.cfg.allowed_roots:
            raise VideoError("image input is not enabled (no allowed_roots configured)")
        if not any(real == r or real.startswith(r.rstrip(os.sep) + os.sep) for r in self.cfg.allowed_roots):
            raise VideoError("that image is outside the shared folders")
        if not os.path.isfile(real) or os.path.splitext(real)[1].lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            raise VideoError("image must be an existing png, jpg or webp file")
        if os.path.getsize(real) > 25 * 2 ** 20:
            raise VideoError("image is larger than 25 MB")
        return real

    def get(self, jid):
        with self.lock:
            for j in self.jobs:
                if j["id"] == jid:
                    return dict(j)
        return None

    def _sidecars(self, j, files, t0, ended, extra=None):
        """Write <clip>.json (seed, workflow, params, timings) next to each clip. Once, when the job completes; never fails the job."""
        meta = {"job_id": j["id"], "workflow": j["workflow"], "params": j["params"], "seed": j["params"].get("seed"), "fav": bool((self.get(j["id"]) or j).get("fav")),
                "created": j["created"], "started": t0, "ended": ended, "queued_s": round(t0 - j["created"], 1), "render_s": round(ended - t0, 1)}
        meta.update(extra or {})
        for p in files:
            try:
                with open(p + ".json", "w", encoding="utf-8") as f:
                    json.dump(dict(meta, clip=os.path.basename(p)), f, indent=1)
            except OSError:
                pass

    def _ahead(self, j):
        return [x for x in self.jobs if x["state"] in ("queued",) + ACTIVE and x["created"] <= j["created"]]

    def status(self, jid):
        """Job state for agents: state, note, elapsed seconds, queue position (1 = next/running, 0 = not pending), ETA minutes, clip names when done."""
        with self.lock:
            j = next((x for x in self.jobs if x["id"] == jid), None)
            if not j:
                return None
            d = {"job_id": j["id"], "state": j["state"], "workflow": j["workflow"], "elapsed_s": int((j.get("ended") or time.time()) - j["created"])}
            if j.get("note"):
                d["note"] = j["note"]
            if j.get("error"):
                d["error"] = j["error"]
            if j["state"] in ("queued",) + ACTIVE:
                ahead = self._ahead(j)
                wfs = load_workflows(self.cfg.workflows_dir)
                d["queue_position"] = len(ahead)
                d["eta_min"] = sum(est_minutes(wfs.get(x["workflow"])) for x in ahead)
            if j["state"] == "done":
                d["clips"] = [os.path.basename(p) for p in j.get("files_out") or []]
        return d

    def result(self, jid):
        """Outcome of a job: clips, share links and metadata when done; the error when failed; otherwise just the state. None if unknown."""
        j = self.get(jid)
        if not j:
            return None
        d = {"job_id": jid, "state": j["state"]}
        if j["state"] == "failed":
            d["error"] = j.get("error", "")
        elif j["state"] == "done":
            clips = j.get("files_out") or []
            d["clips"] = [os.path.basename(p) for p in clips]
            d["links"] = j.get("links") or ([self.share(p) for p in clips] if self.share else [])
            d["meta"] = {"workflow": j["workflow"], "params": j["params"], "seed": j["params"].get("seed"), "seconds": j.get("seconds"),
                         "wall_s": round(j["ended"] - j["created"], 1) if j.get("ended") else None}
        elif j["state"] != "cancelled":
            d["note"] = "not finished; poll video_status"
        return d

    def recent(self, n=10):
        with self.lock:
            return [dict(j) for j in self.jobs[-n:]][::-1]

    def favourites(self):
        """Every starred job (newest first), however old: the recent list alone would lose them once 40 newer jobs exist."""
        with self.lock:
            return [dict(j) for j in self.jobs if j.get("fav")][::-1]

    def set_fav(self, jid, fav):
        """Star or unstar a job. Starred jobs are kept by the jobs.json retention, and their start images by the Studio upload trim.
        The flag is also written into each clip's sidecar JSON. Returns False for an unknown job."""
        with self.lock:
            j = next((x for x in self.jobs if x["id"] == jid), None)
            if not j:
                return False
            j["fav"] = bool(fav)
            self._save()
            clips = list(j.get("files_out") or [])
        if fav and self.cfg.drive_mode == "favourites" and j.get("state") == "done":
            threading.Thread(target=self.drive_sync, args=(jid,), name="drive-sync", daemon=True).start()
        for p in clips:                                          # best effort, like the sidecar itself
            try:
                with open(p + ".json", encoding="utf-8") as f:
                    meta = json.load(f)
                meta["fav"] = bool(fav)
                with open(p + ".json", "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=1)
            except (OSError, ValueError):
                pass
        return True

    def cancel_job(self, jid):
        with self.lock:
            j = next((x for x in self.jobs if x["id"] == jid), None)
            if not j:
                return "no such job"
            if j["state"] == "queued":
                j["state"], j["ended"] = "cancelled", time.time()
                self._save()
                return "cancelled (it had not started)"
            if j["state"] in ACTIVE:
                self.cancel.add(jid)
                return "cancel requested; the job stops at the next check and ComfyUI is closed"
            return "already %s" % j["state"]

    def delete_job(self, jid):
        """Remove a finished job and its clips (the Studio library's delete). Active or queued jobs must be cancelled first."""
        import shutil
        with self.lock:
            j = next((x for x in self.jobs if x["id"] == jid), None)
            if not j:
                return False, "no such job"
            if j["state"] in ("queued",) + ACTIVE:
                return False, "cancel it first"
            self.jobs.remove(j)
            self._save()
        d = os.path.realpath(os.path.join(self.out_dir, jid))
        if re.match(r"^[0-9a-f]{8}$", jid) and os.path.dirname(d) == os.path.realpath(self.out_dir):
            shutil.rmtree(d, ignore_errors=True)
        return True, "deleted"

    # -- worker
    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self._stop.clear()
        self.thread = threading.Thread(target=self._loop, name="video-worker", daemon=True)
        self.thread.start()

    def stop(self):
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=15)
        if self.session:
            try:
                self.session_stop(force=True)
            except Exception:
                pass

    def _killed(self):
        return bool(self.kill_path and os.path.exists(self.kill_path))

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:                               # the worker must never die
                sys.stderr.write("video worker error: %r\n" % (e,))
            self._stop.wait(self.cfg.tick_s)

    def llm_quiet(self):
        """True when the LLM has had no request in flight for quiet_s (or is not loaded at all)."""
        c = self.cfg
        h = {"Authorization": "Bearer " + c.api_key()} if c.api_key() else {}
        try:
            running = (self.env.http("GET", c.swap_url + "/running", headers=h, timeout=5) or {}).get("running") or []
        except Exception:
            return False                                         # cannot tell: do not take the GPU
        busy = False
        for m in running:
            try:
                slots = self.env.http("GET", str(m.get("proxy", "")).rstrip("/") + "/slots", timeout=5)
                if isinstance(slots, list) and any(s.get("is_processing") for s in slots):
                    busy = True
            except Exception:
                busy = True
        if not running:
            return True                                          # nothing loaded: the GPU is free right now
        if busy or m_state_loading(running):
            self.last_busy = time.time()
            return False
        return (time.time() - self.last_busy) >= c.quiet_s

    def tick(self):
        with self.lock:
            nxt = next((j for j in self.jobs if j["state"] in ("queued", "waiting")), None)
            if nxt is None:
                return
            sess = self.session
            if sess is not None and sess["state"] != "ready":
                return                                           # the session is still starting or stopping: the job waits for it
            if self._killed():
                nxt["state"], nxt["error"], nxt["ended"] = "failed", "KILLED: the gateway kill switch is on", time.time()
                self._save()
                return
            if nxt["id"] in self.cancel:
                self.cancel.discard(nxt["id"])
                nxt["state"], nxt["ended"], nxt["note"] = "cancelled", time.time(), ""
                self._save()
                return
            if sess is None:
                nxt["state"] = "waiting"
                nxt["note"] = "waiting for the LLM to be quiet for %d s" % self.cfg.quiet_s
                self._save()
        if sess is None and not self.llm_quiet():
            return
        self.run(nxt["id"])

    def _set(self, jid, **kw):
        with self.lock:
            for j in self.jobs:
                if j["id"] == jid:
                    j.update(kw)
            self._save()

    def run(self, jid):
        c, e = self.cfg, self.env
        j = self.get(jid)
        t0 = time.time()
        with self.lock:
            sess = self.session if (self.session and self.session["state"] == "ready") else None      # an interactive session already holds the GPU and ComfyUI
        self._set(jid, state="starting", started=t0, note="using the running ComfyUI session" if sess else "taking the GPU from the LLM")
        try:
            wf = load_workflows(c.workflows_dir).get(j["workflow"])
            if wf is None:
                raise VideoError("workflow %r is no longer installed" % j["workflow"])
            stages = stage_names(wf)
            if not sess:
                self._take_gpu()
                self._unload_llm()
                if c.comfy_settle_s > 0:
                    self._set(jid, note="letting the GPU settle")
                    e.sleep(c.comfy_settle_s)
                self._set(jid, note="starting the video engine")
            if stages:
                cond = self._cond_dir(jid)
                os.makedirs(cond, exist_ok=True)
                if sess:                                          # the stage hand-over needs ELZ_COND_DIR in ComfyUI's environment: restart it once, inside the session
                    self._stop_comfy()
                    self.proc = None
                self._start_comfy({"ELZ_COND_DIR": cond})
            elif not sess:
                self._start_comfy()
            if jid in self.cancel:
                raise _Cancelled()
            self._set(jid, state="running", note="loading the model and generating")
            vals = dict(j["params"])
            for name, path in (j.get("files") or {}).items():
                vals[name] = self._stage_image(path)
            if stages:
                outputs = self._run_stages(jid, wf, stages, vals, t0)
            else:
                outputs = self._run_graph(jid, fill_graph(wf["prompt"], vals))
            files = self._collect(jid, outputs)
            if not files:
                raise VideoError("finished with no output files")
            self._level_sound(jid, files)
            links = [self.share(p) for p in files] if self.share else []
            ended = time.time()
            self._sidecars(j, files, t0, ended)
            self._set(jid, state="done", ended=ended, seconds=round(ended - t0, 1), files_out=files, links=links, note="", **({"progress": 100.0} if stages else {}))
        except _Cancelled:
            self._set(jid, state="cancelled", ended=time.time(), note="")
        except Exception as ex:
            self._set(jid, state="failed", ended=time.time(), error=str(ex)[:500], note="")
        finally:
            with self.lock:
                self.cancel.discard(jid)
            if sess:                                              # the session owns ComfyUI and the GPU lease: leave both running
                with self.lock:
                    sess["last_active"] = time.time()
                self._drop_cond(jid)
                self._notify(jid)
            else:
                try:
                    self._stop_comfy()
                except Exception:
                    pass
                finally:
                    self.proc = None
                    self._drop_cond(jid)                          # the hand-over file never outlives the job, whatever happened
                    self._restore_mode()                          # the governor prewarms the LLM again
                    self._notify(jid)
        if self.cfg.drive_mode == "all":                          # the GPU is free again; the copy to Drive runs in the background and can take its time
            threading.Thread(target=self._drive_after_done, args=(jid,), name="drive-sync", daemon=True).start()

    # -- interactive ComfyUI session (the owner uses ComfyUI's own UI; queue jobs may run on it meanwhile)
    def session_info(self):
        """{"active": bool, "state": "starting"|"ready"|"stopping"|None, "idle_s": int|None, "error": str}"""
        with self.lock:
            s = self.session
            if not s:
                return {"active": False, "state": None, "idle_s": None, "error": ""}
            return {"active": True, "state": s["state"], "idle_s": int(time.time() - s["last_active"]) if s["state"] == "ready" else None, "error": s.get("error", "")}

    def session_start(self):
        """Take the GPU like a job (the LLM is unloaded), start ComfyUI and keep it up until session_stop or comfy_session_idle_min without
        activity. Returns at once; the session is "starting" until ComfyUI answers. Raises VideoBusy while a session exists or a job is active."""
        c = self.cfg
        if not c.enabled:
            raise VideoError("video generation is not set up on this PC")
        with self.lock:
            if self.session:
                raise VideoBusy("a ComfyUI session is already active")
            if any(j["state"] in ACTIVE for j in self.jobs) or os.path.exists(self.lock_path):
                raise VideoBusy("a video job is running; wait for it to finish or cancel it first")
            if self._killed():
                raise VideoError("the gateway kill switch is on")
            sess = {"state": "starting", "started": time.time(), "last_active": time.time(), "hist_n": None, "ev": threading.Event(), "seen": set(), "last_watch": 0.0}
            self.session = sess
            self._sess_thread = threading.Thread(target=self._session_main, args=(sess,), name="comfy-session", daemon=True)
        self._sess_thread.start()
        return self.session_info()

    def session_stop(self, force=False):
        """Kill ComfyUI and give the GPU back to the LLM. Raises VideoBusy while a queue job is running on the session (unless force)."""
        with self.lock:
            sess = self.session
            if sess is None:
                return {"active": False, "state": None, "idle_s": None, "error": ""}
            if not force and any(j["state"] in ACTIVE for j in self.jobs):
                raise VideoBusy("a video job is running on the session; cancel it first")
            sess["state"] = "stopping"
            sess["ev"].set()
        if self.proc is not None:
            self.env.kill_tree(self.proc)                          # also unblocks a start that is still waiting for ComfyUI
        t = self._sess_thread
        if t and t is not threading.current_thread():
            t.join(timeout=35)
        self._session_end(sess)
        return self.session_info()

    def _session_end(self, sess):
        with self.lock:
            if self.session is not sess:
                return
            sess["state"] = "stopping"
        try:
            self._stop_comfy()
        except Exception:
            pass
        self.proc = None
        self._restore_mode()                                       # the governor prewarms the LLM again
        with self.lock:
            if self.session is sess:
                self.session = None

    def _session_main(self, sess):
        c, e = self.cfg, self.env
        try:
            self._take_gpu()
            self._unload_llm()
            if sess["ev"].is_set():
                raise _Cancelled()
            self._start_comfy()
            if sess["ev"].is_set():
                raise _Cancelled()
        except BaseException as ex:
            if not isinstance(ex, _Cancelled):
                sess["error"] = str(ex)[:300]
                sys.stderr.write("video: ComfyUI session failed to start (%r)\n" % (ex,))
            self._session_end(sess)
            return
        with self.lock:
            if sess["ev"].is_set():
                return                                             # session_stop is finishing the clean-up
            sess["state"], sess["last_active"] = "ready", time.time()
        while not sess["ev"].wait(min(c.poll_s, 2.0)):
            try:
                with self.lock:
                    if any(j["state"] in ACTIVE for j in self.jobs):          # a queue job is using ComfyUI (it may restart it between stages)
                        sess["last_active"] = time.time()
                        continue
                if self.proc is None or self.proc.poll() is not None:
                    sess["error"] = "ComfyUI exited"
                    break
                if self._session_activity(sess):
                    with self.lock:
                        sess["last_active"] = time.time()
                if time.time() - sess["last_watch"] >= c.session_watch_s:
                    sess["last_watch"] = time.time()
                    self._watch_outputs(sess)
                with self.lock:
                    idle = time.time() - sess["last_active"]
                if idle >= c.session_idle_s:
                    break
            except Exception as ex:
                sys.stderr.write("video: session watcher error: %r\n" % (ex,))
        if not sess["ev"].is_set():
            self._session_end(sess)

    def _session_activity(self, sess):
        """True when a prompt is running or pending in ComfyUI, history grew, or a queue job is active. Unknown counts as quiet."""
        if any(j["state"] in ACTIVE for j in self.jobs):
            return True
        c, e = self.cfg, self.env
        busy = False
        try:
            q = e.http("GET", c.comfy_url + "/queue", timeout=3) or {}
            busy = bool(q.get("queue_running") or q.get("queue_pending"))
        except Exception:
            pass
        try:
            h = e.http("GET", c.comfy_url + "/history", timeout=5)
            if isinstance(h, dict):
                n = len(h)
                if sess["hist_n"] is not None and n != sess["hist_n"]:
                    busy = True
                sess["hist_n"] = n
        except Exception:
            pass
        return busy

    # -- renders made in ComfyUI's own UI (CueForge) during a session get the same after-care as queue jobs
    VIDEO_EXT = (".mp4", ".webm", ".mov", ".mkv")

    def _watch_outputs(self, sess):
        """Look at ComfyUI's /history; every finished prompt that is not ours and not seen yet and has video output is ingested on its own thread
        (copied into the outputs folder, levelled, sidecar written, copied to Drive). Idempotent: each prompt id is handled once. Never raises."""
        try:
            h = self.env.http("GET", self.cfg.comfy_url + "/history?max_items=64", timeout=5)
        except Exception:
            return
        if not isinstance(h, dict):
            return
        for pid, ent in h.items():
            with self.lock:
                if pid in sess["seen"] or pid in self.own_pids or not isinstance(ent, dict):
                    continue
                if any(x.get("comfy_pid") == pid for x in self.jobs):
                    sess["seen"].add(pid)
                    continue
                sess["seen"].add(pid)
                sess["last_active"] = time.time()
            outs = {}
            for node, o in (ent.get("outputs") or {}).items():
                vids = [f for key in MEDIA_KEYS for f in ((o or {}).get(key) or [])
                        if isinstance(f, dict) and f.get("filename") and f.get("type") != "temp" and os.path.splitext(str(f["filename"]))[1].lower() in self.VIDEO_EXT]
                if vids:
                    outs[node] = {"videos": vids}
            if outs and (ent.get("status") or {}).get("status_str") != "error":
                threading.Thread(target=self._ingest, args=(pid, ent, outs), name="comfy-ingest", daemon=True).start()

    def _ingest(self, pid, ent, outs):
        try:
            jid = secrets.token_hex(4)
            graph = ent.get("prompt")[2] if isinstance(ent.get("prompt"), (list, tuple)) and len(ent["prompt"]) > 2 and isinstance(ent["prompt"][2], dict) else {}
            text, seed = "", None
            for n in graph.values():
                ins = (n or {}).get("inputs") or {} if isinstance(n, dict) else {}
                if not text and isinstance(ins.get("text"), str) and ins["text"].strip():
                    text = ins["text"].strip()
                for k in ("noise_seed", "seed"):
                    if seed is None and isinstance(ins.get(k), int) and not isinstance(ins.get(k), bool):
                        seed = ins[k]
            ts = {m[0]: m[1].get("timestamp") for m in ((ent.get("status") or {}).get("messages") or []) if isinstance(m, (list, tuple)) and len(m) == 2 and isinstance(m[1], dict)}
            now = time.time()
            t1 = ts.get("execution_success") or ts.get("execution_error")
            t0 = (ts.get("execution_start") or 0) / 1000.0 or now
            t1 = t1 / 1000.0 if isinstance(t1, (int, float)) else now
            files = self._collect(jid, outs)
            if not files:
                return
            params = {"prompt": text[:1500]}
            if seed is not None:
                params["seed"] = seed
            j = dict(id=jid, workflow="comfyui", params=params, files={}, state="done", created=t0, started=t0, ended=t1, seconds=round(max(0.0, t1 - t0), 1),
                     files_out=files, links=[], note="", source="comfy", comfy_pid=pid)
            with self.lock:
                self.jobs.append(j)
                self._save()
            self._level_sound(jid, files)
            self._set(jid, note="", links=[self.share(p) for p in files] if self.share else [])
            self._sidecars(j, files, t0, t1, extra={"graph": graph, "source": "comfy", "comfy_prompt_id": pid})
            if self.cfg.drive_mode == "all":
                self.drive_sync(jid)
        except Exception as ex:
            sys.stderr.write("video: could not ingest ComfyUI output %s (%r)\n" % (pid, ex))

    # -- sound levelling (optional: needs "ffmpeg" in the video config)
    def _level_sound(self, jid, files):
        """ffmpeg loudnorm to -16 LUFS / -1.5 dBTP on each mp4, video stream copied untouched. The result replaces the clip atomically; the original
        is kept as <name>_raw.mp4 only with keep_raw. Single pass. Any failure leaves the clip as ffmpeg-free rendering made it; never raises."""
        c = self.cfg
        if not (c.loudnorm and c.ffmpeg):
            return
        for p in files:
            if os.path.splitext(p)[1].lower() != ".mp4":
                continue
            tmp = os.path.splitext(p)[0] + ".tmp.mp4"
            self._set(jid, loudnorm=False)
            try:
                self._set(jid, note="levelling the sound")
                cmd = [c.ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", p, "-c:v", "copy",
                       "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", tmp]
                code, err = self.env.run_cmd(cmd, timeout=120)
                if code != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
                    raise VideoError("ffmpeg exit %s: %s" % (code, err.strip()[-200:]))
                if c.keep_raw:
                    raw = os.path.splitext(p)[0] + "_raw.mp4"
                    shutil.copyfile(p, raw + ".tmp")
                    os.replace(raw + ".tmp", raw)
                os.replace(tmp, p)
                self._set(jid, loudnorm=True)
            except Exception as ex:
                sys.stderr.write("video: sound levelling skipped for %s (%r)\n" % (os.path.basename(p), ex))
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    # -- Google Drive copy (a synced folder; optional)
    def _drive_after_done(self, jid):
        j = self.get(jid)
        if j and j["state"] == "done" and self.cfg.drive_mode == "all":
            self.drive_sync(jid)

    def drive_sync(self, jid):
        """Copy a done job's clips and one JSON sidecar each into drive_dir/YYYY-MM/, atomically (name.tmp then os.replace). Safe to call twice: files
        already there with the same size are left alone. Records drive_path on the job. Never raises; returns True when everything is in place."""
        c = self.cfg
        try:
            j = self.get(jid)
            if not c.drive_dir or c.drive_mode == "off" or not j or j["state"] != "done" or not j.get("files_out"):
                return False
            if c.drive_mode == "favourites" and not j.get("fav"):
                return False
            month = time.strftime("%Y-%m", time.localtime(j.get("ended") or j["created"]))
            dest = os.path.join(c.drive_dir, month)
            os.makedirs(dest, exist_ok=True)
            first = None
            for p in j["files_out"]:
                if not os.path.isfile(p):
                    continue
                name = "%s_%s" % (jid, os.path.basename(p))
                target = os.path.join(dest, name)
                if not (os.path.isfile(target) and os.path.getsize(target) == os.path.getsize(p)):
                    shutil.copyfile(p, target + ".tmp")
                    os.replace(target + ".tmp", target)
                side = {"job_id": jid, "clip": name, "workflow": j["workflow"], "prompt": (j.get("params") or {}).get("prompt"), "params": j.get("params"),
                        "seed": (j.get("params") or {}).get("seed"), "fav": bool(j.get("fav")), "created": j["created"], "started": j.get("started"), "ended": j.get("ended"),
                        "render_s": j.get("seconds"), "queued_s": round(j["started"] - j["created"], 1) if j.get("started") else None}
                try:                                                  # the full ComfyUI graph of a CueForge render lives in the clip's own sidecar
                    with open(p + ".json", encoding="utf-8") as sf:
                        g = json.load(sf).get("graph")
                    if g:
                        side["workflow_graph"] = g
                except (OSError, ValueError, AttributeError):
                    pass
                with open(target + ".json.tmp", "w", encoding="utf-8") as f:
                    json.dump(side, f, indent=1)
                os.replace(target + ".json.tmp", target + ".json")
                first = first or target
            if not first:
                raise VideoError("no clip file to copy")
            self._set(jid, drive_path=first, drive_rel=month + "/" + os.path.basename(first), drive_error="")
            return True
        except Exception as ex:
            sys.stderr.write("video: Drive copy failed for %s (%r)\n" % (jid, ex))
            try:
                self._set(jid, drive_error=str(ex)[:200])
            except Exception:
                pass
            return False

    def _stop_comfy(self):
        e = self.env
        if self.proc is not None and self.proc.poll() is None:
            try:                                                  # ask ComfyUI to drop its models first; the kill below is still what guarantees the VRAM
                e.http("POST", self.cfg.comfy_url + "/free", {"unload_models": True, "free_memory": True}, timeout=5)
            except Exception:
                pass
        e.kill_tree(self.proc)

    def _run_graph(self, jid, graph, span=None, expect_s=None, deadline=None):
        """Submit one filled graph and wait for it. Returns the history outputs."""
        c, e = self.cfg, self.env
        r = e.http("POST", c.comfy_url + "/prompt", {"prompt": graph, "client_id": "gw-" + jid}, timeout=30)
        if r.get("node_errors"):
            raise VideoError("ComfyUI rejected the workflow: %s" % json.dumps(r["node_errors"])[:400])
        pid = r.get("prompt_id")
        if not pid:
            raise VideoError("ComfyUI did not accept the job: %s" % json.dumps(r)[:300])
        with self.lock:
            self.own_pids.add(pid)
        return self._wait(jid, pid, span, expect_s, deadline)

    # -- two-process split
    def _cond_dir(self, jid):
        return os.path.join(self.cond_root, jid)

    def _drop_cond(self, jid):
        if re.match(r"^[0-9a-f]{8}$", jid or ""):
            shutil.rmtree(self._cond_dir(jid), ignore_errors=True)

    def _run_stages(self, jid, wf, stages, vals, t0):
        """Run the stage graphs in order inside the one GPU lease. ComfyUI is killed and started again between stages. A failed or cancelled stage
        raises, so the remaining stages never start (run()'s cleanup kills the current process and deletes the conditioning folder)."""
        c = self.cfg
        n = len(stages)
        graphs = [load_stage(c.workflows_dir, s) for s in stages]            # all stages present and valid before any process is started again
        weights = stage_weights(wf["meta"], n)
        total_s = est_minutes(wf) * 60.0
        deadline = t0 + c.job_timeout_s                                       # one budget for the whole job, not one per stage
        cond = self._cond_dir(jid)
        lo, outputs = 0.0, {}
        for i, sw in enumerate(graphs):
            hi = lo + weights[i]
            label = str(sw["meta"].get("label") or stages[i])[:60]
            if i:
                self._set(jid, note="stage %d of %d: freeing memory, restarting the video engine" % (i + 1, n), progress=round(lo, 1))
                self._stop_comfy()
                self.proc = None
                if jid in self.cancel or self._stop.is_set() or self._killed():
                    raise _Cancelled()
                self._start_comfy({"ELZ_COND_DIR": cond})
                if jid in self.cancel:
                    raise _Cancelled()
            self._set(jid, note="stage %d of %d: %s" % (i + 1, n, label), progress=round(lo, 1))
            outputs = self._run_graph(jid, fill_graph(sw["prompt"], vals), (lo, hi), max(1.0, total_s * weights[i] / 100.0), deadline)
            if i < n - 1 and not (os.path.isfile(os.path.join(cond, "cond.safetensors")) and os.path.isfile(os.path.join(cond, "cond.json"))):
                raise VideoError("stage %d (%s) finished without writing the conditioning file; stage %d was not started" % (i + 1, stages[i], i + 2))
            lo = hi
            self._set(jid, progress=round(lo, 1))
        return outputs

    # -- push notification
    def _notify(self, jid):
        """ntfy push when a job ends done or failed. Off unless ntfy_url and ntfy_topic are set; 5 s timeout; never raises, never changes the job.
        The text holds no prompt (and no error text, which can echo inputs) unless ntfy_include_prompt is on."""
        c = self.cfg
        if not (c.ntfy_url and c.ntfy_topic):
            return
        try:
            j = self.get(jid)
            if not j or j["state"] not in ("done", "failed"):
                return
            clean = lambda x, n=120: re.sub(r"[\x00-\x1f\x7f]+", " ", str(x)).encode("ascii", "replace").decode()[:n]      # header values must be latin-1 safe, single line
            ok = j["state"] == "done"
            took = int((j.get("ended") or time.time()) - (j.get("started") or j["created"]))
            body = ("Clip ready: %d file(s)" % len(j.get("files_out") or []) if ok else "The render failed; open Studio for the reason") + " (job %s, %dm %02ds)." % (j["id"], took // 60, took % 60)
            if c.ntfy_include_prompt and (j.get("params") or {}).get("prompt"):
                body += "\nPrompt: " + re.sub(r"\s+", " ", str(j["params"]["prompt"]))[:300]
            h = {"Title": clean("Video %s: %s" % ("ready" if ok else "failed", j.get("workflow", ""))), "Tags": "movie_camera" if ok else "warning",
                 "Priority": "default" if ok else "high", "Content-Type": "text/plain; charset=utf-8"}
            if c.ntfy_click_base.lower().startswith(("http://", "https://")):
                h["X-Click"] = clean(c.ntfy_click_base.rstrip("/") + "/approvals/studio#job=" + j["id"], 300)
            self.env.http("POST", c.ntfy_url.rstrip("/") + "/" + urllib.parse.quote(c.ntfy_topic, safe=""), body, headers=h, timeout=5)
        except Exception as ex:
            sys.stderr.write("video: ntfy failed (%r)\n" % (ex,))

    def _unload_llm(self):
        c, e = self.cfg, self.env
        h = {"Authorization": "Bearer " + c.api_key()} if c.api_key() else {}
        names = []
        try:                                                      # unload whatever is loaded (the governor may be running a variant, not model_id)
            names = [m.get("model") for m in ((e.http("GET", c.swap_url + "/running", headers=h, timeout=5) or {}).get("running") or []) if m.get("model")]
        except Exception:
            pass
        for name in names or ([c.model_id] if c.model_id else []):
            try:
                e.http("POST", "%s/api/models/unload/%s" % (c.swap_url, name), {}, headers=h, timeout=60)
            except Exception:
                pass
        end = time.time() + c.unload_timeout_s
        while time.time() < end:
            try:
                if not (e.http("GET", c.swap_url + "/running", headers=h, timeout=5) or {}).get("running") and not e.process_running(c.llm_process):
                    return
            except Exception:
                if not e.process_running(c.llm_process):
                    return
            time.sleep(min(1.0, c.poll_s))
        raise VideoError("the LLM did not unload within %d s; the GPU was not taken" % c.unload_timeout_s)

    def _start_comfy(self, extra_env=None):
        c, e = self.cfg, self.env
        try:
            up = bool(e.http("GET", c.comfy_url + "/system_stats", timeout=3))
        except Exception:
            up = False
        if up:
            raise VideoError("another ComfyUI is already running on %s" % c.comfy_url)
        env = dict(c.comfy_env, **extra_env) if extra_env else c.comfy_env
        log_size = lambda: os.path.getsize(self.log_path) if os.path.exists(self.log_path) else 0

        def spawn():
            self.proc = e.popen(c.comfy_cmd, c.comfy_dir, env, self.log_path)
            try:
                self._lock_set(pid=self.proc.pid)
            except OSError:
                pass
            return time.time(), log_size()

        end = time.time() + c.start_timeout_s                     # one deadline, measured from the first spawn
        t_spawn, size0 = spawn()
        respawned, checked = False, False                         # checked: this spawn has shown life in its log, so it is only slow
        stalled = lambda: "ComfyUI stalled at start-up twice (no output); see %s" % self.log_path
        while time.time() < end:
            if self.proc.poll() is not None:
                raise VideoError("ComfyUI exited during start-up (see %s)" % self.log_path)
            try:
                if e.http("GET", c.comfy_url + "/system_stats", timeout=3):
                    return
            except Exception:
                pass
            if not checked and time.time() - t_spawn >= c.comfy_stall_s:
                if log_size() > size0:
                    checked = True
                elif respawned:
                    e.kill_tree(self.proc)
                    raise VideoError(stalled())
                else:
                    e.kill_tree(self.proc)
                    try:
                        with open(self.log_path, "ab") as f:
                            f.write(("[gateway] ComfyUI produced no output in %d s; restarting once\n" % c.comfy_stall_s).encode())
                    except OSError:
                        pass
                    respawned = True
                    t_spawn, size0 = spawn()
                    continue
            time.sleep(min(1.0, c.poll_s))
        if not checked and log_size() <= size0 and respawned:
            raise VideoError(stalled())
        raise VideoError("ComfyUI did not answer within %d s" % c.start_timeout_s)

    def _stage_image(self, path):
        if not self.cfg.input_dir:
            raise VideoError("input_dir is not configured")
        os.makedirs(self.cfg.input_dir, exist_ok=True)
        name = "gw_%s%s" % (secrets.token_hex(4), os.path.splitext(path)[1].lower())
        import shutil
        shutil.copyfile(path, os.path.join(self.cfg.input_dir, name))
        return name

    def _wait(self, jid, pid, span=None, expect_s=None, deadline=None):
        """Poll until the prompt is in /history. span=(lo, hi) and expect_s (staged jobs only) move the job's progress from lo towards hi
        by elapsed/expected time, never past 95 % of the span until the stage really ends; deadline replaces the per-wait timeout."""
        c, e = self.cfg, self.env
        t_in = time.time()
        end = deadline if deadline is not None else t_in + c.job_timeout_s
        shown = span[0] if span else 0
        while time.time() < end:
            if span:
                p = span[0] + (span[1] - span[0]) * min(0.95, (time.time() - t_in) / expect_s)
                if p - shown >= 1:
                    shown = p
                    self._set(jid, progress=round(p, 1))
            if jid in self.cancel or self._stop.is_set() or self._killed():
                try:
                    e.http("POST", c.comfy_url + "/interrupt", {}, timeout=10)
                except Exception:
                    pass
                raise _Cancelled()
            if self.proc is not None and self.proc.poll() is not None:
                raise VideoError("ComfyUI crashed during the job (see %s)" % self.log_path)
            try:
                h = e.http("GET", "%s/history/%s" % (c.comfy_url, pid), timeout=10) or {}
            except Exception:
                h = {}
            if pid in h:
                st = h[pid].get("status") or {}
                if st.get("status_str") == "error":
                    msgs = [m for m in st.get("messages", []) if m and m[0] == "execution_error"]
                    raise VideoError("ComfyUI error: %s" % (json.dumps(msgs[-1][1])[:400] if msgs else "execution failed"))
                if h[pid].get("outputs"):
                    return h[pid]["outputs"]
                if st.get("status_str") == "success" or st.get("completed"):
                    return {}                                     # finished with nothing to collect
            time.sleep(c.poll_s)
        try:
            e.http("POST", c.comfy_url + "/interrupt", {}, timeout=10)
        except Exception:
            pass
        raise VideoError("the job exceeded %d s and was stopped" % c.job_timeout_s)

    def _collect(self, jid, outputs):
        c, e = self.cfg, self.env
        dest = os.path.join(self.out_dir, jid)
        os.makedirs(dest, exist_ok=True)
        got = []
        for node in outputs.values():
            for key in MEDIA_KEYS:
                for f in node.get(key) or []:
                    if not isinstance(f, dict) or not f.get("filename") or f.get("type") == "temp":
                        continue
                    q = "filename=%s&subfolder=%s&type=%s" % (urllib.request.quote(f["filename"]), urllib.request.quote(f.get("subfolder", "")), f.get("type", "output"))
                    p = os.path.join(dest, os.path.basename(f["filename"]))
                    data = e.fetch("%s/view?%s" % (c.comfy_url, q))
                    open(p, "wb").write(data)
                    got.append(p)
        return got


class _Cancelled(Exception):
    pass


def m_state_loading(running):
    return any(str(m.get("state", "ready")) not in ("ready", "stopped") for m in running)


def est_minutes(wf):
    """Typical minutes from a workflow's meta ("5", "5-10"): the largest number in it, else 5."""
    n = re.findall(r"\d+(?:\.\d+)?", str(((wf or {}).get("meta") or {}).get("est_minutes", "")))
    return max(map(float, n)) if n else 5.0


def est_minutes_num(v):
    """est_minutes as a number for the UI, or "" when it is not one."""
    try:
        f = float(v)
        return f if math.isfinite(f) else ""
    except (TypeError, ValueError):
        return ""


def brief(j):
    """Compact job summary for the model (small, no secrets)."""
    d = {"id": j["id"], "state": j["state"], "workflow": j["workflow"]}
    for k in ("note", "error", "seconds"):
        if j.get(k):
            d[k] = j[k]
    if j.get("links"):
        d["links"] = j["links"]
    if j.get("state") == "queued":
        d["waiting_since_s"] = int(time.time() - j["created"])
    return d


def register(server, cfg, state_dir, base_dir, kill=None, share_fn=None):
    """Add the video tools when the config has a "video" block (opt-in). Returns the Queue, or None."""
    if "video" not in cfg:
        return None
    vc = Cfg(cfg.get("video"), base_dir)
    q = Queue(vc, state_dir, kill, share=share_fn)
    if vc.enabled:
        q.start()

    @server.tool(name="video_workflows", description="List the video workflows that can be generated (name, what it does, parameters, typical minutes).")
    def video_workflows() -> str:
        out = []
        for name, w in load_workflows(vc.workflows_dir).items():
            m = w["meta"]
            out.append({"name": name, "what": m.get("description", ""), "est_minutes": m.get("est_minutes", ""),
                        "params": {k: {kk: vv for kk, vv in p.items() if kk in ("type", "required", "default", "min", "max")} for k, p in (m.get("params") or {}).items()}})
        return json.dumps(out or "no workflows installed", separators=(",", ":"))

    @server.tool(name="video_generate", description=(
        "Queue a video render and return at once with {job_id, position, est_minutes}. Needs the owner's approval. Never wait on it: "
        "poll video_status(job_id), then call video_result(job_id). Takes minutes; the LLM is paused while it renders. "
        "prompt = what to film; workflow = a name from video_workflows; seconds = clip length; image = file path for image-to-video."))
    def video_generate(prompt: str, workflow: str = "", seconds: float = 0, width: int = 0, height: int = 0, seed: int = -1, image: str = "", negative: str = "") -> str:
        if not vc.enabled:
            return "Video generation is not set up on this PC (no ComfyUI configured)."
        raw = {"prompt": prompt, "seconds": seconds, "width": width, "height": height, "seed": seed, "image": image, "negative": negative}
        wf = workflow or next(iter(sorted(load_workflows(vc.workflows_dir))), "")
        try:
            jid, pos, est = q.submit(wf, raw)
        except VideoError as e:
            return "Not queued: %s" % e
        return json.dumps({"job_id": jid, "workflow": wf, "position": pos, "est_minutes": est}, separators=(",", ":"))

    @server.tool(name="video_status", description="State of a video job: state, note, elapsed_s, queue_position, eta_min, and clips once done. Cheap; poll every 30-60 s. Empty job_id lists the 5 latest jobs.")
    def video_status(job_id: str = "") -> str:
        if job_id:
            d = q.status(job_id)
            return json.dumps(d, separators=(",", ":")) if d else "no such job"
        return json.dumps([brief(j) for j in q.recent(5)], separators=(",", ":"))

    @server.tool(name="video_result", description="Outcome of a finished video job: clip names, share links to give the user, and meta (workflow, params, seed, seconds, wall_s). Failed jobs return the error; unfinished jobs just their state.")
    def video_result(job_id: str) -> str:
        d = q.result(job_id)
        return json.dumps(d, separators=(",", ":")) if d else "no such job"

    @server.tool(name="video_queue", description="Read-only list of the 10 most recent video jobs (id, state, workflow, note/error, seconds, links).")
    def video_queue() -> str:
        return json.dumps([brief(j) for j in q.recent(10)], separators=(",", ":"))

    @server.tool(name="video_cancel", description="Cancel a queued or running video job.")
    def video_cancel(job_id: str) -> str:
        return q.cancel_job(job_id)

    return q
