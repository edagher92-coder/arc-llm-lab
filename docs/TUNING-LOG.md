# Tuning log: Intel Arc Pro B60 24GB + Qwen3.8-27B

Every change, in order, with the number it produced. Each **Data** entry names a file in [data/raw](../data/raw) where the raw log exists (see [data/raw/README.md](../data/raw/README.md) for what each file is). "Observed" means the figure was measured during the work, but the raw log wasn't kept. Figures marked † are observed-only: **re-run planned**.

| # | Change | Result | Data |
|---|---|---|---|
| 1 | llama.cpp b11524 Vulkan, full GPU offload, flash attention on, `GGML_VK_FORCE_MMVQ=1` | 16.0 tok/s generation (no drafter), 589 tok/s prompt | compare-f16.txt |
| 2 | SYCL backend tried | slower than Vulkan for this model, so Vulkan kept | observed |
| 3 | Speculative decoding with the DFlash2 draft model (n=5–10) | 41–44 tok/s, identical quality (7/7 coding, 3/3 tools) | tune.txt |
| 4 | Draft length sweep | n=7 and n=10 best (42.2–42.3); n=15 fell to 27 tok/s with only 0.96 GiB of VRAM free | tune.txt |
| 5 | Low-VRAM slowdown seen once (the n=15 run, 0.96 GiB free). Two other runs with 1.04 GiB (n=5) and 0.71 GiB (n=7, `-ub 512`) free did not slow down, so the threshold is **not established** and draft length is a confound | governor keeps ≥1.35–1.5 GiB free as a precaution; auto-fit off (it spilled to shared memory) | tune.txt, tune2.txt, governor.log |
| 6 | Agent loop at 30–37K context still slow: 3 turns = 201 s†, deep prompt reading about 100 tok/s†, deep generation about 11 tok/s† (stock Vulkan with the drafter, before the Intel FA build) | the bottleneck is long-context prefill | observed (raw log not retained) |
| 7 | Intel FA prefill kernel (PR #29357), portable build | no gain with q4 KV (101 vs 101 tok/s at 32K) | compare-q4.txt |
| 8 | Intel FA kernel with **f16 KV** | 420 vs 118 tok/s prompt at 32K (3.6×, compare-f16.txt); 3 agent turns **54.9 s** on the first Intel FA build (server-test.txt), against the 201 s† observed before it | compare-f16.txt, server-test.txt |
| 9 | f16 KV costs 64.5 KiB/token, so context drops to about 57–61K while the PC is in use (up to 64K after row 10) | the `big` variant kept with q4 KV for 150–200K documents | config-history/ |
| 10 | `-ub 256` + q8_0 draft KV | same speed (42.3 tok/s); free VRAM 1.04 → 1.59 GiB, so **64K context fits** | tune.txt |
| 11 | `-ub 512` + q8_0 draft KV | 3-turn 52.6 s but only 0.71 GiB free, so rejected | tune2.txt |
| 12 | Final config regression (ctx 57344, `-ub 256`, q8_0 draft KV) | 56.7 s 3-turn, 42.2 tok/s deep generation, 7/7 + 3/3. The 52.2 s run (live, 61K ctx, before the tune) is also in bench-history.csv | bench-history.csv, bench-run-64k.txt |
| 13 | Windows power plans (Saver / Balanced / Performance) | no effect on tok/s (about 40 on all), so the governor uses Saver when idle | observed |
| 14 | Context shift disabled explicitly (`--no-context-shift`; current llama.cpp also defaults to disabled) | an overflow is an explicit HTTP 400 instead of silent truncation | evalsuite/overflow_test.py |
| 15 | Agent window = server context − 8K (bug fix in `qwen window`) | agents compact before the server can overflow | governor/qwen.ps1 |
| 16 | Slot save/restore to disk (`--slot-save-path`, 43,431-token agent prompt) | cold read 107-124 s; restore 1.29 s + 19 new tokens 3.25 s = **4.5 s** (about 27x faster resume after a restart). Works with the vision projector loaded | v3 bench (2026-10-11) |
| 17 | `--spec-draft-p-min 0.5` with DFlash2 n_max 7 (3 interleaved rounds) | 42.0 -> **43.94 tok/s** (+4.6%), accept rate .627 -> .788. n_max 5 + p-min 0.5: 42.73 (accept .836). Embedded MTP n=2: 32.15 (DFlash2 is 37% faster) | v3 bench |
| 18 | `llama-bench` re-check of the baseline (f16 KV) | pp512 611 tok/s, tg 16.1 (no drafter). Depth: pp512@16K 462; tg 16.0 / 15.6 / 15.2 / 14.3 at 0 / 8K / 16K / 32K. Without cooperative matrices pp512 falls to 203 (3x). Int-dot off: no change (611). SYCL pp512 162, tg 14.6 | v3 bench |
| 19 | Long-context KV choices at 32K depth | FA off: pp 279. q8_0 KV: pp 117 (pp512 591). Only f16 KV with FA keeps the Intel prefill kernel | v3 bench |
| 20 | ThinkingCap-Qwen3.8-27B (Q4_K_M) against the base quant, 16 tasks | At `xhigh`: base 15/16, 234 s (4.1 tasks/min); ThinkingCap **16/16, 60.5 s (15.9 tasks/min), 3.9x**, with 79% less thinking text (4,513 vs 21,298 chars). At `medium`: base 15/16 80 s; ThinkingCap 16/16 74.8 s. Phone eval 10/10 | v3 bench |
| 21 | Qwen's template only accepts `reasoning_effort` of xhigh / medium / low | other values give HTTP 500; "high" maps to xhigh | v3 bench |
| 22 | Windows audit: dwm.exe VRAM with two 3440x1440 monitors | dwm holds 2.6 GB of the 24 GB. Dropping both monitors to 1920x1080 did **not** shrink it (2.6 -> 3.3 GB right after the change, 2.8 GB a minute later). See [DISPLAY-POLICY.md](DISPLAY-POLICY.md) | observed on the PC |
| 23 | Intel graphics services | Graphics Software Service 15 MB RAM, shader distributor 3 MB, PROSet monitoring small; no overlay process was running and none held VRAM. Switching them off is a tidy-up, not a speed-up | observed on the PC |
| 24 | Throughput regression, 17-18 Oct: warm 300-token check fell to 28 tok/s (47 on 15 Oct) with no config change. Checked: ECC **off**, GPU at 2400 MHz and 65 °C under load, no GPU/VRAM/fan tuning, driver unchanged, power plan High performance | a **Windows restart** (uptime was 2 d 13 h) restored it: 42.1 / 44.8 / 46.2 tok/s on the same check. Cause INFERRED: graphics memory manager state after a long uptime | observed on the PC (2026-10-18) |
| 25 | Context sweep: the exact production command line on a spare port, governor off, other apps holding 1.55-1.66 GiB of VRAM. Per size: 3 short code requests, then one request with the context 80% full (code-like filler) | 32K: 54-57 short, **48.2** deep (26K tokens, prompt 456 tok/s). 40K: 51-57 / **46.3** (32.6K, 439). 48K: 50-54 / **43.6** (39K, 421), 1.05 GiB left free. 56K: **31-33 / 22.4**, 1.9 GiB in shared memory. The cliff is between 48K and 56K: 56K would have needed to leave about 0.6 GiB free, and the driver moved about 1 GiB to system memory instead. The 0.96 GiB of "shared" seen at every size is the vision projector held in system memory (`--no-mmproj-offload`, 0.87 GiB file), not a spill | [data/ctx-sweep-20261018.jsonl](../data/ctx-sweep-20261018.jsonl), [bench/ctx-sweep.py](../bench/ctx-sweep.py) |
| 26 | Governor free-VRAM margin 2.5 -> **1.2 GiB** (MAX and BALANCED), host-RAM prompt cache `-cram` 2048 (MAX) / 4096 (BALANCED) -> **6144 MiB** for both, so a 40K agent prompt (about 2.5 GiB of KV) fits in the cache when two agents take turns on the one slot | the governor now loads **45,056** with other apps at 1.64 GiB (1.35 GiB left free), 49,152 when the desktop is light, and steps down when other apps grow. Warm check after the change: 45.1 / 50.1 / 47.2 tok/s | governor.log (2026-10-18 04:04) |
| 27 | Codex wrapper: client cap 32,768 -> 65,536 and compaction at 90% of the window (was 85%) | Codex now gets the server's real window minus 8K (36,864 at a 45,056 load) and compacts at about 33K instead of 27.8K | [agents/codex-qwen.cmd](../agents/codex-qwen.cmd) |
| 28 | Codex harness: lean `CODEX_HOME` + compact instructions + engine lock, evalsuite 19 tasks | old home 13/19 -> lean 15/19, 49% faster on tasks both passed (930 -> 477 s), server prompt tokens -85%; after fixes 18/19 in 711 s for all 19 (old 2,140 s) | data/codex-eval-20261018 |
| 29 | Codex Windows sandbox and `.git` | `.git` is read-only under workspace-write; `-c sandbox_workspace_write.writable_roots=[...]` is ignored at root level with `exec -s` and works after `exec` (branch test: denied vs created) | docs/CODEX-QWEN.md |
| 30 | Baseline re-measure, f16 KV, ctx 32768, 3-seed contract | 38.95 / 43.01 / 44.16 tok/s (mean 42.04), 127 ms/round, accept .62-.71; pp 471 (2,076 tok) / 520 (8,199 tok); dedicated 20.08 GiB, shared 0.75 (vision projector), free 1.73 | bench/ab-20261018/A0 |
| 31 | q8_0 main KV with DFlash2, ctx 32768 | 34.34 / 33.62 / 37.52 (mean 35.16, -16%), 141 ms/round; pp 433 / 381 (-27% at 8K); saves 0.94 GiB. Rejected (again); 48K/56K not run | bench/ab-20261018/A1 |
| 32 | DFlash round attribution with GGML_VK_PERF_LOGGER (seed 4242) | GPU 125.2 ms/round vs wall 128.3: host gap ~3 ms. Verify graph 101.2 ms (n=8 mat-vec q4_K/q6_K ~160 GB/s, ~35% of peak), draft 17.6 ms (its q6_K lm_head 6.1 ms), inject 0.9 ms | bench/ab-20261018/B1-perflog-summary.txt |
| 33 | SYCL fork (valarauca `feature/intel`) source audit | fast prefill targets Q4_0/Q8_0; Q4_K/Q6_K ~20% faster matmul only; DFlash2 in its base; not built (2x gate not expected to pass for Q4_K_M) | CHANGELOG |
| 34 | Mat-vec rows per workgroup on Intel (`rm_kq_int` 1 -> 2, patch 0004), test-backend-ops perf m=4096 k=14336 n=8 | q4_K 178.6 -> 133.8 us, q6_K 288 -> 253 us; 3 rows not better, 8 much worse; a large workgroup for Q6_K was faster again (237 us) but changed one greedy output, so rejected. End to end, warm, 3 seeds, ctx 32768: 39.11 / 43.19 / 44.06 (mean 42.12, 127 ms/round) -> **47.16 / 52.57 / 53.92 (mean 51.22, 104 ms/round)**, same draft acceptance, identical greedy hashes, pp unchanged (500 / 520). test-backend-ops 695/695 | bench/ab-20261018/W0, W2, mmv-sweep.txt |
| 35 | Soak of the baked engine, then promotion (new folder `vulkan-intelfa-kq2-20261018`, one-line `exe` change in the governor, old engine kept) | 51.19 / 51.22 / 51.09 tok/s over three cycles, greedy identical, GPU 64-65 C at stock clocks | bench/ab-20261018/S1-S3, soak-kq2.log |
| 36 | **VRAM spill found and fixed.** With other apps holding ~2.1 GiB, the row-26 margin (1.2 GiB) loaded 49,152 and production ran 26-30 tok/s. Bench, same engine: 32K 51 tok/s, llama shared 0.75 GiB; 40K and 49K **26.4 tok/s, 189 ms/round, shared 1.69 GiB**, dedicated *lower* than at 32K. Windows moves a ~0.94 GiB block off the card once the adapter passes about 22.6 GiB (free < ~1.3 of 23.88); thread count is not a factor (32K at -t 14: 47.15 run 1, same as -t 8). The governor counted dedicated memory only, so a spilled server looked like a perfect fit and the calibration fell from 0.94 to 0.08 GiB, growing the next context further. Row 24 (28 tok/s until a restart) fits the same mechanism (INFERRED) | margin 1.2 -> **1.45**, pressure threshold 1.1 -> 1.3, calibration counts llama shared usage above 0.8 GiB, a spill queues one idle-time re-fit (live governor v4 only; the governor copy in this repo is older). Production after: **47.83 / 53.11 / 54.41 (mean 51.78), 98 ms/round** at 32K, greedy identical | bench/ab-20261018/P1-P3, ctx-probe.log, prod-kq2*.sustained.json |

## Settings that matter (final)

The launch command the governor builds for the default variant ([governor/launch.ps1](../governor/launch.ps1) and [governor/profiles.json](../governor/profiles.json)), with the values that depend on the profile shown as alternatives:

```
GGML_VK_FORCE_MMVQ=1
llama-server -m Qwen3.8-27B-UD-Q4_K_M.gguf --mmproj mmproj-F16.gguf --no-mmproj-offload -a qwen3.8-27b
  --host 127.0.0.1 --port 10001
  -c <sized at each load, 32768 to 65536> -ctk f16 -ctv f16
  -t <8 BALANCED | 14 MAX | 4 LEAN>  -tb <same as -t>  -cram <6144 BALANCED | 6144 MAX | 1024 LEAN>
  --prio <-1 BELOW-NORMAL | 0 NORMAL>
  -ngl 99 -fa on -lm dio -np 1 -fit off --jinja --chat-template-file qwen38-template.jinja
  --cache-reuse 256 --metrics --no-context-shift
  --reasoning-budget 4096 --reasoning-budget-message "Thinking budget reached. Give the final answer now."
  -ngld 99 -md Qwen3.8-27B-DFlash2-Q4_K_M.gguf --spec-type draft-dflash --spec-draft-n-max 7
  -ub 256 -ctkd q8_0 -ctvd q8_0
```

| Flag | Why it is there |
|---|---|
| `-ngl 99 -fa on` | Everything on the GPU, flash attention on (the Intel FA kernel needs it) |
| `-ctk f16 -ctv f16` | The only KV type the Intel FA prefill kernel accelerated in our tests |
| `-md ... --spec-type draft-dflash --spec-draft-n-max 7 -ngld 99` | The DFlash2 drafter, 7 tokens per round; the biggest generation win |
| `-ub 256 -ctkd q8_0 -ctvd q8_0` | Frees about 0.55 GiB at no speed cost, which is what makes 64K fit |
| `--mmproj ... --no-mmproj-offload` | Vision projector stays in system memory so it doesn't take VRAM |
| `-fit off` | llama.cpp's auto-fit is off; on Windows it quietly spilled into shared memory |
| `-lm dio` | Load the model with direct I/O |
| `-t`, `-tb`, `-cram`, `--prio` | Per-profile CPU threads, host-RAM prompt cache size (MiB) and process priority |
| `--chat-template-file qwen38-template.jinja` | The chat template shipped in [governor/](../governor/qwen38-template.jinja) |
| `--no-context-shift` | Overflow is an explicit error, never silent truncation |
| `--reasoning-budget 4096` | Stops runaway thinking with "Give the final answer now" |
| `--metrics` | Prometheus counters at `/metrics` ([TOKEN-EFFICIENCY.md](TOKEN-EFFICIENCY.md)) |
| `-np 1` | One slot: the whole context and drafter budget go to one conversation |

**`--cache-reuse 256` is inert on this model.** The server logs `cache_reuse is not supported by multimodal, it will be disabled` at start-up ([data/raw/server-57344.log](../data/raw/server-57344.log), line 27), because the model loads a vision projector and has recurrent layers. The governor still passes it; it does nothing and is harmless. Prefix reuse comes from the host-RAM prompt cache (`-cram`) and context checkpoints (defaults: 32 checkpoints, at least 8192 tokens apart).

**The first row of [tune.txt](../data/raw/tune.txt) is not a valid measurement.** The line `n7 ub512 (current)` (20.5 tok/s) shows 15.49 GiB already in use before the test server started and only 7.37 GiB attributed to it. The most likely cause (INFERRED) is that the live model was still loaded, so the test model did not get the whole card. It is left in the raw file unedited and excluded from [the sweep](../data/speculative-decoding-sweep.csv). The other five rows were measured with the card free.

## What didn't help

- **More draft tokens (n=15):** too much VRAM pressure (upstream's DFlash example uses 15 on a smaller model).
- **The Intel FA kernel with a q4 KV cache:** no gain.
- **Power-plan tuning:** no effect on speed.
- **Lowering the display resolution to free the compositor's VRAM:** measured, no saving ([DISPLAY-POLICY.md](DISPLAY-POLICY.md)).
- **Embedded MTP, n-gram stacking on top of DFlash2, int-dot, q8_0 KV and FA off:** all slower or no change (rows 17-19).
- **SYCL:** slower than Vulkan here in our observation; the raw log wasn't kept, so please [submit a comparison](GOOD-FIRST-ISSUES.md).
- **Chasing 55 tok/s average (superseded by row 34):** this used to say bandwidth was the cap; the verify mat-vec was running at about 35% of peak and two rows per workgroup lifted the mean to 51-52 tok/s. The original note: the B60's memory bandwidth caps a 27B dense model at about 42–45 tok/s average (56–60 peak on code), so the effort went into reliability instead.
