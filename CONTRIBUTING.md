# Contributing

The most valuable contributions are **measurements from other Intel GPUs** (A770, A750, B580, B570, B60, Lunar Lake / Battlemage iGPUs) and **other models**. Use the [benchmark result form](../../issues/new?template=benchmark.yml).

Rules that keep this repo trustworthy:
- Every number needs raw output (llama-bench, server log or `qwen bench`). No raw log, no table row.
- Say what changed between runs - one variable at a time.
- Quality counts as much as speed: include the coding/tool-call check results (`bench/eval.py`) when you change sampling, quantisation or drafters.

Code PRs welcome, especially: Linux versions of the governor and wrappers, SYCL comparisons, and more evaluation tasks (each needs a hidden checker plus a reference solution so `evalsuite/selftest.py` stays at 0 failures).
