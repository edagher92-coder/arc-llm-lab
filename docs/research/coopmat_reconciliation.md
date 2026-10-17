# Cooperative-matrix reconciliation (Priority C)

**Revision note.** `c85e6c598f89d11c3591616355a138c33737cee3` is **not public**. GitHub API returns `422 No commit found`, and `git fetch` of the SHA from ggml-org/llama.cpp returns `not our ref`. The pack's own plan (CODEX_PROMPT_AND_PLAN.md L12) says the install is `b11524` (`86a283532`) plus PR #29357 commits `61cc4c2` and `1a5137a`, built into `vulkan-intelfa`. I rebuilt that tree on the box (`src/recon-c85e6c5`): b11524 + cherry-pick 61cc4c2 + 1a5137a. Both picks applied cleanly. The SHA differs because the committer metadata differs. **All line numbers below are in that reconstruction (APPROXIMATE).** For files PR #29357 does not touch (everything outside ggml-vulkan), the line numbers match upstream b11524 exactly. Public tag `b11526` is `5e4878e9787fff9bcc5c12478c47618b73268610`. "IntelFA" is a local build of the open PR #29357, not a public fork name.

## 1. What the driver advertises
- **Community report, unverified locally.** On a B580 with driver 32.0.101.9033, issue #30503 says the f16 cooperative-matrix list contains **only `M=8 N=16 K=16`**, for both f32 and f16 accumulation, subgroup scope. PR #29357's author, an Intel engineer, writes: "CM1 FA kernel require m16n16k16 coopMat shape that not supported in driver yet" (PR #29357 comment, 2026-09-25).
- `vulkaninfo` does not print the shape list. You get it from `vkGetPhysicalDeviceCooperativeMatrixPropertiesKHR`, and ggml prints it only in a `VK_LOG_DEBUG` build (ggml-vulkan.cpp, inside the shape loop around L4700).
- **Vulkan spec point:** the SPIR-V `OpTypeCooperativeMatrixKHR` dimensions a shader uses must match an enumerated `VkCooperativeMatrixPropertiesKHR` entry. Running an un-advertised 16x16x16 form is outside the API contract. "It worked on 10 probes" (issue #30503) is driver behaviour, not a guarantee. It can change between drivers and can produce silently wrong results.

## 2. How ggml-vulkan enumerates and admits shapes
| Step | Code (recon) | Effect on B60 (0xE211, Xe2, minSubgroupSize 16) |
|---|---|---|
| Arch detect | `get_device_architecture`, L60-100 | `INTEL_XE2` (minSubgroupSize==16) |
| Vendor gate | `ggml_vk_khr_cooperative_matrix_support` L16306 | Xe2 allowed |
| Feature gate | L4563 `coopmat_support && coopmat_features.cooperativeMatrix` | on |
| Shape loop | ~L4710-4780 | **The first** f16/f16/subgroup entry sets `coopmat_m/n/k`, which becomes **8/16/16**. `coopmat_support_16x16x16_*` is set only if a 16x16x16 entry exists, so it stays **false** |
| mul_mm (cm1 GEMM) | `mul_mm.comp` L167-169, L343-345 use spec constants TM/TN/TK = `coopmat_m/n/k` | Instantiates the **advertised 8x16x16**. Valid and in use (prefill GEMM) |
| mul_mmq_cm1 (int8) | `use_cm1_int` only on AMD RDNA3/4 | Not used on Intel |
| Generic FA cm1 | `get_fa_tuning_params` L1356 `shape_ok` requires 16x16x16; `flash_attn_cm1.comp` L26-27 hard-codes `MatBr=MatBc=16` and K=16 | Rejected, so `FA_SCALAR`. This is #30503 |
| conv2d cm1 | requires 16x16x16 and subgroup 32/64 | Not used |
| **Intel Xe FA (PR #29357 + #24406)** | `xe_fa_supported_platform` L8241. `neq1>8` selects the prefill shader (L8264), otherwise the decode dual-phase pair. Shaders: `flash_attn_prefill.comp` L60-61 and `flash_attn_decode_phase_1/2.comp` `#define TM 8, TK 16`, TN spec constant = `xe_native_sub_group_size` = 16 (L3197) | **8x16x16 = the advertised shape**, pipelines pinned to subgroup 16 (`required_subgroup_size`). Requires **F16 K/V**, mask F16, no softcap/ALiBi |

### Consequence for this install (the key reconciliation)
- **Main model, f16 KV:** prefill (`neq1>8`) and DFlash verification (`neq1 = draft+1 ≤ 8`) already run on the Intel Xe FA shaders, which use the advertised 8x16x16. **The #30503 gate is not on the main model's hot path.** That is consistent with the 653/513/420 t/s prefill numbers the pack credits to PR #29357.
- **Where #30503 does bite:** any FA whose K/V is **not f16**. Here that is the **DFlash draft context (`-ctkd/-ctvd q8_0`)**, which falls through to `get_fa_tuning_params`, gets `shape_ok=false`, and lands on `FA_SCALAR`. The same would apply to a future **q8_0 main KV** used to reach 50-60K. On the draft side, the cost per round is inside the 20.8 ms draft timer and the inject decode, and it is **unmeasured**.
- **Decode with N==1 uses scalar on every vendor anyway** (L1366). So #30503 cannot help single-token decode.
- **Subgroup sizes:** Xe2 supports 16 and 32. ggml reports "warp size 32". The Xe shaders pin 16. The generic cm1 FA uses `device->subgroup_size` (32) with 16x16 fragments, which Intel has said is not a native shape.

## 3. Fallback behaviour if pipeline creation fails
`ggml_vk_create_pipeline_func` (L577-800): `createShaderModule`, `createPipelineLayout` and `createComputePipeline` each `catch (vk::SystemError) { std::cerr << ...; throw; }` (compute pipeline: L777-781). **There is no fallback.** Pipelines compile lazily on first use (`ggml_vk_load_shaders(device, requested)`, claim/compile at ~L3974-3990). That means a failure surfaces mid-request as a C++ exception. Also, the `compile_pending` flag is set before compile (~L3976) and `compile_cv.wait(... compiled)` (L4015) waits on `compiled`. If one thread throws, another thread waiting on the same pipeline may never be released. **This is a hazard; I have not proven it reachable.** The pack's claim that a fallback exists (patch L13-15, plan Task 1) is **false**: its diff contains no such code.

## 4. What a *valid* 8x16x16 generic FA cm1 path would need (UNTESTED design, no code claimed working)
Don't relax `shape_ok`. Instead:
1. In `flash_attn_cm1.comp`, turn `MatBr` and the K-step `16` into spec constants. All `coopmat<..., MatBc, 16, UseA>` / `<16, MatBr, UseB>` / accumulators must form an advertised (M,N,K) triple. With M=8: S = K·Qᵀ tiles become `MatBc=8` (M), `MatBr=16` (N), K=16. For P·V, swap the A/B roles so the 8-row side is M. PR #29357's prefill shader does exactly that ("swapped P/V order to use V as matrixA").
2. Recompute every derived stride and shared-memory size (`kvsh_stride`, `osh_stride`, `pvsh`, `Psh`, `v_cols`, `num_hsv_tiles`), plus `get_fa_tuning_params_coopmat1` / `ggml_vk_flash_attn_coopmat_shmem_support` Br/Bc/row_split.
3. Pin `required_subgroup_size = 16` on Intel (as the Xe shaders do) and require `subgroup_require_full_support`.
4. Admission: `shape_ok = has_shape(M_sel,16,16, acc)`, where M_sel comes from enumerated properties, never assumed.
5. Validation gates: `test-backend-ops -o FLASH_ATTN_EXT` all pass, including q8_0/q4_0 K/V and HSK=HSV=256 with GQA 6 (Qwen3.5-27B: 24 Q heads / 4 KV heads). Greedy token-identical output against FA_SCALAR on a fixed prompt set. Then the q8_0 draft-KV A/B.

Lower-effort alternative (UNTESTED): extend `xe_fa_supported_dtype` to q8_0 K/V by dequantizing to f16 scratch. The `use_dequant_kv` / `pipeline_dequant_transpose` machinery already exists (~L8110-8118). That would route the draft's q8_0 FA onto the already-valid 8x16x16 Xe shaders, at the cost of an f16 scratch copy.

## 5. Recommendation
Do **not** apply the pack's gate bypass. It is malformed anyway: it targets a non-existent `ggml_vk_has_coopmat_support` and a different function signature. Measure first. A GGML_VK_PERF_LOGGER run shows whether `flash_attn_f32_f16*` scalar FA in the draft context is a material share of each round. Only if it is should you pursue §4 or the dequant route.

## 6. Upstream lead (not in this install)
PR #29357 head now has `b583d8d` (2026-10-14), "add m16n16k16/SIMD32 support for Xe FA prefill shader". It parametrises the prefill shader shape per subgroup (8→{8,8,16}, 16→{16,8,16}, 32→{16,16,16}), and per its author it is prefill-only ("decode/spec decode XE FA shaders were not changed"). A later stride-gate relaxation for single-KV-head models was also discussed. It doesn't apply here: Qwen3.5 has 4 KV heads.
