# Field report, 18 October 2026: the real VRAM budget, an open regression, and why the KV cache stays f16

A dated maintainer report from one Windows 11 workstation (Intel Arc Pro B60 24 GB, Ryzen 7 3700X, 32 GB RAM, two 3440×1440 displays). It runs ThinkingCap-Qwen3.8-27B Q4_K_M with the DFlash2 drafter on llama.cpp b11526, the Intel FA build. This report doesn't replace the benchmark headlines in the [README](../README.md). It records what changed in our understanding between 15 and 18 October and which settings that moved.

**How to read the labels.** **Measured** means a number read from the machine, a log or a request capture. **Inferred** means it was derived from measured numbers. **Researched** means it comes from source reading or arithmetic, with nothing run on the card ([docs/research/](research/README.md)). Single runs unless stated.

## Summary

1. **Context is capped by a per-process WDDM budget, not by the adapter's free VRAM.** At a 57,344-token window, llama-server put 2.90 GiB in *shared* (system) memory and decode fell to 20–22 tok/s. That happened even though the adapter still reported about 1.2 GiB free. (Measured.)
2. **Decode on this box is slower than it was on 15–16 October, and the cause isn't known yet.** Warm decode is 28 tok/s at a 36,864-token window today, against 43–48 on 15–16 October. `llama-bench tg32` without the drafter is 19% lower on the same command. (Measured; cause open.)
3. **A q8_0 main KV cache is rejected.** At 25K tokens of context it halves prompt reading (428 → 199 tok/s) and cuts generation by 57% (25.5 → 10.9 tok/s). It saves only 0.27 GiB. (Measured.)
4. **Published governor defaults changed** to a 2.5 GiB free margin for the MAX and BALANCED profiles. The governor is now v4.3 ([governor/README.md](../governor/README.md)).

## 1. Dedicated free VRAM is not a real fit

The governor sizes context as weights + drafter + context × 64.5 KiB per token, against the adapter's *dedicated* free memory minus a margin. On 18 October the fit looked fine and the results did not:

| When | Window | Margin | llama-server dedicated | llama-server **shared** | Other apps | Warm decode |
|---|---:|---:|---:|---:|---:|---:|
| 16 Oct 00:03 | 40,960 | 1.35 GiB | not recorded | not recorded | — | 48 tok/s |
| 18 Oct 00:03 | 57,344 | 1.35 GiB | 19.70 GiB | **2.90 GiB** | 1.74 GiB | 20.0–22.3 tok/s |
| 18 Oct 00:07 | 36,864 | **2.5 GiB** | 20.10 GiB | 1.23 GiB | 1.80 GiB | 26.7–28.3 tok/s |

Data: [context-spill-20261018.csv](../data/context-spill-20261018.csv). The governor log and the counter readback for these three rows were not published.

**What this means (inferred).** Windows gives each process a dedicated-memory budget below the adapter total. Allocations beyond that budget go to shared, system-backed memory over PCIe. Anything the model touches there runs at PCIe speed instead of the card's 456 GB/s. Adapter-wide "free VRAM" can't see that happening. The "cliff at about 1.1 GiB free" in the [tuning log](TUNING-LOG.md) was probably this same effect, seen from outside.

**The 17 October footprint sweep supports this (inferred, not isolated).** Every variant at a 32,768-token window was measured with both counters ([footprint-variants-20261017.csv](../data/footprint-variants-20261017.csv), raw [run.log](../data/raw/ctxlab-20261017/run.log)). The fastest short-request run, 46.1 tok/s, was the one with the least shared memory (0.75 GiB). Production settings had 1.68 GiB shared and ran at 29.9 tok/s. Other things changed between those rows too, so treat this as a lead, not proof.

**Check it on your own card** (Windows PowerShell 5.1). Run it while llama-server is loaded; a tok/s figure without both numbers isn't a result:

```powershell
$p = Get-Process llama-server | ? { $_.Path -like 'C:\AI\llama.cpp\*' }
(Get-Counter '\GPU Process Memory(*)\Dedicated Usage','\GPU Process Memory(*)\Shared Usage').CounterSamples |
  ? { $_.InstanceName -like "pid_$($p.Id)_*" } | select Path,@{n='GiB';e={[math]::Round($_.CookedValue/1GB,2)}}
```

**Practical ceiling on this desktop.** Until the per-process budget is mapped (step E0 in the [roadmap](ROADMAP.md)), treat **about 36–40K tokens with an f16 KV** as the safe window. The 12 October 64K result in the README was real, but shared usage wasn't being recorded then. Larger windows are being re-qualified, not withdrawn.

