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

Everything outside this file (llama-swap, ComfyUI, process control) is reached through small functions on `Env`, so the tests run the
whole lifecycle against mock servers.
"""
import copy, json, math, os, random, re, secrets, subprocess, sys, threading, time, urllib.error, urllib.request

STATES = ("queued", "waiting", "starting", "running", "done", "failed", "cancelled")
ACTIVE = ("waiting", "starting", "running")
PH = re.compile(r"\{\{(\w+)\}\}")
FULL_PH = re.compile(r"^\{\{(\w+)\}\}$")
MEDIA_KEYS = ("videos", "gifs", "images", "audio")


class VideoError(Exception):
    pass


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
        req = urllib.request.Request(url, data=(json.dumps(body).encode() if body is not None else None), headers=h, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            t = r.read()
        try:
            return json.loads(t) if t.strip()[:1] in (b"{", b"[") else {}
        except ValueError:
            return {}

    def popen(self, cmd, cwd, env, log_path):
        e = dict(os.environ)
        e.update(env)
        return subprocess.Popen(cmd, cwd=cwd, env=e, stdout=open(log_path, "ab"), stderr=subprocess.STDOUT)

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
        self.lock = threading.RLock()
        self.cancel = set()
        self.proc = None
        self.last_busy = time.time()
        self.jobs = self._load()
        self._stop = threading.Event()
        self.thread = None
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
                prev = "MAX"
            self._lock_set(mode=prev)
        open(self.cfg.mode_file, "w").write("OFF\n")

    def _restore_mode(self):
        d = self._lock_read()
        if d is None:
            return
        try:
            if self.cfg.mode_file and d.get("mode"):
                open(self.cfg.mode_file, "w").write(str(d["mode"]) + "\n")
            os.remove(self.lock_path)
        except OSError:
            pass

    # -- public API
    def submit(self, workflow, raw, files_ok=True):
        wfs = load_workflows(self.cfg.workflows_dir)
        if workflow not in wfs:
            raise VideoError("unknown workflow %r. Available: %s" % (workflow, ", ".join(sorted(wfs)) or "(none installed)"))
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

    def _sidecars(self, j, files, t0, ended):
        """Write <clip>.json (seed, workflow, params, timings) next to each clip. Once, when the job completes; never fails the job."""
        meta = {"job_id": j["id"], "workflow": j["workflow"], "params": j["params"], "seed": j["params"].get("seed"), "fav": bool((self.get(j["id"]) or j).get("fav")),
                "created": j["created"], "started": t0, "ended": ended, "queued_s": round(t0 - j["created"], 1), "render_s": round(ended - t0, 1)}
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
            if self._killed():
                nxt["state"], nxt["error"], nxt["ended"] = "failed", "KILLED: the gateway kill switch is on", time.time()
                self._save()
                return
            if nxt["id"] in self.cancel:
                self.cancel.discard(nxt["id"])
                nxt["state"], nxt["ended"], nxt["note"] = "cancelled", time.time(), ""
                self._save()
                return
            nxt["state"] = "waiting"
            nxt["note"] = "waiting for the LLM to be quiet for %d s" % self.cfg.quiet_s
            self._save()
        if not self.llm_quiet():
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
        self._set(jid, state="starting", started=t0, note="taking the GPU from the LLM")
        try:
            self._take_gpu()
            self._unload_llm()
            self._set(jid, note="starting the video engine")
            self._start_comfy()
            if jid in self.cancel:
                raise _Cancelled()
            self._set(jid, state="running", note="loading the model and generating")
            wf = load_workflows(c.workflows_dir)[j["workflow"]]
            vals = dict(j["params"])
            for name, path in (j.get("files") or {}).items():
                vals[name] = self._stage_image(path)
            graph = fill_graph(wf["prompt"], vals)
            r = e.http("POST", c.comfy_url + "/prompt", {"prompt": graph, "client_id": "gw-" + jid}, timeout=30)
            if r.get("node_errors"):
                raise VideoError("ComfyUI rejected the workflow: %s" % json.dumps(r["node_errors"])[:400])
            pid = r.get("prompt_id")
            if not pid:
                raise VideoError("ComfyUI did not accept the job: %s" % json.dumps(r)[:300])
            outputs = self._wait(jid, pid)
            files = self._collect(jid, outputs)
            if not files:
                raise VideoError("finished with no output files")
            links = [self.share(p) for p in files] if self.share else []
            ended = time.time()
            self._sidecars(j, files, t0, ended)
            self._set(jid, state="done", ended=ended, seconds=round(ended - t0, 1), files_out=files, links=links, note="")
        except _Cancelled:
            self._set(jid, state="cancelled", ended=time.time(), note="")
        except Exception as ex:
            self._set(jid, state="failed", ended=time.time(), error=str(ex)[:500], note="")
        finally:
            with self.lock:
                self.cancel.discard(jid)
            try:
                if self.proc is not None and self.proc.poll() is None:
                    try:                                          # ask ComfyUI to drop its models first; the kill below is still what guarantees the VRAM
                        e.http("POST", self.cfg.comfy_url + "/free", {"unload_models": True, "free_memory": True}, timeout=5)
                    except Exception:
                        pass
                e.kill_tree(self.proc)
            except Exception:
                pass
            finally:
                self.proc = None
                self._restore_mode()                              # the governor prewarms the LLM again

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

    def _start_comfy(self):
        c, e = self.cfg, self.env
        try:
            up = bool(e.http("GET", c.comfy_url + "/system_stats", timeout=3))
        except Exception:
            up = False
        if up:
            raise VideoError("another ComfyUI is already running on %s" % c.comfy_url)
        self.proc = e.popen(c.comfy_cmd, c.comfy_dir, c.comfy_env, self.log_path)
        try:
            self._lock_set(pid=self.proc.pid)
        except OSError:
            pass
        end = time.time() + c.start_timeout_s
        while time.time() < end:
            if self.proc.poll() is not None:
                raise VideoError("ComfyUI exited during start-up (see %s)" % self.log_path)
            try:
                if e.http("GET", c.comfy_url + "/system_stats", timeout=3):
                    return
            except Exception:
                pass
            time.sleep(min(1.0, c.poll_s))
        raise VideoError("ComfyUI did not answer within %d s" % c.start_timeout_s)

    def _stage_image(self, path):
        if not self.cfg.input_dir:
            raise VideoError("input_dir is not configured")
        os.makedirs(self.cfg.input_dir, exist_ok=True)
        name = "gw_%s%s" % (secrets.token_hex(4), os.path.splitext(path)[1].lower())
        import shutil
        shutil.copyfile(path, os.path.join(self.cfg.input_dir, name))
        return name

    def _wait(self, jid, pid):
        c, e = self.cfg, self.env
        end = time.time() + c.job_timeout_s
        while time.time() < end:
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
