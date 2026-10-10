# Contributing

The most valuable contributions are **measurements from other Intel GPUs** (A770, A750, B580, B570, B50, B60, B70, Lunar Lake and Battlemage iGPUs) and **other models**.

## Send a benchmark result (about 5 minutes)

1. Build or download a llama.cpp Vulkan `llama-bench` (our patched build is described in [docs/INTEL-FA.md](docs/INTEL-FA.md)).
2. Run `bench/arc-bench.ps1` (Windows) or `bench/arc-bench.sh` (Linux). It runs `llama-bench` at 0, 16K and 32K depth, writes a result file that follows [data/community/schema.json](data/community/schema.json), and prints a table row plus the link to the form.
3. Open the [benchmark result form](https://github.com/edagher92-coder/arc-llm-lab/issues/new?template=benchmark.yml) and paste the JSON and the raw `llama-bench` output. Or open a pull request that adds the JSON to `data/community/`. Your name goes on it if you want credit.

New to this? Try [Test on my card](https://github.com/edagher92-coder/arc-llm-lab/issues/new?template=test-my-card.yml) or pick one of the [good first issues](docs/GOOD-FIRST-ISSUES.md). Found a mistake? Use the [bug form](https://github.com/edagher92-coder/arc-llm-lab/issues/new?template=bug.yml).

## Rules that keep this repo trustworthy

- Every number needs raw output (llama-bench, server log or `qwen bench`). No raw log, no table row.
- Say what changed between runs: one variable at a time.
- Say what you ran: build, commit, driver, OS, flags. The community schema asks for all of these.
- Quality counts as much as speed: include the coding and tool-call check results (`bench/eval.py`) when you change sampling, quantisation or drafters.
- Mark estimates as estimates.

## Code

Pull requests are welcome, especially Linux versions of the governor and wrappers, SYCL comparisons, and more evaluation tasks (each needs a hidden checker plus a reference solution, so `cd evalsuite && python selftest.py --ci` stays at SELFTEST OK). Generated files (`docs/COMMUNITY-RESULTS.md`, the tables in `docs/PEERS.md`, `docs/index.html`) come from `tools/build_tables.py` and `tools/build_site.py`; edit the data or the script, then re-run them.
