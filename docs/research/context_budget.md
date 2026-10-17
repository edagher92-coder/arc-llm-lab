# Context feasibility (Section F) — ESTIMATES ONLY; no larger-context benchmark proposed

Calculator: `python3 tools/context_budget.py` (output in `tools/context_budget_output.json`).

## Architecture (public Qwen3.5-27B config; "Qwen3.8" assumed to share it — UNVERIFIED)
`huggingface.co/Qwen/Qwen3.5-27B/raw/main/config.json`: 64 layers, `full_attention_interval 4` → **16 full-attention layers** + 48 Gated-DeltaNet layers; 4 KV heads × head_dim 256; GDN 16 K-heads / 48 V-heads × 128.
- **f16 KV per token** = 16 × 2 (K,V) × 4 × 256 × 2 B = **65,536 B = 64.0 KiB**. The user's 64.5 KiB is within 1% (probably padding or measured from the log), and I use 64.5 conservatively. 32K → 2.02 GiB. **32K→96K adds 4.03 GiB** (confirmed).
- **Recurrent state does not grow with context, but it is multiplied by DFlash rollback snapshots.** `n_rows = mem_size × (1 + n_rs_seq)` (llama-memory-recurrent.cpp L101), with `n_rs_seq = draft n_max = 7` (common.h L399-404). Estimate: 48 × (48·128·128 + 3·10240) × 4 B × 8 ≈ **1.17 GiB**. Draft depth 5 would make it ≈0.88 GiB. Read the real value from the `RS buffer size` log line.
- q8_0 KV = 34/64 of f16 → 34.3 KiB/token. On this install **q8_0 main KV leaves the Intel Xe FA path** (`xe_fa_supported_dtype` requires F16), so FA falls to FA_SCALAR (see #30503 and coopmat_reconciliation.md). Expect both a prefill regression and quality risk. PR #29357 community data on B580 shows q8_0 KV getting little or no prefill gain (−10% to +2%).
- Draft KV q8_0: 2.1-10.6 KiB/token (1 full layer + SWA … 5 layers full context; the draft config is unverified).

## Budget (GiB), 24 total, 1.5 reserve. Rows = used / margin after reserve
| Scenario | ctx | f16 used | f16 margin | q8_0 used | q8_0 margin |
|---|---|---|---|---|---|
| best (embd on CPU, compute 0.8, display 0.75) | 32K | 21.15 | +1.35 | 20.21 | +2.29 |
| | 48K | 22.19 | +0.31 | 20.77 | +1.73 |
| | 56K | 22.71 | **−0.21** | 21.06 | +1.44 |
| | 64K | 23.23 | −0.73 | 21.34 | +1.16 |
| | 96K | 25.31 | −2.81 | 22.48 | +0.02 |
| mid (compute 1.6, display 1.5) | 32K | 22.70 | −0.20 | 21.76 | +0.74 |
| | 48K | 23.74 | −1.24 | 22.32 | +0.18 |
| | 56K | 24.26 | −1.76 | 22.61 | −0.11 |
| worst (embd on GPU, display 3.0) | 32K | 25.42 | −2.92 | 24.48 | −1.98 |

**Calibration:** 32K f16 runs healthily today, so the "worst" row is falsified, and reality sits near the best or mid row. The pack's repo claims that 64K f16 / ub256 ran, with 0.71 GiB free at ub512, and that dwm.exe uses 2.6-3.3 GB. That is unverified, and it is inconsistent with this arithmetic unless WDDM is paging. It is exactly why measured values are needed.

**Verdict:** 48K f16 is plausible but thin (≈0.3 GiB above a 1.5 GiB reserve in the best case). 56-64K f16 does not fit without freeing about 1 GiB or more. q8_0 KV would make 56-64K fit on paper, but it moves FA off the Intel path, so it is a performance and quality experiment, not a free win. **Don't equate weight-repack savings with usable context.** Usable context also needs measured prefill time, quality and governor headroom at that depth.

## Measure before deciding (read-only, from the next normal launch log)
`load_tensors: Vulkan0 model buffer size`, `CPU_Mapped model buffer size` (shows whether token_embd is on the CPU), `llama_kv_cache: size`, `llama_memory_recurrent: size … RS buffer size`, `Vulkan0 compute buffer size` (main and draft contexts), plus the Windows DXGI `QueryVideoMemoryInfo` Budget/CurrentUsage (Task Manager "Dedicated GPU memory" is an acceptable proxy) with the normal desktop open.
