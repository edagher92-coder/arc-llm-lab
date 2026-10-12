@echo off
rem ============================================================================
rem  ltx25_launch.example.bat  -  launch ComfyUI for LTX-2.5 on an Intel Arc Pro B60 (XPU)
rem
rem  A TEMPLATE. Copy to ltx25_launch.bat (or into the gateway's video.comfy_cmd /
rem  video.comfy_env) and edit the paths in the "EDIT THESE" block. No secrets here.
rem
rem  Use this for manual runs and for the benchmark (gateway\tools\ltx_bench.py).
rem  The gateway itself starts ComfyUI from gateway.json "video.comfy_cmd" and
rem  "video.comfy_env"; keep the two in step with this file.
rem ============================================================================
setlocal

rem ---- EDIT THESE -----------------------------------------------------------
rem ComfyUI portable folder. Keep it on the NVMe system drive, never on D:.
set "COMFY_ROOT=C:\AI\comfy\ComfyUI_windows_portable"
set "PORT=8188"
rem Optional: extra flags for an A/B variant, e.g. set "EXTRA_FLAGS=--fp16-vae"
set "EXTRA_FLAGS="
rem ---------------------------------------------------------------------------

rem ---- Environment (Level Zero / SYCL) --------------------------------------
rem SYCL_CACHE_PERSISTENT=1  Keeps compiled kernels on disk, so the second
rem                          start is much less slow than a cold one.
rem                          Not an A/B item: harmless, keep it on.
set SYCL_CACHE_PERSISTENT=1

rem A/B TEST ITEMS (not guaranteed to help; measure each with ltx_bench.py):
rem UR_L0_ENABLE_RELAXED_ALLOCATION_LIMITS / UR_L0_USE_RELAXED_ALLOCATION_LIMITS
rem                          Allow single allocations above the default Level Zero
rem                          size limit (large video latents / attention buffers).
rem                          Both spellings are set because the name differs by
rem                          runtime version. A/B TEST.
set UR_L0_ENABLE_RELAXED_ALLOCATION_LIMITS=1
set UR_L0_USE_RELAXED_ALLOCATION_LIMITS=1
rem ZES_ENABLE_SYSMAN=1      Lets PyTorch read accurate free/total device memory
rem                          (used by ComfyUI's memory manager). A/B TEST.
set ZES_ENABLE_SYSMAN=1

rem ---- Flags ----------------------------------------------------------------
rem --listen 127.0.0.1          Loopback only. Never expose ComfyUI to the network.
rem --port %PORT%               Must match gateway.json video.comfy_url.
rem --disable-auto-launch       Do not open a browser tab.
rem --reserve-vram 1.0          Leave 1 GB of the 24 GB for the driver/desktop.
rem --use-pytorch-cross-attention
rem                             PyTorch SDPA attention (the XPU path we use).
rem --preview-method none       No per-step previews (saves time and memory).
rem --disable-all-custom-nodes  Only core nodes: faster start, no surprises.
rem --disable-partner-nodes     No cloud API nodes.
rem --disable-metadata          Do not embed the prompt/workflow in outputs.
rem
rem NOT USED: --lowvram. On XPU it is live and pushes the 12B Gemma text encoder
rem to the CPU, which is slow. Do not add it back without measuring.
rem
rem NOT USED: the int8-convrot LTX file. On XPU ComfyUI dequantises it to bf16 and
rem computes in bf16, so int8 gives no speed-up. Use the bf16 model.
rem
rem Quote the folder. Only add --windows-standalone-build if your portable build
rem needs it (the stock run_intel_gpu.bat includes it).
rem ---------------------------------------------------------------------------

cd /d "%COMFY_ROOT%" || (echo COMFY_ROOT not found: %COMFY_ROOT% & exit /b 1)

"%COMFY_ROOT%\python_embeded\python.exe" -s ComfyUI\main.py --windows-standalone-build ^
  --listen 127.0.0.1 --port %PORT% ^
  --disable-auto-launch ^
  --reserve-vram 1.0 ^
  --use-pytorch-cross-attention ^
  --preview-method none ^
  --disable-all-custom-nodes ^
  --disable-partner-nodes ^
  --disable-metadata ^
  %EXTRA_FLAGS%

endlocal
