# B60 Qwen research report: evidence-backed next steps
*Prepared 2026-10-17 (AEDT, UTC+11). Box-only analysis; nothing was run on the user's machine. All proposed code is UNTESTED unless stated.*

## 1. Verdict
- **Revision:** `c85e6c598f…` is **not a public commit**. According to the pack's own plan it is b11524 (`86a283532`) plus open PR #29357 (`61cc4c2`, `1a5137a`). I reconstructed that tree and all citations use it (approximate line numbers).
- **Coopmat:** on this install the main model's f16-KV attention (prefill **and** DFlash verification) already runs on PR #29357's / #24406's Intel Xe FA shaders. Those use **8x16x16, the shape the driver advertises**, with subgroup size pinned to 16. Issue #30503's gate only affects FA whose K/V is not f16. Here that means the **q8_0 DFlash draft context**, or a future q8_0 main KV. The pack's bypass is malformed. It would also run an *un-advertised* 16x16x16 shader, which is outside the Vulkan contract, and ggml has **no** fallback when pipeline creation fails: it rethrows lazily, mid-request. **Don't apply it. It isn't the decode bottleneck.**
- **Decode:** the target's weight-read floor is ~36-38 ms per forward (456 GB/s). A round takes 133 ms for 5.03 tokens, and the draft timer covers 20.8 ms of that. Up to ~74 ms per round is unexplained by "verify at bandwidth floor + draft", but it sits in uninstrumented buckets: verify inefficiency, feature readback + `synchronize`, inject decode (which includes positions that are about to be rejected, an upstream TODO), lattice readback, n==1 matmuls, and empty-draft steps. **40 t/s needs only −7 ms per round. 50 t/s needs −32 ms per round.** That is plausible only if instrumentation finds a removable sync/inject cost. I can't promise either number.
- **Already explained:** `--spec-draft-backend-sampling` is a **no-op for DFlash2** (speculative.cpp L1101), which is why "GPU sampling 43.95 ≈ 43.94". FORCE_MMVQ only changes n==1 mat-vec decisions, so its ~5 t/s effect shows that n==1 work matters inside the loop.
- **Completed coding tasks:** the largest *certain* lever is visible latency. The MCP helper buffers whole responses, and reasoning-policy errors (xhigh on omitted effort) inflate total time. Both can be fixed without touching the engine.
- **Context:** f16 KV is 64 KiB/token (verified from the public config). DFlash rollback multiplies the recurrent state ×8 (≈1.17 GiB, estimated). 48K f16 is thin but plausible. 56-64K f16 doesn't fit with a 1.5 GiB reserve. q8_0 KV fits on paper but leaves the Intel FA path.

## 2. Ranked interventions (max three)
| Rank | Intervention | Bottleneck hypothesis | Affects | Compatibility | Risks | Smallest falsification test | Rollback | Already tested? |
|---|---|---|---|---|---|---|---|---|
| **1** | **Visible-latency + reasoning-policy fix in the gateway/MCP helper** (stream to the agent; canonical resolver, `tools/reasoning_resolver_UNTESTED.py`) | Total task time is dominated by buffered delivery and unnecessary thinking (xhigh on omitted effort; top-level effort clobbering nested), not by engine t/s | Visible latency, total task time, KV use | Gateway-only. The engine, governor and weights are untouched. Server precedence was read from source (server-common.cpp L1399-1465) | Template mis-rendering if effort names differ (verify the ThinkingCap template). Streaming partial tool calls needs a robust parser | Integration rows of the 22-shape matrix against the live server. A/B the 12+ task suite on `t_first_visible_mcp` and `t_task_total` (acceptance_test_spec §B) | Feature flag back to the current helper/router | **No.** The unit tests (27/27) pass on the box only |
| **2** | **Instrument, then attack the DFlash per-round overhead** (`instrumentation_patch_UNTESTED.diff` + `GGML_VK_PERF_LOGGER`), then the targeted fix (likely candidates: skip inject for to-be-rejected positions per TAG_SPEC_AVOID_DRAFT_REEVAL; merge inject + draft into one draft graph; remove a redundant `synchronize`) | Most of the 112 ms remainder is sync/serialisation and redundant draft work, not weight bandwidth (floor ~36-38 ms) | Decode/speculation, also prefill TTFT (feature readback of 3-5 GiB for a 32K prompt) | Scratch build of the same reconstructed source. Production engine unchanged | Spec decoding stays lossless under greedy verify. Bugs show up as token diffs, so the greedy-identical gate is required | One attributed profile run (not a throughput claim). Then a single change, A/B on the fixed sustained contract | Keep the production binary. The scratch build lives in a separate directory | **No.** Draft5 and MTP changed acceptance, not overhead. This is a new variable |
| **3** | **Valid 8x16x16 cm1 FA (or q8_0→f16 dequant onto the Xe FA path) for the q8_0 draft KV** | Draft-context attention runs FA_SCALAR (shape_ok=false) inside the 20.8 ms draft time | Speculation (draft time); later q8_0 main KV for 50-60K | Requires shader template changes (coopmat_reconciliation §4). No gate bypass | Shader correctness. Draft-quality drift (acceptance) | First: is scalar FA in the draft graph >10% of draft time in the PERF_LOGGER output? If not, drop this | Revert the build | No. Ranked 3rd because the expected gain is bounded by ≤20.8 ms/round |

