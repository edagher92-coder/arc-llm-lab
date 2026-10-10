# Good first issues

Five tasks that need an Intel GPU, an hour or two, and no deep knowledge of this repo. Every one ends with something other Arc owners can use. Pick one, then [open an issue](https://github.com/edagher92-coder/arc-llm-lab/issues/new?template=test-my-card.yml) to say you're on it, or go straight to a pull request.

Rules for all of them: include the raw output, change one variable at a time, and say what you ran ([CONTRIBUTING.md](../CONTRIBUTING.md)). Results land in [COMMUNITY-RESULTS.md](COMMUNITY-RESULTS.md) with your name on them.

## 1. Run the benchmark on an Arc B580 (12GB) or B570 (10GB)

**Why:** these are the cards most people own, and we have no measured numbers for them, only specs ([gpu-comparison.csv](../data/gpu-comparison.csv)).
**Do:** `bench/arc-bench.ps1` (Windows) or `bench/arc-bench.sh` (Linux) with a model that fits, for example a 7B to 14B Q4_K_M GGUF. State the model and quant, because the 27B used here does not fit.
**Done when:** a JSON file from the script and the raw `llama-bench` output are attached to an issue or a pull request that adds the JSON to `data/community/`.

## 2. Get A770 (16GB) numbers

**Why:** the A770 has more memory bandwidth (560 GB/s) than a B60 or B580 (456 GB/s) and is common second-hand. Nobody has published a comparable run here.
**Do:** the same script, on Vulkan. If you can, also run the stock Vulkan build and the SYCL build on the same model so the three are comparable.
**Done when:** results for at least one build are submitted, with driver and OS.

## 3. A Linux and Mesa run

**Why:** the engine flags carry over to Linux, but the governor and wrappers are Windows-first and the build script for Linux is untested on hardware.
**Do:** build with `engine/build-linux.sh` (it applies the vendored Intel FA patches to b11524), then run `bench/arc-bench.sh`. Report your Mesa version, the kernel, whether `glslc` reported cooperative-matrix support, and anything that failed.
**Done when:** a result file is submitted, or a pull request fixes the build script for your distribution.

## 4. SYCL versus Vulkan on the same card and model

**Why:** we found Vulkan faster for Qwen3.8-27B on a B60 but did not keep the SYCL log, so that finding can't be checked. Other people publish SYCL numbers ([PEERS.md](PEERS.md)).
**Do:** run `llama-bench` with a SYCL build and a Vulkan build, same model, same flags, same depths (the script's defaults). Submit both JSON files.
**Done when:** both runs are in `data/community/` and the notes name the SYCL build and any environment variables used.

## 5. A short guide to pointing Ollama or LM Studio at llama-server

**Why:** many people already use Ollama or LM Studio for their apps and chat UIs. They can use this server's endpoint instead of their built-in engine, but we have only described that in a sentence ([FAQ.md](FAQ.md)).
**Do:** write `docs/OLLAMA-LMSTUDIO-ENDPOINT.md`: how to start llama-server or llama-swap from this repo, what base URL and model name to put into a client, and what does and doesn't work (Ollama's native API isn't emulated). Test it with at least one real app.
**Done when:** the guide is in a pull request with the steps you actually ran, and it is linked from the README.
