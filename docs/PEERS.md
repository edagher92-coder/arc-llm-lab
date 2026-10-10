# How this compares with other Arc Pro B60 results

Other people are publishing numbers for Qwen3.8-27B on the Intel Arc Pro B60. This page puts them next to ours so you can see where each approach is strong. The raw rows are in [data/peer-benchmarks.csv](../data/peer-benchmarks.csv); the community-submitted ones are in [COMMUNITY-RESULTS.md](COMMUNITY-RESULTS.md).

**Read these numbers with care.** They are self-reported, the backends differ (llama.cpp Vulkan, llama.cpp SYCL, OpenVINO), the speculative-decoding methods differ (DFlash2, MTP, none), the context depths differ, and the measurement tools differ (`llama-bench` versus server-reported speeds on a real prompt). Rows were collected on 2026-10-10 from public pages, most with one run per cell. Treat gaps under about 10% as noise.

## The short version

- **Generation (decode):** 42.3 tok/s with a DFlash2 draft model (n=7) is above the highest peer figure we found for a single B60 running Qwen3.8-27B Q4_K_M. It is eval-suite throughput: generated tokens divided by total wall-clock over eight eval requests (seven coding tasks and one web page), with prompt processing and HTTP included, at shallow context. Peers report decode-only speeds, so the comparable figure for this repo is the per-request decode range of 47 to 58 tok/s (mean 53.3), from the same run in [tune.txt](../data/raw/tune.txt). We keep 42.3 as the conservative headline. The closest rival is a self-reported 41.28 to 41.88 tok/s on custom lower-bit quants with embedded MTP (SYCL, shallow context, not like-for-like). At about 30K of context our agent turns still generate at 42.2 tok/s, against 32.3 tok/s for the llama.cpp numbers at 28.8K in [marfrit/arcint#1](https://github.com/marfrit/arcint/issues/1).
- **Prompt reading (prefill):** we are **not** the fastest. At about 29K context the llama.cpp numbers in that issue read 589 to 638 tok/s; ours read 420 tok/s at 32K. Their OpenVINO runs read 657 tok/s at 32.8K, and 1,094 tok/s at 4K. The Intel FA kernel in this repo takes stock llama.cpp from 118 to 420 tok/s at 32K, but a faster prefill path clearly exists.
- **Why the two differ so much:** a coding agent re-reads a long conversation on every turn, so prefill matters as much as decode. The honest summary is that this repo is strongest on generation speed and on being reproducible and measured end to end (agent tasks, VRAM headroom, context safety), and not the leader on prefill.

## Side by side at comparable depths

All rows are a single Arc Pro B60 and Qwen3.8-27B. The first two blocks are ours ([compare-f16.txt](../data/raw/compare-f16.txt), [tune.txt](../data/raw/tune.txt), [bench-history.csv](../data/raw/bench-history.csv)).

| Source | Backend and method | KV cache | Depth | Prompt tok/s | Generation tok/s |
|---|---|---|---|---|---|
| **arc-llm-lab** | llama.cpp Vulkan b11524 + Intel FA patches, DFlash2 n=7 | f16 | empty | 653 (`llama-bench` pp2048) | **42.3** (eval-suite throughput, wall-clock; decode 47-58) |
| **arc-llm-lab** | same | f16 | 32K | 420 (`llama-bench` pp2048) | **42.2** (agent turns at 30-37K) |
| arc-llm-lab, stock build | llama.cpp Vulkan b11524, no drafter | f16 | 32K | 118 | 14.45 (`llama-bench` tg32) |
| marfrit/arcint#1 | llama.cpp engine in ArcInt 0.5.x/0.6.0 (build not stated), MTP 5 drafts | q8_0 | 4K | 824-910 | 36.6 |
| marfrit/arcint#1 | same | q8_0 | 28.8K | **589-638** | 32.3 |
| marfrit/arcint#1 | OpenVINO int4, MTP | not stated | 4K | 1,093.9 | 31.9 |
| marfrit/arcint#1 | OpenVINO int4, MTP | not stated | 32.8K | **657.1** | 17.4 |
| Greatjedi (Hugging Face) | llama.cpp SYCL, custom tuned quants, embedded MTP | not stated | shallow | 245.5 (`-p 128`) | 41.3 to 41.9 |

What this tells you:

1. **Speculative decoding is where the generation speed comes from.** Without a drafter our B60 generates 16.05 tok/s at empty context. The same hardware reaches 42.3 tok/s with DFlash2. The strongest peer runs with MTP land between 31.9 and 41.9 tok/s at shallow context; other self-reported MTP runs on this card are lower (7.9 to 23.0 tok/s, see the full table below).
2. **Prefill is the gap.** The llama.cpp rows from marfrit read about 40% to 50% faster than ours at similar depth. They use a q8_0 KV cache while we use f16, and they are measured on a real prompt rather than `llama-bench`, so the comparison is not exact, but the direction is clear.
3. **Depth hurts everyone.** Decode falls from 36.6 to 32.3 tok/s between 4K and 28.8K in the llama.cpp rows, and from 31.9 to 17.4 tok/s between 4K and 32.8K in the OpenVINO rows. Ours stays near 42 tok/s across the agent turns, but that is a code workload where the drafter does well (573 of 877 drafted tokens accepted, 65%, on a single shallow-context code request in [server-test.txt](../data/raw/server-test.txt); acceptance was not logged for the agent turns). Expect less on text that drafts poorly.
4. **Context budget differs.** The marfrit runs used a 131K to 156K window, and we cap at 64K (57 to 61K while the PC is in use) to keep a drafter and f16 KV inside 24GB. Past 130K, an upstream issue reports instant end-of-sequence on this model ([llama.cpp #27756](https://github.com/ggml-org/llama.cpp/issues/27756)), so long windows need their own testing.

## Other cards

Two Arc Pro B70 (32GB) results exist for dense 27B models, with no drafter: 1,007 tok/s prompt and 23 tok/s generation (model not named, [SergiioB cookbook](https://github.com/SergiioB/intel-arc-pro-b70-inference-cookbook)), and 718 tok/s and 20.4 tok/s for Qwen3.5-27B on SYCL ([PMZFX](https://github.com/PMZFX/intel-arc-pro-b70-benchmarks)). Our no-drafter B60 figure is 16.05 tok/s. The B70's memory bandwidth is 608 GB/s against the B60's 456 GB/s, 1.33 times higher ([gpu-comparison.csv](../data/gpu-comparison.csv)), so the observed gap of 1.27 to 1.43 times (20.4 to 23 tok/s against 16.05) is about what bandwidth alone would suggest (ESTIMATE: different models and builds).

## How to compare your own numbers fairly

Use the same tool and the same depths we do: `bench/arc-bench.ps1` or `bench/arc-bench.sh` run `llama-bench` at depth 0, 16K and 32K with an f16 KV cache, and write a JSON file you can share ([COMMUNITY-RESULTS.md](COMMUNITY-RESULTS.md)). Then state the backend and build, the KV types, and whether a draft model was used.

Corrections are welcome. If a row here misstates your work, or you have a result that belongs in the table, [open an issue](https://github.com/edagher92-coder/arc-llm-lab/issues/new?template=benchmark.yml).

## All peer rows

Generated from [data/peer-benchmarks.csv](../data/peer-benchmarks.csv) by `tools/build_tables.py`. "n/d" means not stated by the source. Quote notes as given by their authors.

<!-- peers-table:start -->
| Source | Date | GPU | Model, quant | Backend | Spec. decoding | Depth (tokens) | pp tok/s | tg tok/s | Notes |
|---|---|---|---|---|---|---|---|---|---|
| [arc-llm-lab (this repo)](https://github.com/edagher92-coder/arc-llm-lab/blob/main/data/raw/compare-f16.txt) | 2026-10-10 | Arc Pro B60 24GB | Qwen3.8-27B, UD-Q4_K_M (f16 KV) | llama.cpp Vulkan b11524 + Intel FA prefill patches (build 11526, c85e6c598), Windows 11, driver 32.0.101.8976 | DFlash2 n=7 | 0 | 653.3 | 42.3 | pp = llama-bench pp2048 (no drafter) at depth 0; tg = eval-suite throughput with DFlash2 n=7 at shallow context: generated tokens / total wall-clock over 8 eval requests (7 coding + 1 web page), prompt processing included; per-request decode 47-58 tok/s, mean 53.3 (raw/tune.txt); no-drafter tg32 16.05 (raw/compare-f16.txt); one run per cell |
| [arc-llm-lab (this repo)](https://github.com/edagher92-coder/arc-llm-lab/blob/main/data/raw/compare-f16.txt) | 2026-10-10 | Arc Pro B60 24GB | Qwen3.8-27B, UD-Q4_K_M (f16 KV) | llama.cpp Vulkan b11524 + Intel FA prefill patches (build 11526, c85e6c598), Windows 11, driver 32.0.101.8976 | DFlash2 n=7 | 32768 | 420.0 | 42.2 | pp = llama-bench pp2048 at depth 32768 (no drafter; raw/compare-f16.txt); tg = generation during 3 agent turns at 30-37K context, final tuned config (raw/bench-history.csv); no-drafter tg32 at that depth 14.46; one run per cell |
| [arc-llm-lab (this repo), stock comparison](https://github.com/edagher92-coder/arc-llm-lab/blob/main/data/raw/compare-f16.txt) | 2026-10-10 | Arc Pro B60 24GB | Qwen3.8-27B, UD-Q4_K_M (f16 KV) | llama.cpp Vulkan b11524 stock (Clang 20.1.8), Windows 11 | none | 32768 | 118.0 | 14.45 | llama-bench pp2048 / tg32 at depth 32768; depth 0 is pp 589.2, tg 16.01; one run per cell |
| [marfrit/arcint#1 OpenVINO](https://github.com/marfrit/arcint/issues/1) | 2026-09-03 | Arc Pro B60 24GB | Qwen3.8-27B, int4 OpenVINO IR | ArcInt 0.2.12 commit 529bad37 / OpenVINO 2026.4.0 patched | MTP | 4061 | 1093.9 | 31.9 | MTP accept 75.9%; target-only decode 24.7; host has 2x B60 but isolated to one card; ctx window 155648 |
| [marfrit/arcint#1 OpenVINO](https://github.com/marfrit/arcint/issues/1) | 2026-09-03 | Arc Pro B60 24GB | Qwen3.8-27B, int4 OpenVINO IR | ArcInt 0.2.12 commit 529bad37 / OpenVINO 2026.4.0 patched | MTP | 32838 | 657.1 | 17.4 | MTP accept 77.0%; target-only decode 20.9 |
| [marfrit/arcint#1 OpenVINO](https://github.com/marfrit/arcint/issues/1) | 2026-09-03 | Arc Pro B60 24GB | Qwen3.8-27B, int4 OpenVINO IR | ArcInt 0.2.12 commit 529bad37 / OpenVINO 2026.4.0 patched | MTP | 131149 | 268.2 | 3.9 | MTP accept 0.0% (f16 rotary overflow bug; fixed in 0.3.0 per owner Oct 8); target-only decode 13.6 (single diagnostic sample) |
| [marfrit/arcint#1 llama.cpp](https://github.com/marfrit/arcint/issues/1) | 2026-10-08 | Arc Pro B60 24GB | Qwen3.8-27B, Q4_K_M (q8_0 KV) | llama.cpp engine in ArcInt 0.5.x/0.6.0 (exact llama.cpp build/backend not stated) | MTP 5 drafts | 4109 | 824-910 | 36.6 | draft accept 37%; no-MTP decode 18.4; ctx window 131072; one run per cell |
| [marfrit/arcint#1 llama.cpp](https://github.com/marfrit/arcint/issues/1) | 2026-10-08 | Arc Pro B60 24GB | Qwen3.8-27B, Q4_K_M (q8_0 KV) | llama.cpp engine in ArcInt 0.5.x/0.6.0 (exact llama.cpp build/backend not stated) | MTP 5 drafts | 28833 | 589-638 | 32.3 | draft accept 43%; no-MTP decode 15.1 |
| [marfrit/arcint#1 llama.cpp](https://github.com/marfrit/arcint/issues/1) | 2026-10-08 | Arc Pro B60 24GB | Qwen3.8-27B, Q4_K_M (q8_0 KV) | llama.cpp engine in ArcInt 0.5.x/0.6.0 (exact llama.cpp build/backend not stated) | MTP 5 drafts | 129981 | 252-272 | 19.3 | draft accept 47%; no-MTP decode 9.7; peak VRAM 21.4 GiB |
| [srmiles/local-llm-benchmarks](https://github.com/srmiles/local-llm-benchmarks) | 2026-08-15 | Arc Pro B60 24GB | Qwen3.8-27B, Q4_K_M + Q4_0 MTP + Q8_0 mmproj | llama.cpp b10433 | MTP | n/d | 333.5 | 23.0 | accept 57.9%; 'parked' status date; repo has 2x B60 but per-row GPU count not stated (VRAM 22.3 GiB suggests single card - inference) |
| [srmiles/local-llm-benchmarks](https://github.com/srmiles/local-llm-benchmarks) | 2026-08-27 | Arc Pro B60 24GB | Qwen3.8-27B, UD-Q4_K_XL (UD 2.0) + unsloth MTP head | llama.cpp SYCL sycl-f16-allfixes | MTP | 12000 | 711 | 18.91 | accept 55.2%; VRAM 20.36 GiB; ctx 12K as stated; GPU count not stated |
| [srmiles/local-llm-benchmarks](https://github.com/srmiles/local-llm-benchmarks) | 2026-08-27 | Arc Pro B60 24GB | Qwen3.8-27B, UD-Q4_K_XL (UD 3.0) + unsloth MTP head | llama.cpp SYCL sycl-f16-allfixes | MTP | 12000 | 685 | 17.11 | accept 53.5%; VRAM 20.02 GiB; GPU count not stated |
| [srmiles/local-llm-benchmarks](https://github.com/srmiles/local-llm-benchmarks) | n/d | Arc Pro B60 24GB | Qwen3.8-27B, UD-Q3_K_XL (13.44 GB) | llama.cpp (build not stated) | MTP | 12000 | 588 | 7.89 | accept 55.8%; date not stated; GPU count not stated |
| [Greatjedi HF](https://huggingface.co/Greatjedi/Qwen3.8-27B-Intel-Arc-Tuned-GGUF) | n/d | Arc Pro B60 24GB | Qwen3.8-27B (Ridge Intel Arc Tuned), Q4_K (15.29 GiB) | llama.cpp build-sycl SYCL (branch sycl-iquants-mmq; no commit hash) | none for pp/tg bench | shallow (llama-bench -p 128 -n 32) | 245.54 | 22.23 | self-reported; undated; with embedded MTP 41.28 tok/s 93.4% accept; page also claims 448 tok/s prefill in production text which conflicts with table |
| [Greatjedi HF](https://huggingface.co/Greatjedi/Qwen3.8-27B-Intel-Arc-Tuned-GGUF) | n/d | Arc Pro B60 24GB | Qwen3.8-27B (DAS Lab Intel Arc Tuned), Q4_K (13.72 GiB) | llama.cpp build-sycl SYCL | none for pp/tg bench | shallow (llama-bench -p 128 -n 32) | 243.61 | 22.36 | self-reported; with external DFlash2 36.03 tok/s 93.5% accept |
| [Greatjedi HF](https://huggingface.co/Greatjedi/Qwen3.8-27B-Intel-Arc-Tuned-GGUF) | 2026-09-17 | Arc Pro B60 24GB | Qwen3.8-27B (DAS Lab IQ3_S-MTP-Q4_K), Q4_K mix (14.31 GiB) | llama.cpp build-sycl SYCL | embedded MTP (ngram-mod+draft-mtp n-max=3) | shallow | - | 41.88 | reasoning workload; autoregressive 21.42; 92.9% accept; DFlash2 39.68 |
| [Greatjedi HF](https://huggingface.co/Greatjedi/Qwen3.8-27B-Intel-Arc-Tuned-GGUF) | 2026-09-17 | Arc Pro B60 24GB | Qwen3.8-27B (DAS Lab IQ3_S-MTP-Q4_K), Q4_K mix | llama.cpp build-sycl SYCL | DFlash2 n-max=3 p-min=0.7 | ~150000 | - | 7.91 | decode only; accept 84.7%; native MTP n-max=2 + SYCL graph 7.21 (78.4%) |
| [SergiioB/intel-arc-pro-b70-inference-cookbook](https://github.com/SergiioB/intel-arc-pro-b70-inference-cookbook) | 2026-08-06 | Arc Pro B70 | dense 27B (exact model not stated), Q4_K_M | llama.cpp (build/backend not stated) | not stated | n/d | 1007 | 23 | date is leaderboard approval date not run date; 230W; repo stars 0 |
| [PMZFX/intel-arc-pro-b70-benchmarks](https://github.com/PMZFX/intel-arc-pro-b70-benchmarks) | 2026-04-21 | Arc Pro B70 | Qwen3.5-27B, Q4_K_M | llama.cpp SYCL commit ec6f7a6a5c | none | pp512 | 718 | 20.4 | date = build date; Q8_0 776/15.3; Q6_K 785/15.1; repo stars 79 |
<!-- peers-table:end -->
