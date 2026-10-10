# Tuning log: Intel Arc Pro B60 24GB + Qwen3.8-27B

Every change, in order, with the number it produced. Each **Data** entry names a file in [data/raw](../data/raw) where the raw log exists. "Observed" means the figure was measured during the work, but the raw log wasn't kept.

| # | Change | Result | Data |
|---|---|---|---|
| 1 | llama.cpp b11524 Vulkan, full GPU offload, flash attention on, `GGML_VK_FORCE_MMVQ=1` | 16.0 tok/s generation (no drafter), 589 tok/s prompt | compare-f16.txt |
| 2 | SYCL backend tried | slower than Vulkan for this model, so Vulkan kept | observed |
| 3 | Speculative decoding with the DFlash2 draft model (n=5–10) | 41–44 tok/s, identical quality (7/7 coding, 3/3 tools) | tune.txt |
| 4 | Draft length sweep | n=7 and n=10 best (42.2–42.3); n=15 collapses to 27 tok/s because VRAM fell to 0.96 GiB free | tune.txt |
| 5 | VRAM cliff found: below about 1.1 GiB free, generation collapses | governor keeps ≥1.35–1.5 GiB free; auto-fit off (it spilled to shared memory) | tune.txt, governor.log |
| 6 | Agent loop at 30–37K context still slow: 3 turns = 201 s, deep prompt reading about 100 tok/s, deep generation about 11 tok/s | the bottleneck is long-context prefill | observed |
| 7 | Intel FA prefill kernel (PR #29357), portable build | no gain with q4 KV (101 vs 101 tok/s at 32K) | compare-q4.txt |
| 8 | Intel FA kernel with **f16 KV** | 420 vs 118 tok/s prompt at 32K (3.6×); 3 agent turns **201 → 54.9 s** | compare-f16.txt, server-test.txt |
| 9 | f16 KV costs 64.5 KiB/token, so context drops to about 57–61K | the `big` variant kept with q4 KV for 150–200K documents | config-history/ |
| 10 | `-ub 256` + q8_0 draft KV | same speed (42.3 tok/s); free VRAM 1.04 → 1.59 GiB, so **64K context fits** | tune.txt |
| 11 | `-ub 512` + q8_0 draft KV | 3-turn 52.6 s but only 0.71 GiB free, so rejected | tune2.txt |
| 12 | Final config regression | 56.7 s 3-turn, 42.2 tok/s deep generation, 7/7 + 3/3 | bench-history.csv, bench-run-64k.txt |
| 13 | Windows power plans (Saver / Balanced / Performance) | no effect on tok/s (about 40 on all), so the governor uses Saver when idle | observed |
| 14 | Context shift disabled (`--no-context-shift`) | an overflow is now an explicit HTTP 400 instead of silent truncation | evalsuite/overflow_test.py |
| 15 | Agent window = server context − 8K (bug fix in `qwen window`) | agents compact before the server can overflow | governor/qwen.ps1 |

## Settings that matter (final)

```
llama-server -m Qwen3.8-27B-UD-Q4_K_M.gguf -ngl 99 -fa on -c <auto, up to 65536> -ctk f16 -ctv f16
  -md Qwen3.8-27B-DFlash2-Q4_K_M.gguf -ngld 99 --spec-type draft-dflash --spec-draft-n-max 7
  -ctkd q8_0 -ctvd q8_0 -ub 256 -np 1 --cache-reuse 256 --jinja --no-context-shift -fit off
  --reasoning-budget 4096   (env: GGML_VK_FORCE_MMVQ=1)
```

The full launch logic is in [governor/launch.ps1](../governor/launch.ps1) and the variants are in [governor/profiles.json](../governor/profiles.json).

## What didn't help

- **More draft tokens (n=15):** too much VRAM pressure.
- **The Intel FA kernel with a q4 KV cache:** no gain.
- **Power-plan tuning:** no effect on speed.
- **SYCL:** slower than Vulkan here.
- **Chasing 55 tok/s average:** the B60's memory bandwidth caps a 27B dense model at about 42–45 tok/s average (56–60 peak on code), so the effort went into reliability instead.
