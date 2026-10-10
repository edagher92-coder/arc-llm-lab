# Intel's flash-attention prefill kernel on Arc (llama.cpp PR #29357)

## Summary

On Intel Arc, stock llama.cpp Vulkan reads prompts quickly when the conversation is short, then slows sharply as context grows. Prompt reading drops from 589 tok/s on an empty context to 118 tok/s at 32K tokens. That is exactly what hurts coding agents, which re-send a 20–40K token conversation on every turn.

Intel's FA prefill kernel ([PR #29357](https://github.com/ggml-org/llama.cpp/pull/29357), commits `61cc4c2` and `1a5137a` from `sliu39/llama.cpp`, branch `intel/fa-prefill`) fixes this, but **only when the KV cache is f16**.

| Prompt processing, pp2048 (tok/s) | empty | 16K deep | 32K deep |
|---|---|---|---|
| Stock b11524, f16 KV | 589 | 198 | 118 |
| **Intel FA, f16 KV** | **653** | **513** | **420** |
| Stock b11524, q4_0 KV | 584 | 182 | 101 |
| Intel FA, q4_0 KV | 584 | 182 | 101 |

Generation speed (tg32, no drafter) is the same on both engines: 16.0 tok/s on an empty context, falling to 14.5 tok/s at 32K. Raw data: [compare-f16.txt](../data/raw/compare-f16.txt), [compare-q4.txt](../data/raw/compare-q4.txt).

In a real agent loop (three turns, each adding about 3K tokens to a 30–37K conversation and writing 400 tokens), total wall time fell from **201 s to 55 s** ([server-test.txt](../data/raw/server-test.txt)).

## The trade-off: f16 KV costs memory

- **f16 KV for Qwen3.8-27B:** 64.5 KiB per token, so 64K tokens is about 4.0 GiB.
- **q4_0 KV:** about 18.6 KiB per token.

The profiles therefore have two variants:

| Variant | KV cache | Context on 24GB | Best for |
|---|---|---|---|
| `qwen3.8-27b` (default) | f16 | ~57–64K | Coding agents, anything that re-reads long context |
| `qwen3.8-27b-big` | q4_0 | ~150–200K | Huge documents read once |
| `qwen3.8-27b-long` | q4_0, no drafter | 262K | Whole-codebase questions, about 15 tok/s |

## Build it (portable, no admin)

[engine/build.ps1](../engine/build.ps1) downloads a portable GCC toolchain (w64devkit), CMake and Ninja. It then builds `glslc` from shaderc, which needs cooperative-matrix and integer-dot support, and builds llama.cpp b11524 with the two commits cherry-picked. It installs to `C:\AI\llama.cpp\vulkan-intelfa` and never touches your existing build.

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
- **Watch for the PR being merged.** Once it is in mainline llama.cpp, use an official release and drop the custom build.
