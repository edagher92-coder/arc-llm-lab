# Sources

## Primary code (read on the box)
- ggml-org/llama.cpp tag **b11526** = `5e4878e9787fff9bcc5c12478c47618b73268610` (2026-10-09). https://github.com/ggml-org/llama.cpp/tree/5e4878e9787fff9bcc5c12478c47618b73268610
- **b11524** = `86a283532072722c5f3363d37d59a874d09fa99b`. https://github.com/ggml-org/llama.cpp/tree/86a283532072722c5f3363d37d59a874d09fa99b
- PR #29357 "vulkan : Intel FA kernel for prefill" (open): https://github.com/ggml-org/llama.cpp/pull/29357. Commits `61cc4c2` (Intel customized FA shader for prefill), `1a5137a` (max_bias/logit_softcap check), `b583d8d` (m16n16k16/SIMD32, 2026-10-14, *not* in the install per the pack).
- Reconstruction used for line numbers: b11524 + cherry-pick 61cc4c2 + 1a5137a (APPROXIMATE stand-in for the non-public `c85e6c598…`). Files cited: `ggml/src/ggml-vulkan/ggml-vulkan.cpp`; `vulkan-shaders/{mul_mm.comp, flash_attn_cm1.comp, flash_attn_prefill.comp, flash_attn_decode_phase_1.comp, flash_attn_decode_phase_2.comp}`; `ggml-vulkan-types.h`; `common/speculative.cpp`; `common/common.{h,cpp}`; `src/llama-context.cpp`; `src/llama-memory-recurrent.cpp`; `src/llama-arch.cpp`; `tools/server/{server-context.cpp, server-common.cpp, server-chat.cpp}`; `common/jinja/caps.cpp`.
- `c85e6c598f89d11c3591616355a138c33737cee3`: **not found** in ggml-org/llama.cpp (API 422; git upload-pack "not our ref").

## Issues / PRs
- Issue #30503 (open): https://github.com/ggml-org/llama.cpp/issues/30503. Single B580 report; the 896 → 2731 pp16384 figure is from Gemma-4-E4B (community, unverified).
- PR #24406 Intel Xe FA decode kernels (referenced in PR #29357).
- PR #14001 enabling KHR_coopmat on Xe2: https://github.com/ggml-org/llama.cpp/pull/14001
- Issue #17628 / PR #23056: Intel Windows MMVQ policy (cited in the source comment).

## Official specs / docs
- Intel Arc Pro B60 specifications (456 GB/s, 192-bit, 24 GB GDDR6, PCIe 5.0 x8, device ID 0xE211): https://www.intel.com/content/www/us/en/products/sku/243916/intel-arc-pro-b60-graphics/specifications.html
- Vulkan `VkCooperativeMatrixPropertiesKHR`: https://docs.vulkan.org/refpages/latest/refpages/source/VkCooperativeMatrixPropertiesKHR.html
- Qwen3.5-27B config: https://huggingface.co/Qwen/Qwen3.5-27B/raw/main/config.json (local copy `src/qwen35_27b_config.json`)
- DFlash paper arXiv:2602.06036: https://arxiv.org/abs/2602.06036 ; code https://github.com/z-lab/dflash ; draft configs https://huggingface.co/z-lab/Qwen3.5-27B-DFlash , https://huggingface.co/z-lab/Qwen3.6-27B-DFlash

## Community (unverified, labelled wherever used)
- PR #29357 B580 benchmark comments (stornic56), SleepinDevil B70 numbers.
- All Reddit/blog figures in the pack's `docs/B60-RESEARCH-AND-BENCHMARKS.md` and `data/b60-external-benchmarks.csv`. Not re-checked; they do not transfer to B60 single-stream.
