"""Studio: the browser front end for local video generation (phone and desktop, over the tailnet).

It adds routes under /approvals/studio/ to the existing approvals server, so it inherits that server's PIN login, session cookie, CSRF header,
security headers and the Tailscale publishing already done by tts_server (it appears at /tts/approvals/studio/ on the tailnet).

  GET  /approvals/studio                       the single-file app (public: it holds no data; the API below needs the PIN session)
  GET  /approvals/studio/manifest.webmanifest, icon-180.png, icon-192.png, icon-512.png   the home-screen app files (public and static: no job data)
  GET  /approvals/studio/api/workflows         the workflows and their controls
  GET  /approvals/studio/api/jobs              recent jobs (newest first) with clip links
  GET  /approvals/studio/api/status            who has the GPU, queue length
  GET  /approvals/studio/api/clip/<id>/<name>  stream a finished clip (Range supported)
  POST /approvals/studio/api/generate          {"workflow", "params"} -> queue a job
  POST /approvals/studio/api/cancel            {"id"}
  POST /approvals/studio/api/delete            {"id"}
  POST /approvals/studio/api/fav               {"id", "fav": true|false} -> star a job; starred jobs (and their start images) are never trimmed
  POST /approvals/studio/api/rerun             {"id"} -> queue a new job from an earlier job's settings (same seed), validated again like any new job
  GET  /approvals/studio/api/system            GPU mode, queue, current stage, last speed, host RAM, disk free, VRAM when cheap (cached 2 s, fails soft)
  POST /approvals/studio/api/comfy             {"action": "start"|"stop"} -> interactive ComfyUI session (GPU lease, auto-stops when idle); start refused (409) while a job runs
  POST /approvals/studio/api/mode              {"mode": "video"|"llm"} -> hand the GPU to video or back to Qwen; refused (409) while a job is queued or running
  POST /approvals/studio/api/upload            raw image body (header X-Filename) -> {"name"}
  POST /approvals/studio/api/assist            {"idea", "workflow", "mode"} -> a prompt written by Qwen. mode: "single" (default), "multi" (2-4 shots
                                               with named cuts) or "continue" (only what happens next, from the start image); unknown -> "single"

Nothing here takes a file path from the browser: images are referred to by the name the upload returned, clips by job id + file name, and both
are checked against the folders this module owns.
"""
import ctypes, json, os, re, secrets, shutil, time

import video

MAX_UPLOAD = 25 * 2 ** 20
CLIP_TYPES = {".mp4": "video/mp4", ".webm": "video/webm", ".webp": "image/webp", ".gif": "image/gif", ".png": "image/png", ".jpg": "image/jpeg",
              ".jpeg": "image/jpeg", ".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac", ".m4a": "audio/mp4"}
NAME_OK = re.compile(r"^[\w][\w .()+-]{0,150}$")
UP_OK = re.compile(r"^up_[0-9a-f]{12}\.(png|jpg|webp)$")
UI_KEYS = ("type", "label", "help", "required", "default", "min", "max", "step", "multiple_of", "rows", "max_len", "choices")

PWA_FILES = {"manifest.webmanifest": "application/manifest+json", "icon-180.png": "image/png", "icon-192.png": "image/png", "icon-512.png": "image/png"}
JOB_ID = re.compile(r"^[0-9a-f]{8}$")

ASSIST_MODES = ("single", "multi", "continue")
ASSIST_SYSTEM = (
    "You write prompts for LTX, a text-to-video model, following Lightricks' prompting guide. Turn the user's idea into ONE flowing paragraph, "
    "present tense, in chronological order, as a single block of prose (no lists, no headings, no numbering, no bullet points). "
    "Open directly with the shot type and framing, then establish the scene and place, then describe the action as a sequence from start to end. "
    "Cover, in whatever order reads naturally: shot type and lens feel; the scene, setting and time of day; the action; the characters "
    "(age, build, clothing, hair, expression, body language); camera movement and when it happens; the lighting and colour palette; and the sound. "
    "Be concrete and visual. Use positive phrasing (say what is there, not what is absent). Keep it to roughly 80 to 180 words. "
    "Avoid brand names, readable text or logos on screen, and physics too complex to render. Never add facts that contradict the user's idea. "
    "Reply with the paragraph only.")
ASSIST_AUDIO = (
    " Include the sound: ambient noise, music and effects. Put any spoken dialogue in double quotes with a short note of who says it and how "
    "(for example: a woman says warmly, \"Welcome home.\"). Add dialogue only if the user asked for speech or clearly implies it.")
