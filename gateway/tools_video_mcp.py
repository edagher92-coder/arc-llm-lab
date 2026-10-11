"""Extra MCP tools for LTX-2.5 video, layered on video.py's Queue (no logic duplicated: every tool calls a Queue method).

  video_system        read   GPU owner (video | llm | busy), ComfyUI session, queue depth, governor mode
  video_presets       read   quality presets per workflow + the LTX-2.5 ComfyUI graphs in presets/ltx25/index.json
  video_comfy_session write  action start|stop: interactive ComfyUI session (CueForge / raw graphs / comfy-mcp)
  video_mode          write  mode video|llm: hand the GPU to video or back to the LLM
  video_generate      write  re-registered with a `preset` argument (replaces video.py's version; same Queue.submit)

Policy: video_system and video_presets belong in policy.read; the other three are not listed there, so the gateway's default intent
("write") makes them PIN-gated exactly like video_generate. Called from gateway.build() right after video.register().
"""
import json, os, sys

import video


def _j(x):
    return json.dumps(x, separators=(",", ":"))


def load_index(base_dir):
    """presets/ltx25/index.json reduced to what an agent needs; {} when the file is missing or unreadable."""
    try:
        d = json.load(open(os.path.join(base_dir, "presets", "ltx25", "index.json"), encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    out = []
    for p in d.get("presets") or []:
        if isinstance(p, dict) and p.get("name"):
            out.append({"name": p["name"], "file": p.get("file", ""), "purpose": p.get("purpose", ""), "runnable_now": bool(p.get("runnable_now")),
                        "needs_ic_lora_download": bool(p.get("needs_ic_lora_download")), "ic_loras": p.get("ic_loras") or [],
                        "unconfirmed_models": p.get("unconfirmed_models") or []})
    return {"comfy_graphs": out, "models": d.get("our_models") or {}, "source_sha": d.get("source_sha", "")}


def find_preset(workflows, name, workflow=""):
    """(workflow_name, params) for a quality preset (workflow meta.presets); None when unknown. Searches one workflow, or all.
    Raises ValueError("ambiguous", [workflow names]) when no workflow is given and more than one workflow has the preset."""
    want = str(name).strip().lower()
    hits = []
    for wn in ([workflow] if workflow else sorted(workflows)):
        for p in (((workflows.get(wn) or {}).get("meta") or {}).get("presets") or []):
            if isinstance(p, dict) and isinstance(p.get("params"), dict) and want in (str(p.get("name", "")).lower(), str(p.get("label", "")).lower()):
                hits.append((wn, p["params"]))
                break
    if len(hits) > 1:
        raise ValueError("ambiguous", [h[0] for h in hits])
    return hits[0] if hits else None


def register(server, q, base_dir):
    """Add the tools to `server` using Queue `q` (as returned by video.register). No-op when q is None."""
    if q is None:
        return
    vc = q.cfg
    prov = getattr(server, "local_provider", None)          # FastMCP: drop video.py's video_generate so the one below (with `preset`) replaces it
    if prov is not None:
        try:
            prov.remove_tool("video_generate")
        except Exception as e:
            sys.stderr.write("video: could not remove video.py's video_generate before re-registering (%r)\n" % (e,))

    @server.tool(name="video_system", description="Read-only video/GPU state: who has the GPU (video, llm or busy), ComfyUI session (active, state, idle_s), queue depth, governor mode. Call before video_comfy_session or video_mode.")
    def video_system() -> str:
        recent = q.recent(50)
        mg, sess = q.mode_get(), q.session_info()
        running = next((j["id"] for j in recent if j["state"] in ("starting", "running")), None)
        return _j({"enabled": vc.enabled, "mode": "busy" if (q.busy() or sess["active"]) else mg["view"], "governor_mode": mg["mode"], "hold": mg["hold"],
                   "comfy_session": sess, "comfy_url": vc.comfy_url, "queued": len([j for j in recent if j["state"] in ("queued", "waiting")]), "running_job": running})

    @server.tool(name="video_presets", description=(
        "Read-only. Lists (a) quality presets per workflow, usable as video_generate(preset=...) [name, params, note], and (b) the LTX-2.5 ComfyUI graphs "
        "(presets/ltx25) with purpose, runnable_now and IC-LoRA needs; those graphs run only inside a ComfyUI session (video_comfy_session start), not through video_generate."))
    def video_presets() -> str:
        wfs, out = video.load_workflows(vc.workflows_dir), {}
        out["workflow_presets"] = {wn: [{"name": p.get("name"), "params": p.get("params"), "note": p.get("note", "")} for p in (w["meta"].get("presets") or []) if isinstance(p, dict)]
                                   for wn, w in wfs.items() if w["meta"].get("presets")}
        out.update(load_index(base_dir))
        return _j(out)

    @server.tool(name="video_comfy_session", description=(
        "Needs the owner's approval. action=start takes the GPU from the LLM and starts an interactive ComfyUI (CueForge/raw graphs) on 127.0.0.1:8188; "
        "action=stop kills it and gives the GPU back. Returns {active,state,idle_s,error}; start returns at once ('starting'), poll video_system. "
        "Refused while a video job runs. It auto-stops when idle."))
    def video_comfy_session(action: str) -> str:
        if action not in ("start", "stop"):
            return "action must be start or stop"
        try:
            return _j(q.session_start() if action == "start" else q.session_stop())
        except video.VideoError as e:                      # includes VideoBusy
            return "Refused: %s" % e

    @server.tool(name="video_mode", description=(
        "Needs the owner's approval. mode=video releases the LLM from the GPU (governor OFF) so ComfyUI can use it; mode=llm gives the GPU back to the LLM. "
        "Refused while a job is queued/running or a ComfyUI session is active. Returns {mode,view,hold}."))
    def video_mode(mode: str) -> str:
        if mode not in ("video", "llm"):
            return "mode must be video or llm"
        try:
            return _j(q.mode_set(mode))
        except video.VideoError as e:
            return "Refused: %s" % e

    @server.tool(name="video_generate", description=(
        "Queue a video render and return at once with {job_id, workflow, position, est_minutes}. Needs the owner's approval. Never wait on it: "
        "poll video_status(job_id), then video_result(job_id). Takes minutes; the LLM is paused while it renders. "
        "prompt = what to film (required); workflow = a name from video_workflows (default: first); preset = a quality preset from video_presets "
        "(e.g. draft, daily, hero) that fills width/height/seconds; seconds, width, height, seed (-1 = random), negative = what to avoid; "
        "explicit arguments override the preset. image = file path inside the shared folders, for image-to-video."))
    def video_generate(prompt: str, workflow: str = "", preset: str = "", seconds: float = 0, width: int = 0, height: int = 0, seed: int = -1, image: str = "", negative: str = "") -> str:
        if not vc.enabled:
            return "Video generation is not set up on this PC (no ComfyUI configured)."
        wfs = video.load_workflows(vc.workflows_dir)
        wf = workflow or next(iter(sorted(wfs)), "")
        raw = {"prompt": prompt, "seconds": seconds, "width": width, "height": height, "seed": seed, "image": image, "negative": negative}
        if preset:
            try:
                hit = find_preset(wfs, preset, workflow)
            except ValueError as e:
                return "Not queued: ambiguous preset %r; pass workflow (one of: %s)" % (preset, ", ".join(e.args[1]))
            if not hit:
                return "Not queued: unknown preset %r (see video_presets)" % preset
            wf, pp = hit
            for k in ("width", "height", "seconds"):
                if not raw[k] and isinstance(pp.get(k), (int, float)) and not isinstance(pp.get(k), bool):
                    raw[k] = pp[k]
        try:
            jid, pos, est = q.submit(wf, raw)
        except video.VideoError as e:
            return "Not queued: %s" % e
        return _j({"job_id": jid, "workflow": wf, "position": pos, "est_minutes": est})
