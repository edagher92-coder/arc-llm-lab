# Community benchmark results

One JSON file per run, written by [bench/arc-bench.ps1](../../bench/arc-bench.ps1) (Windows) or [bench/arc-bench.sh](../../bench/arc-bench.sh) (Linux) and validated against [schema.json](schema.json). The table in [docs/COMMUNITY-RESULTS.md](../../docs/COMMUNITY-RESULTS.md) and the community section of the [benchmark site](https://edagher92-coder.github.io/arc-llm-lab/) are generated from these files by `tools/build_tables.py` and `tools/build_site.py`.

## Add yours

1. Run the script for your card (examples in [CONTRIBUTING.md](../../CONTRIBUTING.md)). It runs `llama-bench -ngl 99 -fa 1 -ctk f16 -ctv f16 -p 2048 -n 32 -d 0,16384,32768 -r 1`, the same flags as [bench/compare-f16.ps1](../../bench/compare-f16.ps1) apart from `-lm dio` and the extra `pp8` test, and writes `<date>-<gpu>-<backend>-<build>.json`.
2. Open a [benchmark result issue](https://github.com/edagher92-coder/arc-llm-lab/issues/new?template=benchmark.yml) and paste the JSON, or add the file to this folder in a pull request.
3. Attach the raw `llama-bench` output (the script keeps it next to the JSON as `llama-bench-<stamp>.json`). A number without a log can't be checked, so it is not added to the table.

Check your file against the schema before you send it (needs `pip install check-jsonschema`, run from your copy of this repository):

```
check-jsonschema --schemafile data/community/schema.json your-result.json
```

`python tools/validate_repo.py` checks the whole repository (the same checks CI runs). It does not check a single result file.

## What the fields mean

| Field | Meaning |
|---|---|
| `gpu`, `vram_gb`, `driver`, `os` | The card, its memory, the driver version and the operating system. Edit `driver` by hand if the script could not detect it |
| `backend`, `llama_cpp_build` | `Vulkan`, `SYCL` or another backend, and the build number and commit that `llama-bench` printed |
| `patches` | Anything applied on top of that build: commit SHAs or names, one per entry. Empty for an unpatched build |
| `model`, `quant`, `kv_cache`, `flash_attn` | What was measured. Keep the KV cache type: the Intel FA prefill shader only helps with f16 |
| `depth_results` | For each context depth in tokens: `pp_tok_s` (prompt processing of `pp_tokens` tokens) and `tg_tok_s` (generation of `tg_tokens` tokens) |
| `flags`, `repeats`, `notes`, `raw_log_url` | The exact command, how many repeats, anything that helped or hurt, and a link to the raw output |

The numbers are `llama-bench` figures with no speculative decoding, so they are comparable between cards. They are not the agent-style numbers in the main README, which also use a draft model.

## Entries from the maintainer

| File | What it is |
|---|---|
| [2026-10-10-arc-pro-b60-24gb-vulkan-stock.json](2026-10-10-arc-pro-b60-24gb-vulkan-stock.json) | Arc Pro B60 24GB on stock llama.cpp b11524, from [compare-f16.txt](../raw/compare-f16.txt) |
| [2026-10-10-arc-pro-b60-24gb-vulkan-intel-fa.json](2026-10-10-arc-pro-b60-24gb-vulkan-intel-fa.json) | The same card on b11524 plus the two vendored Intel FA prefill patches, from the same log |

Both come from the maintainer's own run of [bench/compare-f16.ps1](../../bench/compare-f16.ps1), one run per cell, and were written by hand from that log, not by `arc-bench`.
