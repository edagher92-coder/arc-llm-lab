# Upscale a finished clip x2 (LTX-2.5)

Status: spec and tests are in the repo; of the wiring below only the video.py `video` input type is applied (see the finishing section above). **Nothing has been run**: no render, ComfyUI not started, nothing downloaded. Labels: VERIFIED = read from the repo or from the PC's files (object_info.json, custom node and ComfyUI sources, 12 Oct 2026); INFERRED = reasoned, needs a real run.

## Finish at 1080p / 2K / 4K (built, in the repo)

Status: code and tests done (`tests/test_finish.py`, `test_recommend_and_finish_routes` in `tests/test_studio.py`); a headless-browser check of the Studio buttons passed on the dev box with real ffmpeg. **Not yet run on ELZYDLAB** and not deployed. ffmpeg must be on the PC's PATH or set as `ffmpeg_path` in the video config; if it is missing the job records "ffmpeg was not found".

- **No length limit.** The generator is bound by memory (`width x height x frames <= 80 M`), so a long clip is generated at the largest size that fits and enlarged afterwards. `GET /api/recommend?seconds=&aspect=&target=1080p|2k|4k` returns that plan (`video.recommend_plan`): 3 s lands at 1344x768, 10 s at 704x384, 15 s at 576x320.
- **Finishing is ffmpeg lanczos + light sharpen + x264 crf 16, on the CPU.** It never takes the GPU, so Qwen or the next render is not held up. `POST /api/finish {id, clip, target}` starts it; `Queue.finish` writes `<clip>_<target>.mp4` beside the clip and adds it to the job.
- **Auto:** the Create tab's "Finish at" chips (Off, 1080p, 2K, 4K) send `finish` with the job; the clip is upscaled as soon as the render is done. "Use recommended size" sets the frame to the plan's generation size. The viewer has Upscale 1080p / 2K / 4K buttons for any finished clip.
- **Honest limit:** this enlarges, it does not add detail. Above 2x (4K from a 10 s clip is 5.6x) the picture is clean but soft. A learned upscaler (SeedVR2 3B) would add detail and is the next step; it is NOT installed, NOT confirmed on Intel Arc, and its download needs Elz's yes. `recommend_plan` already returns `method: "lanczos"` so the method can change without touching the UI.
- Output sizes snap to standard ratios (16:9, 9:16, 1:1, 4:3, 3:2) within 6%, the few pixels of difference are cropped: 1920x1080, 2560x1440, 3840x2160 (short side 1080/1440/2160).
- The latent x2 workflow below is still a draft and is not installed. The video-input wiring it needs is now in `video.py` (`video` param type, `_check_video`); `/api/upscale` and its button are deliberately not added, because the ffmpeg path covers the need and the latent path is unmeasured.

## What it does (latent x2 workflow, draft, not installed)

