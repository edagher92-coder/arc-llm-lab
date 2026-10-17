# DFlash timing analysis (Section D)

Reproduce with `python3 tools/dflash_timing.py` (output: `tools/dflash_timing_output.json`). Every input is a user-reported number or a public spec. No new measurements.

## 1. Arithmetic from the traced run
| Quantity | Value | Note |
|---|---|---|
| native t/s | 2303/60.898 = **37.817** | Matches the reported 37.8176 only if the first token (from prefill) is excluded. 2304/60.898 = 37.834 |
| tokens / verification round | 2304/458 = **5.03** | |
| drafted / round | 2576/458 = 5.62 | p-min 0.5 truncates below n_max=7 |
| accepted / round | 1789/458 = 3.91 | acceptance 1789/2576 = **69.4%** |
| tokens explained by rounds (accepted + 1 bonus each) | 2247 | **56-57 tokens unexplained**. Likely empty-draft single-token steps (not counted as verification rounds) plus the first token. Needs a counter |
| ms / round | **132.97** | |
| draft timer / round | **20.82 ms** (15.7% of gen time) | Excludes readback/injection, per the user |
| remainder / round | **112.15 ms** | Target verify + readback + concat + inject + sync + lattice readback + selector + server overhead. **Cannot be split without instrumentation** |
| wall − native | 0.866 s | ≈ first-content latency 0.864 s, i.e. prompt processing + first token |

### Bandwidth bound (EXTRAPOLATION)
B60 = **456 GB/s** (Intel ARK, SKU 243916). One target forward has to read every VRAM-resident weight at least once:
- whole file 17.44 GB → 38.3 ms, so **≤26.1 forwards/s**
- with token_embd kept on the CPU (llama.cpp default for the input layer; embedding type unverified) → 36.0-36.7 ms, so ≤27.3-27.8 forwards/s

So non-speculative decode is bounded at ~26-28 t/s at 100% bandwidth efficiency. Real kernels reach 60-85%, which gives roughly 16-23 t/s. The ~38-44 t/s seen is only possible because of speculation (5.03 tokens per target forward).

A verify of 6.6 tokens costs ≥ the single-token floor. On Intel the mat-vec path stays bandwidth-bound up to `mul_mat_vec_max_cols = 8` (ggml-vulkan-types.h L383), so verify cost should be close to, but above, ~36-38 ms. That leaves **at most ~74 ms per round not explained by the weight-read floor plus the draft timer**. The "ideal" round (verify at floor + draft) is 59 ms, which would give ~85 t/s at the current 5.03 tokens/round. **This is a ceiling, not a forecast.**

### What 40/50 t/s requires on this contract
| Target | Round time needed at 5.03 tok/round | Or tokens/round needed at 133 ms |
|---|---|---|
| 40 | ≤125.8 ms (−7.2 ms, −5.4%) | ≥5.32 |
| 45 | ≤111.8 ms | ≥5.98 |
| 50 | ≤100.6 ms (−32.4 ms, −24%) | ≥6.65 (close to the n_max=7 cap of 8, not realistic at 69% acceptance) |

**Implication:** 50 t/s has to come mostly from cutting per-round overhead, not from acceptance. The original runs (38.79 / 42.71 / 43.91, mean 41.8, sd 2.7) already straddle 40. Seed-to-seed variance is about the size of the gap, so any acceptance test must report tokens/round and ms/round per run (see acceptance_test_spec.md).

