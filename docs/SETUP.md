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

This needs git and Python on PATH. It downloads a portable toolchain and writes `C:\AI\llama.cpp\vulkan-intelfa\llama-server.exe`.

## 2. Models

Download the Qwen3.8-27B GGUF (UD-Q4_K_M), its `mmproj-F16` for vision, and the DFlash2 draft GGUF into `C:\AI\models\qwen3.8-27b\`. Optional extras: `Qwen3.8-27B-Q4_0.gguf` for the turbo variant, and an MTP draft for the 262K variant.

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
qwen bench       # 3-turn agent test at 30-37K context. Expect ~55 s, coding 7/7, tools 3/3
qwen snapshot "first working config"
```

`qwen` is `governor\qwen.ps1`. Add a `qwen.cmd` shim on PATH that calls it.

## 5. Remote (optional): Tailscale

```powershell
tailscale serve --bg --https=8445 http://127.0.0.1:8090                       # API for other PCs, tailnet only
tailscale serve --bg --https=8445 --set-path=/governor/ C:\AI\governor\public  # status page + voice page
```

Keep everything **tailnet-only**. Don't use `tailscale funnel` for the model API.

## 6. Nightly regression (optional)

Schedule `governor\nightly.ps1` daily at 3 am. It runs the doctor, the benchmark and a 14-task agent sample, and writes `governor\public\nightly.json`. It skips itself while an evaluation is running or the model is busy.