## 2. An open throughput regression

| Date | Test | Result |
|---|---|---|
| 12 Oct | `llama-bench tg32`, depth 0, no drafter | 16.0–16.1 tok/s ([TUNING-LOG](TUNING-LOG.md) row 1) |
| 15–16 Oct | warm 300-token request, window 40,960 | 43–48 tok/s |
| 17 Oct 16:08 | same `tg32` command | **13.0 tok/s** (−19%) ([kv-batch1.md](../data/raw/ctxlab-20261017/kv-batch1.md)) |
| 18 Oct 00:07 | warm 300-token request, window 36,864 | **28 tok/s** |

The `llama-bench` drop came before any governor or profile change that week, so the governor didn't cause it.

**Already ruled out (measured):** GPU contention (no other process above 1%), a driver change (still 32.0.101.8976), configuration changes, the power plan, the ECC registry value, and WHEA or display-driver events.

**Not yet ruled out:** the ECC toggle in Intel Graphics Software (the 12 October slowdown had the same signature and went away with ECC off), the clock or thermal state after 2.5 days of uptime, a reboot, and whether the shared-memory spill alone explains the gap. The cheap checks are listed first in the [roadmap](ROADMAP.md#e0-real-vram-budget-and-the-regression).

## 3. Why the main KV cache stays f16

The Intel Xe flash-attention shaders only take f16 K and V. With q8_0 the engine falls back to a scalar path, and the cost grows with context. Measured on 17 October, all from the same build:

| Tool | KV | Context | Prompt tok/s | Generation tok/s |
|---|---|---:|---:|---:|
| llama-bench (no drafter) | f16 | 0 / 16K / 32K | 485 / 379 / 354 | 13.0 / 14.4 / 12.7 |
| llama-bench (no drafter) | q8_0 | 0 / 16K / 32K | 588 / 198 / 123 | 15.7 / 11.5 / 9.5 |
| llama-server + DFlash2, window 40,960 | f16 | 3.9K / 25K | 473 / **428** | 30.9 / **25.5** |
| llama-server + DFlash2, window 40,960 | q8_0 | 3.9K / 25K | 413 / **199** | 33.8 / **10.9** |

Data: [kv-cache-depth-20261017.csv](../data/kv-cache-depth-20261017.csv); raw [server-depth-f16.log](../data/raw/ctxlab-20261017/server-depth-f16.log), [server-depth-q8_0.log](../data/raw/ctxlab-20261017/server-depth-q8_0.log). q8_0 wins on empty prompts and loses badly once a coding agent's 20–40K-token conversation is in the window. Measured at a 40,960-token window, it saved 0.27 GiB (19.65 → 19.38 GiB).

The only honest route to a smaller KV cache is engine work, not a flag: a valid 8×16×16 path for quantised K/V, or dequantising to f16 onto the existing Xe shaders. That is researched but untested, in [research/coopmat_reconciliation.md](research/coopmat_reconciliation.md).

## 4. What changed in this repo

- [governor/](../governor/) is now **v4.3**. It has null-safe sensing, pressure hysteresis, no unload while a request is in flight, KV slot save/restore, power-plan hysteresis, footprint calibration, and a process-path filter so Ollama's bundled `llama-server.exe` is never counted as the model. Tests: `test_governor.ps1` 111/0, pytest 53/0, `test_ctx.ps1` 11/11.
- `governor/profiles.json`: the MAX and BALANCED `free_margin_gib` is **2.5** (was 1.35), and `auto.others_vram_max_gib` is 2.5.
- [agents/codex-lean/](../agents/codex-lean/README.md): an opt-in Codex home that cuts Codex's start-up prompt from 12,235 to 3,010 tokens (measured). The first cold turn went from 33 s to 8 s.
- [CODEX-COMPAT.md](CODEX-COMPAT.md): which OpenAI request features this llama-server honours, ignores or drops, from 22 request shapes against the live server.
- [TRIED-AND-REJECTED.md](TRIED-AND-REJECTED.md) and [ROADMAP.md](ROADMAP.md): what not to re-run, and the next experiments with pass/fail criteria.
- [research/](research/README.md): a source-level study of the engine (DFlash per-round timing, the coopmat question, the context budget), clearly marked as not run on the card.

## Evidence boundary

The three 16–18 October rows in section 1 and the warm-decode figures in section 2 come from the maintainer's governor log and counter readback, which are not published. Everything in section 3 and the footprint sweep has raw files in [data/raw/ctxlab-20261017/](../data/raw/ctxlab-20261017/README.md).
