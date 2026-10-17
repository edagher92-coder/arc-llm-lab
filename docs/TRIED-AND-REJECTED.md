# Tried and rejected

These ideas were already measured on the B60, or checked against the source, and didn't help. If you want to try one again, change something first. Each row says what you'd need to change. Last updated 18 October 2026.

## Measured on the card and rejected

| Idea | Result | Evidence |
|---|---|---|
| q8_0 main KV cache (`-ctk q8_0 -ctv q8_0`) | Prompt reading −53% and generation −57% at 25K tokens of context; only 0.27 GiB saved | [FIELD-REPORT-20261018](FIELD-REPORT-20261018.md#3-why-the-main-kv-cache-stays-f16) |
| q4_0 KV with the Intel FA kernel | No gain (101 vs 101 tok/s at 32K) | [TUNING-LOG](TUNING-LOG.md) row 7 |
| Larger window by lowering the free-VRAM margin (57,344 at 1.35 GiB) | Fits dedicated VRAM but spills 2.90 GiB into shared memory → 20–22 tok/s | [FIELD-REPORT-20261018](FIELD-REPORT-20261018.md#1-dedicated-free-vram-is-not-a-real-fit) |
| Removing `GGML_VK_FORCE_MMVQ=1` | 36.0 / 37.2 / 36.9 vs 38.8 / 42.7 / 43.9 tok/s (3 seeds) | maintainer battery |
| 5 draft tokens instead of 7 | 37.7 / 40.8 / 41.2 tok/s: not better | maintainer battery |
| 15 draft tokens | 27.0 tok/s; VRAM pressure | [TUNING-LOG](TUNING-LOG.md) |
| 8 CPU threads instead of 14 | 38.4 / 37.3 / 42.8 tok/s: not better (RAM cache confounds it) | maintainer battery |
| Embedded MTP drafter, n-gram stacked on DFlash2 | 32.2 tok/s, or no gain | [TUNING-LOG](TUNING-LOG.md) rows 17–19 |
| `--spec-draft-backend-sampling` | 43.95 vs 43.94 tok/s. The source shows it is a no-op for DFlash2 | battery; [research/dflash_timing_analysis.md](research/dflash_timing_analysis.md) |
| `-ub 128` / `-ub 512` to save VRAM | 18.98 / 19.50 GiB vs 19.14 GiB at 32K: not worth the speed trade | [footprint-variants-20261017.csv](../data/footprint-variants-20261017.csv) |
| Drafter on the CPU | Saves 0.15 GiB; generation 16.7 tok/s | same |
| No drafter | Saves 1.45 GiB; generation about 16 tok/s | same |
| Last two layers on the CPU (`-ot blk.(62\|63)=CPU`) | 19.53 GiB: **more** VRAM, not less | same |
| Dropping the vision projector | 0 GiB saved (it already lives CPU-side) | same |
| `--cache-reuse` | Inert on this model (multimodal) | [server-57344.log](../data/raw/server-57344.log) line 27 |
| Power-plan tuning, lower display resolution | No effect; no lower native modes on these panels | [DISPLAY-POLICY](DISPLAY-POLICY.md) |
| A strict governor gate (margin 3.0, other apps ≤ 0.75 GiB) | Pins context at 32K; MAX can never start, because the compositor alone holds 1.7–1.9 GiB | maintainer readback |

## Proposed, checked, and not adopted

An outside "optimisation pack" proposed the items below. Each was checked against the installed engine (Codex, read-only) and against the llama.cpp source (Gemini, reading only). **None of this was run on the card, and it isn't in this repo.**

| Proposal | Why not |
|---|---|
| Vulkan coopmat patch for issue #30503 (admit 8×16×16 for a 16×16×16 shader) | The patch is malformed (`git apply --check` fails) and targets a predicate that doesn't exist at b11524. The claimed fallback isn't implemented. Running an unadvertised shape is outside the Vulkan contract. And the Xe FA shaders already use 8×16×16 for f16 K/V, so it isn't on the main model's hot path ([research/coopmat_reconciliation.md](research/coopmat_reconciliation.md)) |
| "The coopmat mismatch forces DP4A on decode" | Wrong for the main model, for the same reason. Single-token decode is scalar on every vendor |
| Build script for the patch | It force-resets and cleans the source tree; never point it at a working build |
| 128-token prefill benchmark as the acceptance test | Too short, with no drafter contract, so it can't show a 40 tok/s floor |
| Launcher that picks 64K/96K from the model's file size | No measured headroom, it bypasses the governor, and it stops other apps' models |
| "Reasoning effort router" | Forces maximum effort on short histories and overrides an explicit effort from the caller |
| "0-IQ repack" of the GGUF | Neither GGUF contains IQ, Q2_K or Q3_K tensors; a repack would be a model change |
| SYCL, vLLM-XPU or EXL3 containers as the fix | A different backend, Linux/oneAPI, privileged containers and different weights: not a drop-in |
| Moving the display to the integrated GPU | The Ryzen 7 3700X has no integrated GPU |
| 96K window with f16 KV | +4 GiB of KV; doesn't fit (arithmetic and measurement) |
| B70, multi-client or prefix-cached external numbers as targets | Not comparable to single-stream decode on a B60 |
