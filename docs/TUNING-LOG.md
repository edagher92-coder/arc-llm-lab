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

## Settings that matter (final)

The launch command the governor builds for the default variant ([governor/launch.ps1](../governor/launch.ps1) and [governor/profiles.json](../governor/profiles.json)), with the values that depend on the profile shown as alternatives:

```
GGML_VK_FORCE_MMVQ=1
llama-server -m Qwen3.8-27B-UD-Q4_K_M.gguf --mmproj mmproj-F16.gguf --no-mmproj-offload -a qwen3.8-27b
  --host 127.0.0.1 --port 10001
  -c <sized at each load, 32768 to 65536> -ctk f16 -ctv f16
  -t <8 BALANCED | 14 MAX | 4 LEAN>  -tb <same as -t>  -cram <4096 BALANCED | 8192 MAX | 1024 LEAN>
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
- **SYCL:** slower than Vulkan here in our observation; the raw log wasn't kept, so please [submit a comparison](GOOD-FIRST-ISSUES.md).
- **Chasing 55 tok/s average:** the B60's memory bandwidth caps a 27B dense model at about 42–45 tok/s average (56–60 peak on code), so the effort went into reliability instead.
