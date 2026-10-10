# FAQ

**Is a 24GB Intel Arc card good for local LLMs?**
For a single user running a 27-32B dense model at 4-bit, yes: it fits with a 57-64K context and a speculative drafter, and on the B60 it delivers 42-45 tok/s average generation. Its limit is memory bandwidth - more tuning will not double that. Bigger/faster cards cost several times more (see the README for the price context at the time of writing).

**Ollama, LM Studio, or this?**
Ollama and LM Studio are the easiest way to start and both build on llama.cpp. This repo is for when you want what they don't expose: a custom engine with Intel's unmerged FA kernel (3.6x faster long-context reading than stock llama.cpp here), a speculative draft model (2.6x faster generation), per-request presets on one loaded model, VRAM-aware context sizing and agent wrappers. Apps that speak OpenAI-compatible or Anthropic-compatible APIs can use this server directly; Ollama's native API is not emulated.

**Vulkan or SYCL on Arc?**
For this model on the B60, Vulkan (with `GGML_VK_FORCE_MMVQ=1`) was faster in our testing. SYCL raw logs were not kept, so please submit a comparison.

**Why f16 KV cache when q4 saves memory?**
Because Intel's FA prefill kernel only accelerates f16 KV - 3.6x faster prompt reading at 32K. Use the q4 `big`/`long` variants only for very long one-off documents.

**My generation speed suddenly halved.**
Check free VRAM (`qwen doctor`). Below ~1.1 GiB free, generation collapses. Close GPU-heavy apps or let the governor drop to the BALANCED/LEAN profile.

**Will the agent silently lose context?**
Not with this setup: context shift is off (overflow = explicit error), agent windows are sized below the server context, and the governor never reloads a smaller context than a live session needs. The sustained-session test checks retention after compaction.

**Which tasks can the local model do unattended?**
See [RELIABILITY.md](RELIABILITY.md) for per-category tiers (autonomous / supervised / escalate) measured over 100 tasks.

**Linux?**
The engine flags and findings carry over directly. The governor and wrappers are PowerShell-first; Linux ports are welcome.
