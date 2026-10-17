# Research: the engine, read from source

> **Researched, not run on the card.** Everything in this folder came from reading llama.cpp source and doing arithmetic on published numbers. It was prepared on 17 October 2026 by a separate model (Gemini) working from our logs and a reconstruction of the engine. No file here was executed on the B60. Code marked `UNTESTED` has never run against the live server. Measured results live in [../FIELD-REPORT-20261018.md](../FIELD-REPORT-20261018.md) and [../../data/](../../data/); use this folder for leads and reasoning, not for numbers.

**The engine studied.** Our build reports `c85e6c598`, which is not a public commit. The study reconstructs it as llama.cpp b11524 plus the two commits from PR #29357 that this repo vendors. Line numbers are therefore approximate. Where these files call PR #29357 *open*, see [../INTEL-FA.md](../INTEL-FA.md): we recorded it as closed without merging on 2026-09-25. That status was not re-checked for this import.

## What is here, and how far to trust it

| File | What it argues | Status |
|---|---|---|
| [REPORT.md](REPORT.md) | Verdict and three ranked interventions: gateway latency first, then DFlash per-round overhead, then a valid quantised-KV FA path | Researched |
| [dflash_timing_analysis.md](dflash_timing_analysis.md) | 133 ms per drafter round, about 74 ms of it unexplained; 40 tok/s needs only −7 ms per round. Also shows `--spec-draft-backend-sampling` is a no-op for DFlash2 | Researched; the trace numbers are measured |
| [coopmat_reconciliation.md](coopmat_reconciliation.md) | Why issue #30503 (coopmat shape gate) isn't on the main model's hot path, and the two valid routes to fast q8_0 K/V | Researched |
| [context_budget.md](context_budget.md), [tools/context_budget.py](tools/context_budget.py) | VRAM arithmetic per window size and KV type | Researched. Superseded in one respect: it budgets against the adapter total, and the 18 Oct measurements show a smaller **per-process** budget ([field report](../FIELD-REPORT-20261018.md)) |
| [tools/dflash_timing.py](tools/dflash_timing.py) | The per-round arithmetic behind the timing analysis | Runs offline (no GPU) |
| [instrumentation_patch_UNTESTED.diff](instrumentation_patch_UNTESTED.diff) | Per-bucket timers for the DFlash loop (roadmap step E1/E2) | **UNTESTED**, never compiled here |
| [reasoning_policy.md](reasoning_policy.md), [tools/reasoning_resolver_UNTESTED.py](tools/reasoning_resolver_UNTESTED.py), [tests/](tests/) | One precedence order for thinking/effort/budget parameters, a 22-row matrix and unit tests | **UNTESTED** against the live server. The unit tests pass offline: 22 passed, 5 skipped (the skipped ones compare against the rejected router, which isn't shipped) |
| [acceptance_test_spec.md](acceptance_test_spec.md) | How to A/B any change on visible latency and total task time | Proposal |
| [pack_defects_review.md](pack_defects_review.md) | Line-by-line problems in the outside optimisation pack | Researched; summarised in [../TRIED-AND-REJECTED.md](../TRIED-AND-REJECTED.md) |
| [sources.md](sources.md), [src/qwen35_27b_config.json](src/qwen35_27b_config.json) | Commits, issues and specs cited; the public model config used for KV arithmetic | Reference |

Run the offline pieces:

```bash
python docs/research/tools/dflash_timing.py
python docs/research/tools/context_budget.py
python -m pytest docs/research/tests -q
```

The outside "optimisation pack" these files review is **not** included. Its patch, build script and launcher were found to be defective, and nothing from it should be run ([../TRIED-AND-REJECTED.md](../TRIED-AND-REJECTED.md)).