A short finished clip (the gateway's own output, for example 768x416) goes in; a clip at double the size (1536x832) comes out with the original sound. No new model files and no 15 GB text encoder: everything is already on disk and the prompt is encoded by Lightricks' hosted encoder through our `ElzLTXAPITextEncode`.

Workflow name once built: `ltx25g_upscale_api` (build command below). Spec: `gateway/workflows/specs/ltx25_upscale.spec.json`. Tests: `gateway/tests/test_upscale.py` (14 pass). The graph is the second half of the live `ltx25g_t2v_api` graph (x2 latent upscale, then the 3-step distilled refine) fed with a real clip instead of a fresh render.

## Graph (33 nodes, all from the spec's `add` block; node ids are the spec's)

```
LoadVideo {{video}} -> GetVideoComponents (frames, audio, fps)
frames -> GetImageSize (w, h, count)
cap:  N = 8n+1 frames = min(count, round({{seconds}} x fps)+1, floor(60,000,000 / (w x h x 4)))     (ComfyMathExpression)
frames -> ImageFromBatch (first N) -> ImageScale lanczos to multiples of 32 (no-op for gateway clips)
-> VAEEncode (ltx-2.5-video-vae-bf16) -> LTXVLatentUpsampler (x2 spatial upscaler) 
-> LTXVConcatAVLatent (+ LTXVEmptyLatentAudio from ltx-2.5-audio-vae-bf16, N frames)
UnetLoaderGGUF (LTX-2.5-Distilled-Q4_K_M) -> LTXVDualCFGGuider (cfg 1/1)
ElzLTXAPITextEncode x2 ({{prompt}}, {{negative}}) -> LTXVConditioning (source fps)
RandomNoise {{seed}} + euler_ancestral + ManualSigmas "0.85, 0.7250, 0.4219, 0.0" -> SamplerCustomAdvanced
-> LTXVSeparateAVLatent -> VAEDecodeTiled (512/64, 64/16)
-> CreateVideo (decoded frames + the ORIGINAL audio trimmed to N frames, source fps) -> SaveVideo video/gw_ltx25g_upscale
```

Why this graph: it is exactly the proven stage 2 of the live text-to-video graph (same sampler, sigmas, guider, decode), so the only new things are the front end (load, trim, encode) and the audio mux. The generated audio latent is only there because the model wants an AV latent; it is discarded and the original soundtrack is muxed back (lossless, and it avoids the audio NaN problem seen on this card, so `ElzAudioNanGuard` is not needed).

Drafts that came before this (the earlier version of this file) used the Lightricks TiledFusion recipe with the Refine Details IC-LoRA. That file is not on the PC (a 1.3 GB download) and the draft also loaded the 14 GB local Gemma encoder. Both contradict the brief, so it was dropped. Its tiling, per-tile memory and "about an hour" figures were extrapolations for a different graph and no longer apply.

## Limits and the guard

- The sampler is untiled (no tiled sampler takes a plain AV latent: INFERRED, LTXVTiledSampler and LTXVTiledFusionSampler need other latent types). So length is limited instead.
- The measured evidence: 960x544x193 frames (100 M px-frames) spilled VRAM in stage 2 at 141 s/step. The gateway default guard is 60 M px-frames; the output of an x2 upscale is 4x the source, so the spec sets `max_px_frames` to 15,000,000 on the SOURCE size (= 60 M at the output).
- 768x416 source: at most 41 frames (1.7 s at 24 fps). 2 s (49 frames) is refused with "Try at most 46 frames ... " (the 8n+1 snap makes it 41). 960x544: 25 frames (1 s) passes (13.1 M), 41 does not (21.4 M). 1280x704: refused even at the 1 s minimum (the guard allows 9 frames there).
- The refusal comes from the gateway (`_check_px_frames`) only when it knows the source size, so `width` and `height` are REQUIRED params (guard only; the graph reads the true size). The graph applies the same cap again from the real clip, so a wrong width/height cannot spill the card; it silently shortens instead.
- Trim advice in the message is generic ("Try at most N frames or WxH"); for an upscale the right fix is a smaller `seconds`.
- Longer clips: upscale in 1.7 s pieces and join, or (later) add a tiled variant. Not built.

Time (INFERRED, unmeasured): 3 steps at about 7.5k tokens (48x26x6 latent) ~ tens of seconds each, plus model load, encode and decode: roughly 6 minutes, spec says `est_minutes: 6` with an UNMEASURED note. `job_timeout_s` 3600 is ample. Replace the figure after the first run.

## Confirmed node classes

All 26 classes used, confirmed on the PC (core classes from `C:\AI\video\object_info.json`, which also gave every input name and output slot; Elz and GGUF from source):

- ComfyUI core: LoadVideo, GetVideoComponents, GetImageSize, ImageFromBatch, ImageScale, TrimAudioDuration, CreateVideo, SaveVideo, ComfyMathExpression, PrimitiveFloat, VAELoader, VAEEncode, VAEDecodeTiled, LatentUpscaleModelLoader, LTXVLatentUpsampler, LTXVEmptyLatentAudio, LTXVConcatAVLatent, LTXVSeparateAVLatent, LTXVDualCFGGuider, LTXVConditioning, RandomNoise, KSamplerSelect, ManualSigmas, SamplerCustomAdvanced.
- ComfyUI-GGUF: UnetLoaderGGUF (nodes.py, NODE_CLASS_MAPPINGS).
- elz_nodes: ElzLTXAPITextEncode (`__init__.py` registers it; inputs prompt, enhance_prompt, ltx_version, gemma_version).
- ComfyUI-LTXVideo (official pack, commit 3bf3ca62): no class from it is used. object_info.json is stale for the pack (it lists none of its nodes, nor ElzAudioNanGuard); it only reflects core.

Model files (all on disk per the brief): `LTX-2.5-Distilled-Q4_K_M.gguf`, `ltx-2.5-video-vae-bf16`, `ltx-2.5-audio-vae-bf16`, `ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0` (the last three `.safetensors`). Needs the LTX API key file read by the encode node (`C:\AI\secrets\ltx-api-key.txt`).

## Build and install

```
echo {} > empty_graph.json
python gateway\tools\build_workflow.py gateway\workflows\specs\ltx25_upscale.spec.json empty_graph.json C:\AI\video\object_info.json C:\AI\video\workflows\ltx25g_upscale_api.json
```

`build_workflow.py` needs no change (the spec adds every node; only SaveVideo's output flag is read from object_info). Do the copy only after the wiring below is in, otherwise the Studio lists a workflow it cannot fill. Rebuild after any change to `meta`.

## Wiring needed (nothing applied)

`video` is a new param type. Today `video.py` stores an unknown type as text, so the raw path would be written into `LoadVideo.file` and fail.

### video.py
1. `_resolve` (about line 282): `elif t == "image" or t == "video": files[name] = str(v)`.
2. `Queue.submit` (line 570): pick the validator by declared type, e.g.
   `pspec = wfs[workflow]["meta"].get("params") or {}` then `files[name] = self._check_video(path) if (pspec.get(name) or {}).get("type") == "video" else self._check_image(path)`.
3. New `_check_video` beside `_check_image` (line 581): same `allowed_roots` test, extension in (.mp4, .webm, .mov), existing file, size cap (200 MB suggested), return the real path.
4. The worker's staging loop (line 832, `vals[name] = self._stage_image(path)`) already works for a video: it copies to `input_dir` as `gw_<hex>.mp4`, which `LoadVideo` reads. Staged inputs are never cleaned (also true of images); consider deleting old `gw_*` files.
5. Optional MCP `video_generate`: add `video: str = ""` and pass it through. Not needed for the Studio button.

### studio.py
The browser must never send a path. Add one endpoint mirroring `clip()` (line 343; `NAME_OK`, `JOB_ID`, `real_out` exist):
```python
def upscale(req):
    b = req["body"]; jid, name = b.get("id"), str(b.get("clip") or "")
    if not isinstance(jid, str) or not JOB_ID.match(jid): return _j(400, {"error": "id must be a job id"})
    if not NAME_OK.match(name) or "/" in name or "\\" in name or ".." in name: return _j(400, {"error": "bad name"})
    if not vc.enabled: return _j(503, {"error": "video generation is not set up on this PC"})
    p = os.path.realpath(os.path.join(real_out, jid, name))
    if os.path.dirname(os.path.dirname(p)) != real_out or not os.path.isfile(p) or not name.lower().endswith((".mp4", ".webm")):
        return _j(404, {"error": "not found"})
    old = q.get(jid) or {}; op = old.get("params") or {}
    fps = 24.0   # meta fps of the workflow
    if not (op.get("width") and op.get("height")): return _j(400, {"error": "this clip's size is unknown; upscale needs the job's width and height"})
    raw = {"video": p, "width": op["width"], "height": op["height"], "seed": op.get("seed", -1),
           "seconds": min(float(op.get("seconds") or 1.7), float(b.get("seconds") or 1.7))}
    try: nid, pos, est = q.submit("ltx25g_upscale_api", raw)
    except video.VideoError as e: return _j(400, {"error": str(e)})
    return _j(200, {"id": nid, "position": pos, "est_minutes": est})
```
Register: `"POST " + T + "/api/upscale": upscale` (line 443). `real_out` must sit under `allowed_roots` (example config: out_dir `C:\AI\shared\video`, root `C:\AI\shared`). Remove the unused `fps` line if copied. A refusal from the guard is returned to the browser as the 400 text. In `rerun()` (line 397) carry every staged file: replace the `img = ...` lines with `for k, pth in (old.get("files") or {}).items(): raw[k] = pth` so a re-run of an upscale job works.

### studio/index.html
1. In the viewer actions (line 846, beside "Continue from last frame"): when `j.clips[0].type.startsWith("video") && S.wfs.some(w => w.name === "ltx25g_upscale_api") && j.workflow !== "ltx25g_upscale_api"`, add a button "Upscale x2".
2. `upscale(j, btn)` modelled on `rerun()` (line 876): `api("upscale", {method: "POST", json: {id: j.id, clip: j.clips[0].name}})`, then toast, `S.sel = d.id`, `refresh()`, `tab("queue")`. Show the returned error text on a 400 (the guard message). Optional confirm: about 6 min (UNMEASURED), holds the GPU.
3. Keep the workflow out of the "Make video" picker: skip params of `type === "video"` in the param loop (about line 735) and filter `w.kind !== "upscale"` in `shotWf` (line 960) and any "first workflow" fallback. The workflow has no `sizes` and no prompt-first flow. `estFor()` (line 460) uses `est_ref` [768,416,1.7] with the job's width/height/seconds, which scales properly.

### gateway.example.json
No change required: `job_timeout_s` 3600 covers it, `video_max_px_frames` stays 60000000 (the workflow's own `max_px_frames` overrides it).

## Not verified / risks

- No run. Input names and slots match object_info.json, but ComfyMathExpression's autogrow inputs (`values.a`..`values.d`, four here, two in the live graph) and its `min`/`floor`/`round` use come from reading `nodes_math.py` (the function table has them), not from a run.
- `LoadVideo.file` is a combo of the input folder's videos; the staged `gw_<hex>.mp4` must be there before submit (the worker stages first, as for images).
- Quality: a 0.85 start sigma re-noises heavily; the result may drift from the source (faces, text). A fidelity-first variant would start lower (for example "0.7250, 0.4219, 0.0"); not provided because untested. Prompt describes the look only.
- LTXVLatentUpsampler on a VAEEncode latent (not a sampler latent): INFERRED fine (same space as stage 1 output), unproven.
- Memory: the 41-frame cap equals the 60 M guard, which is the highest size measured to run; stage 2 at 63 M (960x544x121) is also in the live graph. Near the limit step time may jump; reduce `seconds`.
- A clip with no soundtrack: TrimAudioDuration returns no audio (VERIFIED in source) and CreateVideo gets none; output is silent. Not run.
- Frame count shorter than 9 or not 8n+1 (non-gateway clip) is used as is below the cap; the VAE needs 8n+1.
- The `kind: upscale` workflow and missing `sizes` may need Studio tolerance (see above).