Rejected or non-ranked: the pack's #30503 patch (invalid); GGUF repack (not lossless, no IQ tensors); SYCL/containers (separate security review; production-engine replacement); clock/voltage; iGPU display move (impossible on a 3700X); `--spec-draft-backend-sampling` (no-op for DFlash2); repeating MMVQ-off / 8-worker / draft5 / MTP (no new variable).

## 3. Single best next experiment
**Attribution profile of the existing build. No code change, no engine replacement.**
1. Launch exactly as production (MAX14, draft7, p-min 0.5, FORCE_MMVQ=1, 32K) with `GGML_VK_PERF_LOGGER=1 GGML_VK_PERF_LOGGER_FREQUENCY=50`. Run **one** seed (4242) of the fixed 2304-token prompt.
2. From the log, extract per-graph op time for (a) the target verify graph, (b) the draft inject graph, (c) the draft decode graph, plus FA pipeline names (xe_fa_decode_ph1/ph2 vs flash_attn_f32_f16 scalar) and mat-vec column counts (find the n==1 nodes).
3. Separately, run one normal (logger off) seed to confirm the baseline is intact.

**Pass (hypothesis survives):** the sum of GPU op time per round in (a)+(b)+(c) is ≤ 85 ms. That would leave ≥ 25 ms/round of host/sync gap, which justifies intervention 2. **Fail:** GPU time ≥ 120 ms/round, meaning the remainder is kernel time. Then switch to kernel work (verify mat-vec efficiency) and drop the sync hypothesis. **Also record:** whether the draft FA is scalar and what its share is (gates intervention 3).
**Rollback:** unset the two environment variables and relaunch through the governor. No files change. **Abort criteria:** governor headroom alarm, desktop stutter, or VRAM spill. The logger serialises work and reduces t/s; that slowdown is expected and must not be reported as a benchmark.

## 4. Precise source-level corrections worth considering (UNTESTED)
1. `ggml_vk_create_pipeline_func` (ggml-vulkan.cpp ~L777-781): on `createComputePipeline` failure, mark the pipeline failed and notify `compile_cv` before rethrowing. For FA cm1 pipelines specifically, return a "failed" state that `get_fa_tuning_params` treats as `FA_SCALAR`. Today waiters on `compiled` may block forever.
2. Shape admission: keep `shape_ok` strict. If the cm1 FA shader is parametrised (coopmat_reconciliation §4), admit by the *enumerated* M.
3. `common_speculative_impl_draft_dflash`: when `backend_sampling` is requested for DFlash2, log that it is ignored, so nobody believes it is active (L1101).
4. Server [TAG_SPEC_AVOID_DRAFT_REEVAL] (server-context.cpp L3415/L4226): inject only accepted+bonus positions into ctx_dft, after the accept step. Needs a correctness proof against the draft-KV `seq_rm` logic.
5. Gateway: use the canonical resolver (reasoning_policy.md). Never emit top-level `reasoning_effort` alongside nested kwargs.

## 5. Missing evidence that prevents a conclusion
- The split of the 112 ms/round remainder (no per-bucket timers yet). The identity of the n==1 matmuls that FORCE_MMVQ affects.
- The actual coopmat property list of this B60 driver (a debug-build `VK_LOG_DEBUG` line). Driver version.
- Load-log buffer sizes: model (GPU vs CPU_Mapped), KV, RS, compute (main and draft). DXGI budget with the normal desktop open.
- Qwen3.8 / DFlash2 architecture (n_extract, draft layers, SWA). Only Qwen3.5/3.6 public configs were available.
- The exact local diff between `c85e6c5` and my reconstruction (`git diff 86a283532 c85e6c598 --stat` on the user's machine would settle it).
- The ThinkingCap chat template (to verify effort names and how budget tags render).

## What the pack/Gemini research already covered (so we don't duplicate it)
- Identified issue #30503 and the 8x16x16 advertisement (correct as a lead). Benchmarks attribute 653/513/420 prefill to PR #29357. The pack lists rejected experiments: ub512 at 64K, n_max 15, MTP n=2, ngram+DFlash stacking, power plans/resolution.
- Its proposals that this report rejects or corrects: gate bypass + fallback (invalid; fallback absent), backend draft sampling (no-op for DFlash2), 0-IQ repack (no IQ tensors; not lossless), 96K from file size, the router, SYCL/containers, iGPU display, clock offsets. Detailed line-by-line review: `pack_defects_review.md`.
- **What this report adds that the pack does not have:** the IntelFA path already uses the advertised shape for f16 KV; the no-fallback/lazy-compile hazard; the DFlash2 backend-sampling no-op; the FORCE_MMVQ n==1 scope; the per-round arithmetic and bandwidth floor; recurrent-state ×(1+n_rs_seq) memory; the per-prompt feature-readback volume; the precedence matrix and tests.

## Sections C-F (detail)
- C: `coopmat_reconciliation.md`
- D: `dflash_timing_analysis.md`, `tools/dflash_timing.py`, `tools/dflash_timing_output.json`, `instrumentation_patch_UNTESTED.diff`
- E: `reasoning_policy.md`, `tests/precedence_matrix.csv`, `tools/reasoning_resolver_UNTESTED.py`, `tests/test_reasoning_resolver.py`, `tests/test_run_output.txt`
- F: `context_budget.md`, `tools/context_budget.py`, `tools/context_budget_output.json`
- Acceptance protocol: `acceptance_test_spec.md`. Pack review: `pack_defects_review.md`. Sources: `sources.md`.