ASSIST_SILENT = " This workflow makes no audio, so do not describe sound or dialogue."
ASSIST_MULTI = (
    " MULTI-SHOT: write 2 to 4 shots inside the one paragraph, in order, joined by named cuts in prose such as 'Cut to a close-up of...', "
    "'The scene cuts to a wide shot of...' or 'Match cut to...'. Give each shot its own framing and camera move. After every cut, "
    "re-identify each subject in full (who they are and what they wear) instead of saying 'she' or 'the same man', because the model does not "
    "remember earlier shots. Keep lighting and palette consistent across the cuts unless the idea says otherwise. Do not number the shots.")
ASSIST_CONTINUE = (
    " CONTINUE: the user already has a start image, which is the first frame of the clip and shows who and what is in it. Do not re-describe "
    "what the image already shows beyond a few words to anchor the subject. Describe only what happens next: the motion, the action, any camera "
    "move, and the sound, starting from that frame.")


def assist_system(mode, audio=True):
    s = ASSIST_SYSTEM
    if mode == "multi": s += ASSIST_MULTI
    elif mode == "continue": s += ASSIST_CONTINUE
    return s + (ASSIST_AUDIO if audio else ASSIST_SILENT)


def assist_mode(v):
    return v if isinstance(v, str) and v in ASSIST_MODES else "single"


def _j(code, obj):
    return code, json.dumps(obj, separators=(",", ":")), "application/json"


def _public_job(j):
    d = {"id": j["id"], "workflow": j.get("workflow"), "state": j.get("state"), "note": j.get("note", ""), "created": j.get("created"),
         "started": j.get("started"), "ended": j.get("ended"), "seconds": j.get("seconds"), "error": j.get("error", ""),
         "params": {k: v for k, v in (j.get("params") or {}).items()}, "has_image": bool(j.get("files")), "fav": bool(j.get("fav"))}
    if isinstance(j.get("progress"), (int, float)) and not isinstance(j.get("progress"), bool): d["progress"] = max(0.0, min(100.0, float(j["progress"])))   # staged workflows report a real percentage
    if isinstance(j.get("step"), str) and re.match(r"^\d{1,4}/\d{1,4}$", j["step"]): d["step"] = j["step"]                      # live sampler step, e.g. "3/8"
    if isinstance(j.get("eta_s"), (int, float)) and not isinstance(j.get("eta_s"), bool) and 0 <= j["eta_s"] < 86400: d["eta_s"] = round(float(j["eta_s"]), 1)
    if isinstance(j.get("phase"), str) and re.match(r"^[a-z0-9_]{1,16}$", j["phase"]): d["phase"] = j["phase"]
    if j.get("drive_rel"): d["drive"] = j["drive_rel"]                 # "2026-10/<job>_<clip>.mp4": a path inside the Drive folder, never the folder itself
    if j.get("drive_error"): d["drive_error"] = str(j["drive_error"])[:120]
    d["clips"] = [{"name": os.path.basename(p), "type": CLIP_TYPES.get(os.path.splitext(p)[1].lower(), "application/octet-stream")}
                  for p in (j.get("files_out") or [])]
    return d


def _scalar(v, n=500):
    if isinstance(v, bool) or v is None: return v
    if isinstance(v, (int, float)): return v
    return str(v)[:n]


def clean_presets(raw, allowed):
    """Presets as the browser gets them: [{"name", "label", "hint"?, "params": {...}}]. params may hold any workflow param name (never prompt, image or
    seed) plus "size" (an index into sizes, a size label such as "Draft", "WxH", or [w, h]), "seconds" and "workflow" (jump to another workflow).
    Anything else is dropped, so a typo in a workflow file cannot reach the browser as markup or as an unknown field."""
    out = []
    ok = set(allowed) | {"size", "seconds", "workflow"}
    for p in (raw if isinstance(raw, list) else [])[:8]:
        if not isinstance(p, dict) or not isinstance(p.get("params"), dict): continue
        label = str(p.get("label") or p.get("name") or "").strip()[:24]
        if not label: continue
        params = {}
        for k, v in p["params"].items():
            if k in ("prompt", "image", "seed", "frames") or not (k in ok and isinstance(k, str)): continue
            if isinstance(v, (list, tuple)): v = [_scalar(x, 40) for x in v[:2]]
            elif isinstance(v, dict): continue
            else: v = _scalar(v)
            params[k] = v
        if params:
            item = {"name": re.sub(r"[^\w-]+", "-", str(p.get("name") or label).strip().lower())[:32] or "preset", "label": label,
                    "hint": str(p.get("hint") or "")[:80], "params": params}
            if isinstance(p.get("note"), str) and p["note"].strip(): item["note"] = p["note"].strip()[:200]      # the measured-time / what-it-does line, shown under the chips
            out.append(item)
    return out


