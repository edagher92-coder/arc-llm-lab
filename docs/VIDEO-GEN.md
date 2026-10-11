# Local video generation (LTX-2.5 on the Arc Pro B60)

A text-to-video and image-to-video service for the PC. The phone tool gateway ([GATEWAY.md](GATEWAY.md)) queues a job, hands the GPU from the LLM to ComfyUI, renders one clip, collects it, and hands the GPU back. You can drive it from an MCP client (Qwen, Claude Code) or from the Studio web page. Everything runs locally; nothing is sent to a cloud service.

Status: the workflows, gateway code and tooling are in the repo. Render times are **not measured yet**. Every figure marked TBD in this guide is a placeholder, not an estimate (see [Unverified / to measure](#unverified--to-measure)).

## What it is

- **Engine:** ComfyUI 0.39, Intel portable build, PyTorch 2.14+xpu, on Windows 11.
- **Model:** LTX-2.5 (22B video model, with sound), a Gemma4 12B text encoder, a video VAE and a latent upscaler.
- **Driver:** `gateway/video.py`. It is deliberately kill-per-job: start ComfyUI, wait for it, `POST /prompt`, poll `/history`, collect the file, free the models, kill the process. Killing the process is the only release of XPU memory that is guaranteed.
- **Workflows:** JSON files in `workflows_dir`, each `{"meta": ..., "prompt": <API graph with {{placeholders}}>}`. The `meta` block makes a workflow self-describing, so arguments are validated and clamped before anything is queued. They are built from the specs in `gateway/workflows/specs/` with `gateway/tools/build_workflow.py` (see below).

## Requirements

| Item | Needed |
|---|---|
| GPU | Intel Arc Pro B60, 24 GB |
| Host RAM | 32 GB now; 64 GB planned (see the memory plan) |
| OS | Windows 11, current Intel Arc driver |
| Disk | NVMe system drive with room for the models. Not `D:` |
| Python | The portable ComfyUI's own `python_embeded`; the gateway tools use only the standard library |
| Optional | `psutil` in the Python that runs `ltx_bench.py`, for host RAM figures |

## Install layout

Keep ComfyUI and its models on the NVMe system drive. Do not put them on `D:` (slow, and model loading is the dominant cold-start cost).

```
C:\AI\comfy\ComfyUI_windows_portable\          ComfyUI portable (comfy_dir)
  ComfyUI\models\checkpoints\                  the LTX-2.5 22B bf16 model
  ComfyUI\models\text_encoders\                the Gemma4 12B text encoder
  ComfyUI\models\vae\                          the video VAE(s)
  ComfyUI\models\latent_upscale_models\        the x2 latent upscaler (Daily and Hero)
  ComfyUI\input\                               images staged for image-to-video (input_dir)
C:\AI\video\workflows\                         built workflow JSON (workflows_dir)
C:\AI\shared\video\                            finished clips (out_dir, inside the outbox roots)
```

Models (use the exact file names your workflow's loader nodes name; sizes are on the TBD list below):

| Model | Role | Note |
|---|---|---|
| LTX-2.5 22B, **bf16** | The video model | Do not use the int8-convrot file (see Troubleshooting) |
| Gemma4 12B | Text encoder | Has to sit on the GPU; see `--lowvram` below |
| `ltx-2.5-video-vae-conv-bf16` | Faster VAE for the Draft preset | Only if you have it; otherwise the workflow's default VAE |
| LTX-2.5 x2 latent upscaler | Second stage for Daily and Hero | Needs the two-stage graph |

Launch ComfyUI from [`gateway/tools/ltx25_launch.example.bat`](../gateway/tools/ltx25_launch.example.bat) for manual runs and benchmarks. For the gateway, put the same flags in `video.comfy_cmd` and the environment in `video.comfy_env` in `gateway.json`, and set `video.comfy_dir`, `video.input_dir` and the command paths to the NVMe location.

## GGUF build for 32 GB machines (measured on the B60, 11 Oct 2026)

The official int8-convrot files are dequantised on XPU (no int8 speedup) and need about 70 GB of memory to load, which freezes a 32 GB PC. The community **distilled GGUF** fits.

| Part | File | Size |
|---|---|---|
| Transformer (smoke, draft) | `Abiray/LTX-2.5-Distilled-GGUF` `LTX-2.5-Distilled-Q4_K_M.gguf` | 14.6 GiB |
| Transformer (daily, hero; being tested) | same repo, `Q6_K` | 17.3 GiB |
| Text encoder | official `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot` (kept; the Gemma GGUF encoder scored only 0.87 cosine against bf16) | 14.3 GiB |
| Loader node | `city96/ComfyUI-GGUF` pinned at `6ea2651e` plus `pip install gguf` | |
| Guard node | `gateway/comfy_nodes/elz_nodes` (replaces NaN audio with silence) | |

Launch flags: `--disable-dynamic-vram --reserve-vram 1.5 --cache-none --whitelist-custom-nodes ComfyUI-GGUF elz_nodes` (see `gateway.example.json`). Workflows: `ltx25g_t2v`, `ltx25g_i2v` (built from `workflows/specs/ltx25g_*.spec.json`).

**Measured:** Q4_K_M, 768x512, 2 s, 49 frames, with sound: 188 to 219 s from queued to clip, including starting ComfyUI. Sampling ran at about 4.5 s per step (the int8 build was about 2.5 s per step). Free RAM stayed above about 2 GB. The first clip had NaN audio that the AAC muxer rejected; later runs decoded clean, so the guard stays in.

**Watchdog while testing:** stop ComfyUI if Windows "Available MBytes" falls under 400 (do not use "free" memory, it excludes cache and gives false alarms).

The official **temporal x2 upscaler** (`ltx-2.5-latent-temporal-upscaler-x2-bf16-1.0.safetensors`, 0.24 GiB) is in the gated `Lightricks/LTX-2.5` repo, so download it yourself after accepting the licence. A public mirror's copy failed the SHA-256 check against the official file and was rejected.

## Launch flags and why

```
--listen 127.0.0.1 --port 8188 --disable-auto-launch --reserve-vram 1.0
--use-pytorch-cross-attention --preview-method none
--disable-all-custom-nodes --disable-partner-nodes --disable-metadata
```

| Flag | Why |
|---|---|
| `--listen 127.0.0.1` | Loopback only. The gateway is the only client. |
| `--disable-auto-launch` | No browser tab on every job. |
| `--reserve-vram 1.0` | Leaves 1 GB of the 24 GB for the driver and desktop. |
| `--use-pytorch-cross-attention` | PyTorch scaled-dot-product attention, the path used on XPU. |
| `--preview-method none` | No per-step preview decode. |
| `--disable-all-custom-nodes` | Core nodes only: quicker start-up, fewer surprises. |
| `--disable-partner-nodes` | No cloud API nodes. |
| `--disable-metadata` | No prompt or graph embedded in the output file. |

**Drop `--lowvram`.** It is live on XPU and pushes the 12B Gemma4 text encoder to the CPU, which is slow. The older example config used it; remove it.

Environment (set in `video.comfy_env` or the launch script):

| Variable | Effect | Status |
|---|---|---|
| `SYCL_CACHE_PERSISTENT=1` | Keeps compiled kernels on disk, so warm starts are quicker | Keep on |
| `UR_L0_ENABLE_RELAXED_ALLOCATION_LIMITS=1`, `UR_L0_USE_RELAXED_ALLOCATION_LIMITS=1` | Allows allocations above the default Level Zero limit (both spellings, as the name varies by runtime) | **A/B test** |
| `ZES_ENABLE_SYSMAN=1` | Accurate device memory figures for ComfyUI's memory manager | **A/B test** |

The A/B items are recommended starting points, not guaranteed wins. Measure them with the benchmark.

## Memory plan

- **GPU (24 GB):** the LLM and ComfyUI never share it. The gateway unloads the LLM, runs ComfyUI, then kills ComfyUI so the governor can reload the LLM. Inside a job, the text encoder, the 22B model and the VAE take turns on the GPU while the rest waits in host RAM.
- **Host RAM, 32 GB now:** loading is the pressure point, because weights are staged through RAM and the 12B text encoder is large. Keep other heavy applications closed during a render and keep the Windows page file on the NVMe. If a job fails with a host out-of-memory error rather than a GPU one, this is the cause.
- **Host RAM, 64 GB later:** should let the text encoder and model stay cached in RAM, which shortens loads. Keeping ComfyUI warm between jobs would then be possible, but it is a different design from kill-per-job and has not been tested. Treat it as a future option.
- **Resolution and length** are the GPU memory levers. Raise them one step at a time (Draft, then Daily, then Hero).

## Presets

LTX-2.5 needs **frames = 8n + 1** (for example 49, 73, 97, 121) and width and height **divisible by 32**, at 24 fps (LTX-2.3 specs use 25 fps). When a workflow takes `frames`, the gateway turns `seconds` into a frame count of that form (`snap_frames`). When the spec binds `seconds` directly to a graph node, the gateway snaps it so that seconds x fps is a multiple of 8 (`round(s*fps/8)*8/fps`, rounded to 4 decimals), which gives 8n+1 frames. The specs use `multiple_of: 32` for width and height.

| Preset | Size (stage 1) | Length | Frames | Notes |
|---|---|---|---|---|
| Draft | 768 x 416 | 3 s | 73 (49 to 97 works) | 8 steps, single stage, Conv VAE if present. For checking a prompt. |
| Daily | 960 x 544, then x2 latent upscale to 1920 x 1088 | 4 s | 97 | The normal quality setting. |
| Hero | as Daily | 5 s | 121 | Longest clip; most memory and time. |

Render time per preset: **TBD (measure)**. The specs carry `est_minutes: "TBD (measure)"` and a `presets` list (`name`, `label`, `params`) that the Studio page offers. The Daily and Hero sizes are stage-1 sizes; the 1920 x 1088 output needs the upscale stage to be in the built graph.

## The GPU hand-off

Per job, in order (all in `Queue.run`):

1. The worker waits until the LLM has been quiet for `quiet_s` (default 90 s), so it never cuts off a conversation.
2. It records the governor's current mode in `gpu.lock`, sets the mode to `OFF`, and asks llama-swap to unload the LLM; it waits until `llama-server.exe` has gone.
3. It starts ComfyUI and polls `GET /system_stats` until it answers (no fixed sleeps), up to `start_timeout_s`.
4. It fills the workflow, `POST /prompt`, then polls `/history` until the job succeeds, errors, times out (`job_timeout_s`), is cancelled or the kill file appears.
5. It fetches the clips with `/view`, writes a `<clip>.json` sidecar (seed, params, timings) and shares links.
6. Before killing ComfyUI the worker should call `POST /free` with `{"unload_models": true, "free_memory": true}` so models are released in an orderly way (check that your `video.py` does; at the time of writing the call was being added). The kill remains the guarantee.
7. It kills the process tree, restores the governor mode, and the LLM prewarms again. A restart repairs a half-finished hand-off from `gpu.lock`.

Video generation is a "write" tool: the gateway asks for the owner's PIN approval before a job is queued.

## Using it from MCP (async)

Tools registered by `video.py`: `video_workflows`, `video_generate`, `video_status`, `video_result`, `video_queue`, `video_cancel`.

1. `video_workflows`: see the workflows, their parameters and `est_minutes`.
2. `video_generate(prompt, workflow, seconds, width, height, seed, image, negative)` returns at once with `{job_id, position, est_minutes}`. Never wait on it.
3. `video_status(job_id)`: state (`queued`, `waiting`, `starting`, `running`, `done`, `failed`, `cancelled`), a note, elapsed seconds and queue position. It is cheap; poll every 30 to 60 s.
4. `video_result(job_id)`: clip names, share links and metadata when done; the error when failed.
5. `video_cancel(job_id)` stops a queued or running job and closes ComfyUI.

`image` is a path inside the shared folders (`allowed_roots`), for image-to-video. The LLM is paused while a job renders, so tell the user to expect a pause.

## Using Studio

Studio is the browser front end (`gateway/studio.py`), served under `/approvals/studio` and protected by the same PIN login as approvals. It works from a phone over the tailnet. Choose a workflow, pick a preset (Draft, Daily or Hero) or set the size and length, write a prompt (or use the prompt assistant), optionally upload a start image, and press Generate. The library lists recent jobs with playback, cancel and delete. Studio calls the same queue as the MCP tools.

## Building a workflow from the specs

```
python gateway/tools/comfy_ui_to_api.py   <ui_workflow.json> <object_info.json> <api_graph.json>
python gateway/tools/build_workflow.py    gateway/workflows/specs/ltx25_t2v.spec.json <api_graph.json> <object_info.json> C:\AI\video\workflows\ltx25_t2v.json
```

`object_info.json` is `GET /object_info` from the running ComfyUI. Rebuild after any change to a spec's `meta`, because the built file carries its own copy. Tests: `python gateway/tests/test_workflow_tools.py`.

## Benchmark procedure

Use `gateway/tools/ltx_bench.py`. It needs a running ComfyUI and never starts one.

1. Print the plan: `python gateway/tools/ltx_bench.py --matrix` (or `--matrix my.json`, `--shell powershell`). It lists, for each variant, the environment, the ComfyUI command (terminal A) and the benchmark command (terminal B). Variants: baseline, without the relaxed-allocation variables, without `ZES_ENABLE_SYSMAN`, without the persistent cache, a `--lowvram` reference, and the Daily and Hero sizes.
2. For each variant, open a new terminal, start ComfyUI with that variant's environment, then run its benchmark command. Run it **twice**: the first is a cold start (empty kernel cache after a flag change), the second is warm.
3. Each run appends one JSON line to `bench-results.jsonl`: wall time, time to first progress (polled from `/queue`), `exec_s` and per-node timings where `/history` provides them, lowest free VRAM seen, host RAM peak (with `psutil`; add `--pid` for the ComfyUI process tree), outputs, and the time to `/free`.
4. For per-node and sampler timings on builds where `/history` has none, add `--comfy-log <path>` (ComfyUI's console log) and the tool parses the "Prompt executed in" and progress-bar lines added during the run.
5. Compare variants at the same seed, size and length. Do not draw conclusions from a single run.

Self test (no GPU needed): `python gateway/tools/ltx_bench.py --selftest`.

## Troubleshooting

- **Slow first job after a change:** cold start. Kernels are compiled the first time (and again after a driver or flag change). `SYCL_CACHE_PERSISTENT=1` makes later starts quicker. Compare warm runs, not the first.
- **"ComfyUI did not answer within N s":** raise `start_timeout_s` for the cold start; check `state\video\comfy.log`.
- **Out of memory on the GPU:** drop to a smaller size or shorter length (Draft first), confirm nothing else holds the GPU (the LLM must be unloaded), and keep `--reserve-vram 1.0`. Do not "fix" it with `--lowvram`; that moves the text encoder to the CPU.
- **Out of memory on the host:** close other applications, check the page file is on the NVMe, and see the memory plan.
- **int8 file gives no speed-up:** on Intel XPU ComfyUI dequantises the int8-convrot LTX-2.5 file to bf16 and computes in bf16. Use the bf16 model and save the disk space.
- **"ComfyUI rejected the workflow":** a model file name in the graph does not match a file on disk, or the size or frame count is not valid (32 and 8n+1).
- **LLM does not come back:** check `gpu.lock` in the gateway state folder; a gateway restart restores the recorded governor mode.

## Licence

LTX-2.x is released under the **LTX-2.x Community License**. Entities with annual revenue of US$10 million or more need a paid licence from Lightricks. Do not remove the model's safety or transparency features (for example watermarking or provenance information), and follow the licence's acceptable-use terms. Read the licence text that ships with the model files before commercial use; this guide is not legal advice. `--disable-metadata` only stops ComfyUI embedding the prompt and graph in files; it does not remove any such features from the model itself.

## Unverified / to measure

Nothing here has been measured on this PC yet. Do not quote these as results.

- Render time per preset (Draft, Daily, Hero), cold and warm: **TBD**.
- Cold-start time to `/system_stats`, and the saving from `SYCL_CACHE_PERSISTENT`: **TBD**.
- Effect of the relaxed-allocation variables and `ZES_ENABLE_SYSMAN`: **TBD** (A/B, may be zero).
- File sizes of the 22B model, text encoder, VAEs and upscaler on disk: **TBD** (check the folders).
- Peak host RAM and lowest free VRAM per preset; whether 32 GB is enough for Hero: **TBD**.
- Whether the Conv VAE changes quality as well as speed in Draft: **TBD**.
- Whether 64 GB makes a warm-ComfyUI design worth building: **TBD**.
- Whether `POST /free` before the kill makes any visible difference: **TBD**.
- Whether `/history` on this ComfyUI build carries per-node timings: **TBD** (the benchmark records them if so).
