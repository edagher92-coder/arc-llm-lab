# Intel's flash-attention prefill kernel on Arc (llama.cpp PR #29357)

## Summary

On Intel Arc, stock llama.cpp Vulkan reads prompts quickly when the conversation is short, then slows sharply as context grows. Prompt reading drops from 589 tok/s on an empty context to 118 tok/s at 32K tokens. That is exactly what hurts coding agents, which re-send a 20–40K token conversation on every turn.

Intel's FA prefill kernel ([PR #29357](https://github.com/ggml-org/llama.cpp/pull/29357), commits `61cc4c2` and `1a5137a` from `sliu39/llama.cpp`, branch `intel/fa-prefill`) fixes this, but **only when the KV cache is f16**. The PR was closed unmerged upstream, so this repo ships the two commits itself: see [Upstream status](#upstream-status-and-the-vendored-patches).

| Prompt processing, pp2048 (tok/s) | empty | 16K deep | 32K deep |
|---|---|---|---|
| Stock b11524, f16 KV | 589 | 198 | 118 |
| **Intel FA, f16 KV** | **653** | **513** | **420** |
| Stock b11524, q4_0 KV | 584 | 182 | 101 |
| Intel FA, q4_0 KV | 584 | 182 | 101 |

Generation speed (tg32, no drafter, `llama-bench`) is the same on both engines: 16.0 tok/s on an empty context, falling to 14.5 tok/s at 32K. That is the figure to quote for "stock" decode speed: it is not the 42.3 tok/s eval-suite throughput (wall-clock, prompt processing included), which also uses the DFlash2 drafter. Raw data: [compare-f16.txt](../data/raw/compare-f16.txt), [compare-q4.txt](../data/raw/compare-q4.txt).

In a real agent loop (three turns, each adding about 3K tokens to a 30–37K conversation and writing 400 tokens), total wall time fell from **201 s† to 55–57 s**.

- **55–57 s:** 54.9 s was the first Intel FA build ([server-test.txt](../data/raw/server-test.txt)); 56.7 s is the final tuned configuration at 57,344 context ([bench-history.csv](../data/raw/bench-history.csv)). A live run at 61K context measured 52.2 s (same file). All are in [agent-turns.csv](../data/agent-turns.csv).
- **† 201 s:** observed with the stock engine and the drafter before logging was in place; the raw log was not retained, and a re-run is planned. Treat it as an observation, not a reproducible measurement. The measured before-and-after at the engine level is the benchmark table above (prompt speed at 32K: 118 versus 420 tok/s).

## The trade-off: f16 KV costs memory

- **f16 KV for Qwen3.8-27B:** 64.5 KiB per token, so 64K tokens is about 4.0 GiB.
- **q4_0 KV:** about 18.6 KiB per token.

The profiles therefore have two variants:

| Variant | KV cache | Context on 24GB | Best for |
|---|---|---|---|
| `qwen3.8-27b` (default) | f16 | ~57–64K | Coding agents, anything that re-reads long context |
| `qwen3.8-27b-big` | q4_0 | ~150–200K | Huge documents read once |
| `qwen3.8-27b-long` | q4_0, no drafter | 262K | Whole-codebase questions, about 15 tok/s |

## Upstream status and the vendored patches

| Item | Status |
|---|---|
| Intel Xe flash-attention decode kernels, [PR #24406](https://github.com/ggml-org/llama.cpp/pull/24406) | Merged 2026-09-22. Already in stock b11524. |
| Intel GDN tuning, [PR #29476](https://github.com/ggml-org/llama.cpp/pull/29476) | Merged 2026-09-29. |
| **FA prefill shader, [PR #29357](https://github.com/ggml-org/llama.cpp/pull/29357)** | **Closed unmerged by its author on 2026-09-25.** The branch was force-pushed afterwards. This is the 118 to 420 tok/s change. |
| SYCL backend work, [PR #25025](https://github.com/ggml-org/llama.cpp/pull/25025) | Merged 2026-07-31 (a different backend; the prefill shader is Vulkan-only). |

Because the prefill shader never reached mainline and its branch can change, the two commits are **vendored** in [engine/patches/](../engine/patches/) with SHA256 checksums, the original author lines and a README on provenance and licence. The build applies them to llama.cpp b11524. The previous method (fetch the branch and cherry-pick) is kept as a fallback only.

The engine we ran is llama.cpp build 11526 (commit `c85e6c598`), which is upstream b11524 (`86a283532`, tag dated 2026-10-09) plus those two commits. The stock engine we compare against is plain b11524. Versions of everything else are in the [README](../README.md#versions-used).

## Build it (portable, no admin)

[engine/build.ps1](../engine/build.ps1) downloads a portable GCC toolchain (w64devkit), CMake and Ninja. It then builds `glslc` from shaderc, which needs cooperative-matrix and integer-dot support, and builds llama.cpp b11524 with the two vendored patches applied (it checks their checksums first). It installs to `C:\AI\llama.cpp\vulkan-intelfa` and never touches your existing build. On Linux, [engine/build-linux.sh](../engine/build-linux.sh) does the equivalent; patch application is verified, but the script has not been run end to end on a Linux machine with an Arc GPU.

Check the configure log for:

```
GL_KHR_cooperative_matrix supported by glslc
GL_EXT_integer_dot_product supported by glslc
```

Building with Visual Studio Build Tools also works. See [engine/BUILD-INTEL-FA.md](../engine/BUILD-INTEL-FA.md).

## Verify on your card

```powershell
powershell -ExecutionPolicy Bypass -File bench\compare-f16.ps1   # stock vs Intel FA, f16 KV, 0/16K/32K depth
powershell -ExecutionPolicy Bypass -File bench\server-test.ps1   # agent-style 3-turn test + coding/tool checks
```

Then switch with `qwen engine intelfa` (and back with `qwen engine stock`).

## Gotchas

- **The draft model's KV can stay quantised** (`-ctkd q8_0 -ctvd q8_0`). That saves VRAM without losing the main-model speed-up.
- **`-ub 256` instead of 512** freed about 0.55 GiB with no measurable speed loss ([tune.txt](../data/raw/tune.txt)).
- **Watch for an upstream equivalent.** PR #29357 is closed, but if the same optimisation, or something faster, is merged into mainline llama.cpp, use an official release and drop the custom build. Run the comparison script above on the new release to check, and [tell us](https://github.com/edagher92-coder/arc-llm-lab/issues/new?template=benchmark.yml).
- **Other Intel GPUs.** The shader is an Intel-specific path, and we measured it only on an Arc Pro B60. Results on a B580, B570, B50 or A770 are welcome ([GOOD-FIRST-ISSUES.md](GOOD-FIRST-ISSUES.md)).
- **Context shift is off.** The server runs with `--no-context-shift` (also the default in b11524), so a conversation that outgrows the window gets an explicit error instead of silently dropping its oldest tokens.