def _meta_for_ui(name, w):
    m = w.get("meta") or {}
    out = {"name": name, "title": m.get("title") or name.replace("_", " "), "description": m.get("description", ""),
           "est_minutes": video.est_minutes_num(m.get("est_minutes")), "kind": m.get("kind", ""), "fps": m.get("fps", 24), "audio": bool(m.get("audio")),
           "seconds": m.get("seconds") or None, "order": m.get("order", 100), "sizes": m.get("sizes") or [], "frames_rule": m.get("frames_rule") or "8n+1", "presets": [], "params": {}}
    er = m.get("est_ref")                                                    # [width, height, seconds] the est_minutes figure was measured at; lets the UI scale the ETA
    if isinstance(er, list) and len(er) == 3 and all(isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0 for x in er): out["est_ref"] = [float(x) for x in er]
    for k, p in (m.get("params") or {}).items():
        out["params"][k] = {kk: vv for kk, vv in p.items() if kk in UI_KEYS}
    out["presets"] = clean_presets(m.get("presets"), out["params"])
    return out


# ---------- host numbers for the System tab (all best effort: a failed probe is None, never an error) ----------
def host_ram():
    """(total, available) bytes of host RAM, or (None, None). Windows: GlobalMemoryStatusEx; elsewhere /proc/meminfo."""
    try:
        if os.name == "nt":
            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS(); m.dwLength = ctypes.sizeof(MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return int(m.ullTotalPhys), int(m.ullAvailPhys)
            return None, None
    except Exception:
        pass
    try:
        return _meminfo("/proc/meminfo")
    except Exception:
        return None, None


def _meminfo(path):
    kb = {}
    with open(path) as f:
        for line in f:
            k, _, v = line.partition(":")
            n = re.match(r"\s*(\d+)", v)
            if n: kb[k] = int(n.group(1)) * 1024
    if "MemTotal" not in kb: return None, None
    return kb["MemTotal"], kb.get("MemAvailable", kb.get("MemFree"))


def disk_free(path):
    try:
        u = shutil.disk_usage(path)
        return {"free": u.free, "total": u.total}
    except Exception:
        return None


def _out_secs(j):
    """Seconds of film a job made: params.seconds, else (frames - 1) / fps."""
    p = j.get("params") or {}
    try:
        if p.get("seconds"): return float(p["seconds"])
        if p.get("frames"): return (float(p["frames"]) - 1) / 24.0
    except (TypeError, ValueError):
        pass
    return None


def last_speed(jobs):
    """Newest finished render: {"seconds": render wall time, "per_output_s": render seconds per second of film, "job": id}, or None."""
    for j in reversed(jobs):
        if j.get("state") == "done" and isinstance(j.get("seconds"), (int, float)) and j["seconds"] > 0:
            o = _out_secs(j)
            return {"seconds": round(float(j["seconds"]), 1), "out_seconds": round(o, 2) if o else None, "per_output_s": round(j["seconds"] / o, 1) if o else None, "job": j["id"]}
    return None


def routes(q, vc, here, env=None):
    """Build the route table for approvals.register_extra. q = video.Queue, vc = video.Cfg, here = folder holding studio/index.html."""
    env = env or q.env
    index = os.path.join(here, "studio", "index.html")
    up_dir = os.path.join(q.dir, "uploads")
    os.makedirs(up_dir, exist_ok=True)
    real_up = os.path.realpath(up_dir)
    if real_up not in vc.allowed_roots:
        vc.allowed_roots.append(real_up)                      # uploads are the only images the browser can name
    real_out = os.path.realpath(q.out_dir)
    T = "/approvals/studio"

    def need(req):
        return None if req.get("authed") else _j(401, {"error": "log in with your PIN first"})

    def shell(req):
        try:
            with open(index, "rb") as f:
                return 200, f.read(), "text/html; charset=utf-8"
        except OSError:
            return 404, "Studio files are missing (gateway/studio/index.html).", "text/plain"

    def pwa_file(name):
        """A static home-screen file from studio/. Public like the shell: it holds no data and the browser fetches it before any sign-in."""
        def serve(req):
            try:
                with open(os.path.join(here, "studio", name), "rb") as f:
                    return 200, f.read(), PWA_FILES[name]
            except OSError:
                return 404, "Studio files are missing (gateway/studio/%s)." % name, "text/plain"
        return serve

    def workflows(req):
        bad = need(req)
        if bad: return bad
        wfs = video.load_workflows(vc.workflows_dir)
        return _j(200, {"enabled": vc.enabled, "workflows": [_meta_for_ui(n, w) for n, w in sorted(wfs.items(), key=lambda kv: (kv[1]["meta"].get("order", 100), kv[0]))]})

    def jobs(req):
        bad = need(req)
        if bad: return bad
        out = q.recent(40)
        have = {j["id"] for j in out}
        return _j(200, [_public_job(j) for j in out + [f for f in q.favourites() if f["id"] not in have]])    # starred clips stay listed once newer ones push them out

    def status(req):
        bad = need(req)
        if bad: return bad
        recent = q.recent(200)
        active = [j for j in recent if j["state"] in video.ACTIVE]
        queued = [j for j in recent if j["state"] == "queued"]
        h = {"Authorization": "Bearer " + vc.api_key()} if vc.api_key() else {}
        llm = "unknown"
        try:
            run = (env.http("GET", vc.swap_url + "/running", headers=h, timeout=3) or {}).get("running") or []
            llm = "loaded" if run else "unloaded"
        except Exception:
            pass
        owner = "video" if (active and active[0]["state"] in ("starting", "running")) or os.path.exists(q.lock_path) else "llm"
        return _j(200, {"gpu": owner, "llm": llm, "active": _public_job(active[0]) if active else None, "queued": len(queued) + len(
            [j for j in active if j["state"] == "waiting"]), "now": time.time(), "enabled": vc.enabled,
                                "ntfy": bool(vc.ntfy_url and vc.ntfy_topic)})                 # on/off only: never the server address or topic

    sys_cache = {"t": 0.0, "v": None}

    def system_snapshot():
        recent = q.recent(200)
        active = next((j for j in recent if j["state"] in video.ACTIVE), None)
        running = next((j for j in recent if j["state"] in ("starting", "running")), None)
        queued = [j for j in recent if j["state"] in ("queued", "waiting")]
        mg = q.mode_get()
        sess = q.session_info()
        llm = False
        try:
            h = {"Authorization": "Bearer " + vc.api_key()} if vc.api_key() else {}
            llm = bool((env.http("GET", vc.swap_url + "/running", headers=h, timeout=2) or {}).get("running"))
        except Exception:
            pass
        tot, avail = host_ram()
        du = disk_free(q.out_dir)
        proc = q.proc
        last = last_speed(recent)
        stage, prog = None, None
        if running or active:
            a = running or active
            stage = str(a.get("note") or a.get("state") or "")[:120]
            prog = float(a["progress"]) if isinstance(a.get("progress"), (int, float)) and not isinstance(a.get("progress"), bool) else None
        dj = next((j for j in recent if j.get("drive_path") or j.get("drive_error")), None)
        d_ok = False
        try:
            d_ok = bool(vc.drive_dir) and os.path.isdir(vc.drive_dir) and os.access(vc.drive_dir, os.W_OK)
        except Exception:
            pass
        return {"mode": "busy" if (q.busy() or sess["active"]) else mg["view"], "llm_loaded": llm,
                "comfy": {"running": bool(proc is not None and proc.poll() is None), "session": sess["active"], "idle_s": sess["idle_s"], "linger_until": mg.get("linger_until"), "port": vc.tailnet_port},
                "queue": {"len": len(queued) + len([j for j in recent if j["state"] in ("starting", "running")]), "running_id": running["id"] if running else None,
                          "stage": stage, "progress": prog},
                "ram": {"total_mb": int(tot // 2 ** 20) if tot else 0, "avail_mb": int(avail // 2 ** 20) if avail else 0},
                "disk": {"out_free_gb": round(du["free"] / 2 ** 30, 1) if du else 0.0},
                "vram": None,
                "last": {"seconds": last["seconds"] if last else None, "out_seconds": last.get("out_seconds") if last else None},
                "drive": {"mode": vc.drive_mode if vc.drive_dir else "off", "dir_ok": d_ok, "last_path": (dj.get("drive_path") or None) if dj else None,
                          "last_error": (str(dj.get("drive_error"))[:200] or None) if dj else None},
                "ntfy": bool(vc.ntfy_url and vc.ntfy_topic), "loudnorm": bool(vc.loudnorm), "version": "studio-v3"}

    def system(req):
        bad = need(req)
        if bad: return bad
        now = time.time()
        if sys_cache["v"] is None or now - sys_cache["t"] > 2.0:
            try:
                sys_cache["v"] = system_snapshot()
            except Exception as e:                                   # fail soft: the tab shows what it has
                sys_cache["v"] = {"mode": "busy", "llm_loaded": False, "error": type(e).__name__, "version": "studio-v3"}
            sys_cache["t"] = now
        return _j(200, sys_cache["v"])

    def mode(req):
        m = req["body"].get("mode")
        if m not in ("video", "llm"): return _j(400, {"error": "mode must be video or llm"})
        try:
            q.mode_set(m)
        except video.VideoBusy as e:
            return _j(409, {"error": str(e)})
        except video.VideoError as e:
            msg = str(e)
            return _j(503 if "not configured" in msg else 500, {"error": msg})
        sys_cache["v"] = None
        return _j(200, {"ok": True, "mode": m})

    def comfy(req):
        act = req["body"].get("action")
        if act not in ("start", "stop"): return _j(400, {"error": "action must be start or stop"})
        try:
            if act == "start": q.session_start()
            else: q.session_stop()
        except video.VideoBusy as e:
            return _j(409, {"error": str(e)})
        except video.VideoError as e:
            return _j(503, {"error": str(e)})
        sys_cache["v"] = None
        return _j(200, {"ok": True, "session": q.session_info()["active"]})

    def clip(req):
        bad = need(req)
        if bad: return bad
        m = re.match(r"^" + T + r"/api/clip/([0-9a-f]{8})/(.+)$", req["path"])
        if not m: return _j(404, {"error": "not found"})
        from urllib.parse import unquote
        name = unquote(m.group(2))
        if not NAME_OK.match(name) or "/" in name or "\\" in name or ".." in name: return _j(400, {"error": "bad name"})
        p = os.path.realpath(os.path.join(real_out, m.group(1), name))
        if os.path.dirname(os.path.dirname(p)) != real_out or not os.path.isfile(p): return _j(404, {"error": "not found"})
        ct = CLIP_TYPES.get(os.path.splitext(p)[1].lower())
        if not ct: return _j(415, {"error": "not a media file"})
        dl = name if req["query"].get("dl") else None
        return 200, {"file": p, "ctype": ct, "download": dl}, ct

    def generate(req):
        b = req["body"]
        wf, params = str(b.get("workflow") or ""), b.get("params")
        if not isinstance(params, dict): return _j(400, {"error": "params must be an object"})
        if not vc.enabled: return _j(503, {"error": "video generation is not set up on this PC"})
        raw = dict(params)
        img = raw.get("image")
        if img not in (None, ""):
            if not isinstance(img, str) or not UP_OK.match(img): return _j(400, {"error": "image must be an uploaded file"})
            raw["image"] = os.path.join(real_up, img)
        try:
            jid, pos, est = q.submit(wf, raw)
        except video.VideoError as e:
            return _j(400, {"error": str(e)})
        return _j(200, {"id": jid, "position": pos, "est_minutes": est})

    def cancel(req):
        jid = str(req["body"].get("id") or "")
        return _j(200, {"result": q.cancel_job(jid)})

    def delete(req):
        ok, msg = q.delete_job(str(req["body"].get("id") or ""))
        return _j(200 if ok else 409, {"result": msg})

    def fav(req):
        b = req["body"]
        jid, on = b.get("id"), b.get("fav")
        if not isinstance(jid, str) or not JOB_ID.match(jid): return _j(400, {"error": "id must be a job id"})
        if not isinstance(on, bool): return _j(400, {"error": "fav must be true or false"})
        if not q.set_fav(jid, on): return _j(404, {"error": "no such job"})
        return _j(200, {"id": jid, "fav": on})

    def rerun(req):
        jid = req["body"].get("id")
        if not isinstance(jid, str) or not JOB_ID.match(jid): return _j(400, {"error": "id must be a job id"})
        old = q.get(jid)
        if not old: return _j(404, {"error": "no such job"})
        if not vc.enabled: return _j(503, {"error": "video generation is not set up on this PC"})
        raw = dict(old.get("params") or {})                                       # the stored, already-cleaned values, checked again against the workflow as it is now
        img = (old.get("files") or {}).get("image")
        if img: raw["image"] = img                                                # submit() re-checks it is an existing png/jpg/webp inside the allowed folders
        try:
            nid, pos, est = q.submit(str(old.get("workflow") or ""), raw)
        except video.VideoError as e:
            return _j(400, {"error": str(e)})
        return _j(200, {"id": nid, "position": pos, "est_minutes": est})

    def upload(req):
        data = req["raw"] or b""
        if not data: return _j(400, {"error": "empty upload"})
        if len(data) > MAX_UPLOAD: return _j(413, {"error": "image is larger than 25 MB"})
        if data[:8] == b"\x89PNG\r\n\x1a\n": ext = "png"
        elif data[:3] == b"\xff\xd8\xff": ext = "jpg"
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP": ext = "webp"
        else: return _j(415, {"error": "use a png, jpg or webp image"})
        name = "up_%s.%s" % (secrets.token_hex(6), ext)
        with open(os.path.join(real_up, name), "wb") as f:
            f.write(data)
        _trim_uploads(real_up, protect=_fav_images(q))
        return _j(200, {"name": name, "bytes": len(data)})

    def assist(req):
        idea = str(req["body"].get("idea") or "").strip()[:1500]
        if not idea: return _j(400, {"error": "write a few words about the shot first"})
        mode = assist_mode(req["body"].get("mode"))
        if any(j["state"] in ("starting", "running") for j in q.recent(200)):
            return _j(409, {"error": "the GPU is rendering right now; the prompt helper needs the language model, so try again when the clip is done"})
        wmeta = (video.load_workflows(vc.workflows_dir).get(str(req["body"].get("workflow") or "")) or {}).get("meta") or {}
        audio = bool(wmeta.get("audio")) if wmeta else True
        h = {"Authorization": "Bearer " + vc.api_key()} if vc.api_key() else {}
        body = {"model": vc.model_id or "default", "max_tokens": 1000 if mode == "multi" else 700, "temperature": 0.7, "reasoning_effort": "low",
                "messages": [{"role": "system", "content": assist_system(mode, audio)}, {"role": "user", "content": idea}]}
        try:
            r = env.http("POST", vc.swap_url + "/v1/chat/completions", body, headers=h, timeout=180)
            text = ((r.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        except Exception as e:
            return _j(502, {"error": "the language model did not answer (%s)" % type(e).__name__})
        text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
        if len(text) > 1 and text[0] == text[-1] == '"' and '"' not in text[1:-1]: text = text[1:-1].strip()   # a wrapper, not dialogue
        if not text: return _j(502, {"error": "the language model returned nothing"})
        return _j(200, {"prompt": text[:2000], "mode": mode})

    table = {"GET " + T: shell, "GET " + T + "/api/workflows": workflows, "GET " + T + "/api/jobs": jobs, "GET " + T + "/api/status": status,
             "GET " + T + "/api/clip/*": clip, "POST " + T + "/api/generate": generate, "POST " + T + "/api/cancel": cancel,
             "POST " + T + "/api/delete": delete, "POST " + T + "/api/upload": upload, "POST " + T + "/api/assist": assist,
             "POST " + T + "/api/fav": fav, "POST " + T + "/api/rerun": rerun, "GET " + T + "/api/system": system, "POST " + T + "/api/mode": mode,
             "POST " + T + "/api/comfy": comfy}
    table.update({"GET %s/%s" % (T, n): pwa_file(n) for n in PWA_FILES})
    return table, {"POST " + T + "/api/upload": MAX_UPLOAD + 4096}


def _fav_images(q):
    """File names of the start images that starred jobs were made from (they must survive, or Run again would have nothing to start from)."""
    return {os.path.basename(str((j.get("files") or {}).get("image") or "")) for j in q.favourites()}


def _trim_uploads(d, keep=60, protect=()):
    """Keep the newest `keep` uploads; anything named in `protect` is never removed and does not count towards the limit."""
    try:
        fs = sorted((os.path.join(d, f) for f in os.listdir(d) if UP_OK.match(f) and f not in protect), key=os.path.getmtime)
        for p in fs[:-keep] if keep else fs:
            os.remove(p)
    except OSError:
        pass


def register(approvals_mod, q, vc, here, env=None):
    table, caps = routes(q, vc, here, env)
    approvals_mod.GPU_BUSY = lambda: os.path.exists(q.lock_path)
    approvals_mod.register_extra(table, caps)
    return table
