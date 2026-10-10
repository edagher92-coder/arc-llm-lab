# Setup (Windows 11, Intel Arc Pro B60 24GB)

The scripts assume this layout, so keep the paths or update them in `governor/profiles.json`, `llama-swap/config.yaml` and the wrappers:

```
C:\AI\llama.cpp\vulkan-intelfa\   engine build (engine\build.ps1)
C:\AI\llama.cpp\vulkan\           optional: official llama.cpp Vulkan release (qwen engine stock)
C:\AI\models\qwen3.8-27b\         Qwen3.8-27B-UD-Q4_K_M.gguf, mmproj-F16.gguf, Qwen3.8-27B-DFlash2-Q4_K_M.gguf
C:\AI\llama-swap\                 llama-swap.exe, config.yaml, api-key.txt
C:\AI\governor\                   everything from governor\ (+ voice\voice.html in governor\public\)
C:\AI\bench\                      everything from bench\ (benchmarks write their logs here)
C:\AI\evalsuite\                  everything from evalsuite\
C:\AI\tts\  C:\AI\whisper\         created by voice\setup-*.ps1
C:\AI\claude-local\               agents\claude-local\ (LOCAL-SYSTEM.md, mcp.json)
%USERPROFILE%\bin\                agents\claude-qwen.cmd, agents\codex-qwen.cmd
```

## 1. Engine

```powershell
powershell -ExecutionPolicy Bypass -File engine\build.ps1
```

This needs git and Python on PATH. It downloads a portable toolchain, checks and applies the two vendored Intel FA patches ([engine/patches/](../engine/patches/)) to llama.cpp b11524, and writes `C:\AI\llama.cpp\vulkan-intelfa\llama-server.exe`. Our own build log shows 3 min 21 s from start to `BUILD OK` on a run where the toolchain was already in place ([build.log](../data/raw/build.log)); a first run also downloads the toolchain. On Linux use [engine/build-linux.sh](../engine/build-linux.sh) (patch application verified; not run on Linux with an Arc GPU by the author). Background: [INTEL-FA.md](INTEL-FA.md).

## 2. Models

Download `Qwen3.8-27B-UD-Q4_K_M.gguf` and `mmproj-F16.gguf` (vision) from [unsloth/Qwen3.8-27B-GGUF](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF) on Hugging Face, plus the DFlash2 draft GGUF (`Qwen3.8-27B-DFlash2-Q4_K_M.gguf`), into `C:\AI\models\qwen3.8-27b\`. We did not record where we downloaded the drafter from, so look for a Qwen3.8-27B DFlash2 draft on Hugging Face and check its licence; if you know the right source, please [tell us](https://github.com/edagher92-coder/arc-llm-lab/issues/new?template=bug.yml). Optional extras: `Qwen3.8-27B-Q4_0.gguf` for the turbo variant, and an MTP draft for the 262K variant.

## 3. Key and server

```powershell
$b = New-Object byte[] 24; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); $k = ([BitConverter]::ToString($b) -replace '-').ToLower()
setx LOCAL_QWEN_KEY $k; $k | Set-Content C:\AI\llama-swap\api-key.txt
```

Put `llama-swap.exe` and [llama-swap/config.yaml](../llama-swap/config.yaml) in `C:\AI\llama-swap\`. Then register two logon tasks, both started through `conhost.exe --headless` so no console windows pop up:

```
conhost.exe --headless "C:\AI\llama-swap\llama-swap.exe" --config "C:\AI\llama-swap\config.yaml" --listen 127.0.0.1:8090
conhost.exe --headless powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\AI\governor\governor.ps1"
```

## 4. Verify

```powershell
qwen doctor      # 26 checks: server, governor, VRAM headroom, no-context-shift, voice, Tailscale routes, tasks, agents, power, disks, last benchmark
qwen bench       # 3-turn agent test at 30-37K context. We measured 55-57 s, coding 7/7, tools 3/3 (details: INTEL-FA.md)
qwen snapshot "first working config"
```

`qwen` is `governor\qwen.ps1`. Add a `qwen.cmd` shim on PATH that calls it.

## 5. Remote (optional): Tailscale

```powershell
tailscale serve --bg --https=8445 http://127.0.0.1:8090                       # API for other PCs, tailnet only
tailscale serve --bg --https=8445 --set-path=/governor/ C:\AI\governor\public  # status page + voice page
```

Keep everything **tailnet-only**. Don't use `tailscale funnel` for the model API.

## 5b. A chat UI, voice and tools (optional)

[PLATFORM.md](PLATFORM.md) adds Open WebUI on top of this setup, with voice in and out ([VOICE.md](VOICE.md)), MCP tools and phone access over Tailscale, and the settings that keep it from disturbing the prompt cache.

## 6. Nightly regression (optional)

Schedule `governor\nightly.ps1` daily at 3 am. It runs the doctor, the benchmark and a 14-task agent sample, and writes `governor\public\nightly.json`. It skips itself while an evaluation is running or the model is busy.
