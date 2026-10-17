# Context lab, 17 October 2026

Raw output from one session on the maintainer's Arc Pro B60 24GB (Windows 11, Ryzen 7 3700X, 32 GB RAM), 16:08–17:05 local time, with the PC in normal use. Files are unedited, except that the per-process VRAM lists in the `baseline VRAM` lines were cut down to the adapter total, the free figure and the compositor (`dwm`). The application names and PIDs were removed.

**Conditions:** llama.cpp b11526 (`c85e6c598`), the Intel FA build (b11524 plus the [vendored patches](../../../engine/patches/)), `GGML_VK_FORCE_MMVQ=1`, `-t 8`, `--prio -1`, ThinkingCap-Qwen3.8-27B Q4_K_M. Single runs unless `r=3`.

| File | What it is |
|---|---|
| [kv-batch1.md](kv-batch1.md), [kv-batch2.md](kv-batch2.md) | `llama-bench -ngl 99 -fa on -lm dio -ub 256 -b 2048`, `pp512`/`tg32`, no drafter: f16 KV at depths 0, 16K and 32K; q8_0 KV at 0, 16K (batch 1) and 32K (batch 2) |
| [server-depth-f16.log](server-depth-f16.log), [server-depth-q8_0.log](server-depth-q8_0.log) | llama-server at ctx 40960 with the DFlash2 drafter (n_max 7, p-min 0.5, q8_0 draft KV): a 3,875-token prompt, then a 25,243-token prompt, 256 tokens generated each. The `print_timing` lines carry the numbers |
| [run.log](run.log) | Driver log for the whole session, including the 9-variant footprint sweep at ctx 32768 (`ded` = llama-server dedicated GiB, `shr` = its WDDM **shared** GiB, `free` = adapter free, `gen` = tok/s on a short request) |

**Two things to know before quoting these:**

- The `depth kv=…` lines in `run.log` near 16:56 are from an aborted first attempt: the long runs are empty. The depth figures come from the two `server-depth-*.log` files.
- `tg32` here (13.0 tok/s at depth 0) is about 19% below the 16.0–16.1 tok/s that the same kind of command gave on 12 Oct. That slowdown is an open issue ([field report](../../../docs/FIELD-REPORT-20261018.md#2-an-open-throughput-regression)), so compare these rows with each other, not with older tables.