## 2. What the code does each round (reconstructed revision; common/speculative.cpp is unchanged from b11524)
1. **Target verify decode** of `[id_last, draft...]`. llama-context `extract_layer_inputs` (L2294-2325) issues `ggml_backend_tensor_get_async` for **each extracted target layer input** (`[TAG_EXTRACT_TARGET_EMBEDDINGS]`, L2028). That is a GPU→host copy of n_extract × 5120 × f32 per token.
2. **Readback sync:** `llama_get_embeddings_layer_inp()` calls `ctx->synchronize()` (llama-context.cpp ~L4176) and then `output_reorder()`. This is a full CPU wait for the target graph to finish.
3. **CPU concatenation:** `common_speculative_impl_draft_dflash::process` L1206-1222 does a per-token, per-layer `memcpy` into `features_buf` (n_chunk × n_extract·5120 floats).
4. **Injection:** `batch_inject.add_embd` and then `llama_process(ctx_dft, DECODE, batch_inject)` (L1230). This is a **separate draft-graph run** that uploads the features host→device and writes the draft K/V. It is called from the server via `common_speculative_process(spec, batch.view)` (server-context.cpp L4232), on **all tokens of the verify batch, including drafted tokens that are about to be rejected**. Upstream marks this redundancy as `TODO [TAG_SPEC_AVOID_DRAFT_REEVAL]` (L3415, L4226). The rejected positions are removed by `llama_memory_seq_rm(ctx_dft, ..., ckpt.pos_max+1, -1)` (L3420-3424) before the next draft.
5. **Draft decode:** one batch of `n_max+1` tokens `[id_last, <mask>×n_max]` (L1264-1277).
6. **DFlash2 selection:** `llama_get_embeddings_nextn(ctx_dft)` (L1297, another readback + sync), then a **CPU** argmax over `selector_top_k` per position, plus the p-min softmax check (L1300-1318). There is no vocabulary sampling.
7. **Target rollback:** for the hybrid Qwen3.5-style target, `n_rs_seq = n_max` (common.h L399-404). Recurrent-state snapshots stay on device, so no host checkpoint is needed when `draft.size() ≤ n_rs_seq` (server-context.cpp L3429-3440).

### Important source facts
- **`--spec-draft-backend-sampling` is a no-op for DFlash2.** The constructor only installs backend samplers when `backend_sampling && !is_dflash2` (L1101). That explains why the "GPU/backend sampling" battery result (43.95 vs 43.94) did not move. The pack's Task 3 / launcher flag cannot help this draft.
- **Feature traffic is small per round but large per prompt** (`feature_traffic()` in the script; n_extract is 5 or 8 depending on the draft, unverified for Qwen3.8-DFlash2). Per round: 0.65-1.04 MiB each way, 0.05-0.11 ms of transfer at a practical 10-14 GB/s on PCIe 4.0 x8 (3700X platform). So per-round cost comes from **sync/latency, not bytes**. Per prefill: a 32K-token prompt implies 3.1-5.0 GiB each way (≈0.24-0.54 s each way), plus a draft inject pass over every prompt token. **That is relevant to time to first useful output in agentic turns with big contexts.**
- **FORCE_MMVQ:** with the default policy `n>1` already selects MMVQ (`ggml_vk_should_use_mmvq` L6604). `GGML_VK_FORCE_MMVQ=1` therefore only changes **n==1** mat-vec calls on the Intel Windows driver (L6620-6632 returns false for non-Q2/Q3/Q6 types). The measured ~5 t/s loss when it was removed means n==1 matmuls are material inside the loop. Which nodes those are is **unverified**. Candidates: the empty-draft steps (the 56 unexplained tokens) and DFlash2 conv/selector nodes. The per-op profile in the next experiment answers this.

## 3. Measured vs needs instrumentation
| Component | Status |
|---|---|
| Draft decode (step 5) + selector (6) | Partly measured by the existing draft timer (20.8 ms/round). Whether inject (4) is inside it is unclear; the user says the readback/injection path is excluded |
| Target verify GPU time (1) | **Not isolated** |
| Readback sync wait (2) | **Not measured** |
| CPU concat (3) | **Not measured** (expected well under 1 ms) |
| Inject decode (4) incl. upload + redundant rejected positions | **Not measured** |
| Lattice readback + sync (6) | **Not measured** |
| Empty-draft / single-token steps | **Not counted** |
| Per-op GPU time (which FA path, which matmuls have n==1) | Available today with no code change: `GGML_VK_PERF_LOGGER=1` (+ `GGML_VK_PERF_LOGGER_FREQUENCY`). This serialises submissions, so use it as a diagnostic, not for throughput numbers |

See `instrumentation_patch_UNTESTED.diff` for timers around steps 1-6.
