# FAQ: running LLMs on Intel Arc with llama.cpp

## Hardware and price

**Is a 24GB Intel Arc card good for local LLMs?**
For one person running a 27-32B dense model at 4-bit, yes. Qwen3.8-27B fits on an Arc Pro B60 24GB with a 57-64K context and a speculative draft model, and generates 42.3 tok/s eval-suite throughput (wall-clock, prompt processing included; per-request decode 47-58 tok/s, mean 53.3). The limit is memory bandwidth (456 GB/s on the B60), so more tuning will not double that. Faster cards cost several times more ([README](../README.md#which-intel-card-and-which-model-fits)).

**What does a B60 cost in Australia?**
The cheapest sourced listing we recorded for a 24GB Arc Pro B60 was A$1,240 ([gpuprix.com](https://gpuprix.com/australia/gpus/arc-pro-b60), ASRock B60 Creator, updated 2026-10-07). On 2026-10-10 PCCaseGear listed an ASRock Arc Pro B60 Passive 24GB (OEM) at A$999 including GST. A passive card has no fan of its own and needs strong case or server airflow, so check your case before buying one. Prices move; treat both as a snapshot.

**Will a B580 12GB, B570 10GB, B50 16GB or A770 16GB run this?**
Not this 27B model with a useful context: the Q4_K_M weights alone are about 15.3 GiB. They run smaller models well, and the same tools and benchmark scripts apply. See the model-fit table in the [README](../README.md#which-intel-card-and-which-model-fits) and send us numbers: [GOOD-FIRST-ISSUES.md](GOOD-FIRST-ISSUES.md).

## Software choices

**Vulkan or SYCL on Arc?**
For this model on our B60, Vulkan (with `GGML_VK_FORCE_MMVQ=1`) was faster in our testing. We did not keep the SYCL raw log, so that is an observation you can't check. Other people publish SYCL numbers on the same card ([PEERS.md](PEERS.md)), and upstream SYCL work continues (for example llama.cpp PR #25025, merged 2026-07-31). The Intel FA prefill patch used here is Vulkan-only. A like-for-like SYCL run with `bench/arc-bench.sh` or `.ps1` is one of the most useful things you can send ([GOOD-FIRST-ISSUES.md](GOOD-FIRST-ISSUES.md)).

**Ollama, LM Studio, or this?**
Ollama and LM Studio are the easiest way to start. Ollama enables its Vulkan backend by default when you install it ([docs.ollama.com/gpu](https://docs.ollama.com/gpu)), and both bundle their own copy of llama.cpp. That is also the limit: they ship their own engine, so they don't include the Intel FA prefill patch or the DFlash2 draft-model path, and this exact setup can't be reproduced inside them. They are good for smaller models and quick trials. If you want this server's speed from the apps you already use, run llama-server (or llama-swap) from this repo and point those apps at it: anything that accepts an OpenAI-compatible base URL (`/v1/chat/completions`, `/v1/responses`) or an Anthropic-compatible one (`/v1/messages`) works. Ollama's native API is not emulated.

**What about IPEX-LLM?**
The `intel/ipex-llm` repository was archived on 2026-01-28 and is read-only. Don't start a new setup on it. llama.cpp's Vulkan and SYCL backends are the maintained llama.cpp routes for Intel GPUs.

**What about Intel's llm-scaler (vLLM in Docker)?**
[intel/llm-scaler](https://github.com/intel/llm-scaler) is Intel's vLLM-based Docker route for Arc Pro B60 and B70 cards. Its vLLM images have added speculative methods such as DFlash (for Qwen3.6-27B in `vllm-0.21.0-b3`, 2026-08-10) and MTP. It is a different stack, aimed at batching and multi-GPU serving, and we have not benchmarked it. If you run Linux and want vLLM semantics, it is the route to try; this repo is about llama.cpp.

**Where does the Intel FA kernel stand upstream?**
Two separate pieces of Intel work matter. The decode-focused Xe flash-attention kernels (llama.cpp PR #24406) were merged on 2026-09-22 and the Intel GDN tuning (PR #29476) on 2026-09-29, so stock b11524 already includes both, and our stock numbers (16 tok/s generation, 118 tok/s prompt at 32K) were measured with them. The prefill shader (PR #29357) is the one that takes prompt reading at 32K from 118 to 420 tok/s. Its author closed that PR without merging on 2026-09-25 and later force-pushed the branch, so this repo **vendors the two commits** in [engine/patches/](../engine/patches/) with checksums and attribution, and the build applies them on top of b11524. Details: [INTEL-FA.md](INTEL-FA.md).

## Settings

**Why an f16 KV cache when q4 saves memory?**
Because the Intel FA prefill kernel only sped up the f16 cache in our tests: 420 versus 118 tok/s at 32K, while with q4_0 it was identical to stock (101 versus 101). Use the q4 `big` and `long` variants only for very long one-off documents. For Qwen3.8-27B the f16 KV costs 64.5 KiB per token.

**My generation speed suddenly halved.**
Check free VRAM (`qwen doctor`). In our draft-length sweep the one run that fell short of VRAM (n=15, 0.96 GiB free) dropped from 42 to 27 tok/s ([tune.txt](../data/raw/tune.txt)). Runs at 1.04 and 0.71 GiB free did not slow down, so the exact threshold is not established, and draft length changed in that run too. As a precaution the governor keeps 1.35 to 3 GiB free, depending on its profile. Close GPU-heavy apps or let it drop to the BALANCED or LEAN profile.

**Is `--cache-reuse` doing anything?**
No, not on this model. The server prints `cache_reuse is not supported by multimodal, it will be disabled` at start-up ([server-57344.log](../data/raw/server-57344.log)). Prefix reuse comes from the host-RAM prompt cache and context checkpoints. See [TOKEN-EFFICIENCY.md](TOKEN-EFFICIENCY.md).

**Why is prompt reading slower than some other published B60 numbers?**
Other people report 589 to 638 tok/s at about 29K on a llama.cpp engine, and 657 tok/s at 32.8K on OpenVINO, against our 420 tok/s at 32K. The measurements aren't identical (different KV types and tools), but the gap is real. [PEERS.md](PEERS.md) lays the rows side by side. Generation speed is where this repo leads.

## Agents and safety

**Will the agent lose context?**
Not silently. Context shift is off (`--no-context-shift`; in current llama.cpp it is also the default), so a conversation that outgrows the server context gets an explicit HTTP 400 instead of quietly losing its oldest tokens. The agent windows are sized below the server context (server context minus 8K), and the governor never reloads a smaller context than a live session needs. **Claude Code's own compaction is different, and by design:** when the window fills, Claude Code summarises the conversation, and a summary can drop detail. That is not the server truncating anything, but it can still make an agent forget a specific instruction. The sustained-session test ([RELIABILITY.md](RELIABILITY.md)) checks whether a code given at step 1 is still recalled after compaction.

**Does the model work past 130K tokens?**
Qwen3.8-27B supports a long native context, but an upstream issue reports it ending instantly beyond about 130K tokens ([llama.cpp #27756](https://github.com/ggml-org/llama.cpp/issues/27756)). This repo's f16 setups stop at 64K, and the q4 `big` and `long` variants (150K to 262K) are for one-off documents. Test before relying on them.

**Which tasks can the local model do unattended?**
See [RELIABILITY.md](RELIABILITY.md) for per-category tiers (autonomous, supervised, escalate) measured over 100 tasks. Rule of thumb from that run: commit or checkpoint before any unattended run, and supervise multi-file refactors ([README](../README.md#agent-safety)).

## Platform

**Can I get a ChatGPT-style web UI, voice and tools?**
Yes: [PLATFORM.md](PLATFORM.md) covers Open WebUI on top of llama-swap, a Kokoro and whisper.cpp voice adapter, MCP tools, and Tailscale access from your phone.

**Linux?**
The engine flags and findings carry over. `engine/build-linux.sh` builds llama.cpp with the vendored patches (patch application is verified; the script has not been run on Linux with an Arc GPU by the author), and `bench/arc-bench.sh` measures your card. The governor and agent wrappers are PowerShell and Windows first; ports are welcome.
