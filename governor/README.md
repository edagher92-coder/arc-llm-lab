# Governor (v4.3)

The governor keeps the local Qwen server sized to what the PC is doing. It picks a profile (MAX when you're away, BALANCED while you work, LEAN under load) and sizes the context window to the VRAM actually free at each load. It never unloads while a request is in flight, and it saves the KV slot before its own reloads so agents keep their cached prefix. It runs hidden in the user session as the scheduled task "Local Qwen Governor" under Windows PowerShell 5.1.

## What changed since v3 (15–17 October 2026)

| Version | Change | Why |
|---|---|---|
| v4 | Null-safe sensing: an invalid counter sample keeps the last good value and is marked degraded, never acted on. Pressure must persist 60 s; refits happen at most every 15 min; nothing unloads with a request in flight. KV slot save/restore. `status.json` is written on every sample | v3's loop crashed every 16 s whenever it started with no model loaded, and single bad samples caused reload churn |
| v4.1 | Post-launch BASELINE, refit only when *other* apps grew ≥ 0.5 GiB, footprint calibration (`calib.json`), repeat-refit guard | A tight fit refitted itself every 15 min for ever |
| v4.2 | Power-plan hysteresis (`GovPowerDecide`) | 104 power-plan flips in 400 log lines |
| v4.3 | `ProcIds` and `launch.ps1` count only llama-server processes under `C:\AI\llama.cpp\` | Ollama ships its own `llama-server.exe`; an idle Ollama model was being counted as ours |
| 18 Oct defaults | MAX/BALANCED `free_margin_gib` 1.35 → **2.5**; `auto.others_vram_max_gib` 2.5 | A fit on dedicated free VRAM spilled 2.9 GiB into shared memory at a 57K window ([field report](../docs/FIELD-REPORT-20261018.md)) |

`slotlib.ps1` holds slot save/restore; `govpolicy.py` and `slotpolicy.py` mirror the pure decision functions so they can be tested with pytest.

## Tests

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File governor\test_governor.ps1   # 111 passed, 0 failed
powershell -NoProfile -ExecutionPolicy Bypass -File governor\test_ctx.ps1        # 7/7
python -m pytest governor -q                                                       # 53 passed
```

These counts come from PowerShell 7.4 and Python 3.12 on Linux, with the Windows-only reads stubbed. The tests write to a temp folder, never to the production log.

## Install or upgrade

1. Back up your current `C:\AI\governor\` folder.
2. Copy this folder over it. `profiles.json` uses the repo's model paths (`C:/AI/models/...`), so check them against your disk first.
3. Run the tests above.
4. Restart only the governor task; the model keeps running. `--slot-save-path` takes effect at the next server start.

Then check:

- `qwen status` shows a `Governor:` line and no "N s old" warning.
- `qwen log` shows `governor start ... v4` and no `loop error` lines.

**What this folder is.** This is the reference implementation with tests. The maintainer's own machine carries some extra local edits that are not published: a media-playback veto and CPU/RAM gates for MAX. So `qwen status` on that machine can show fields this copy doesn't write.
