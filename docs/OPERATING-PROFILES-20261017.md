# B60 throughput recovery and desktop coexistence — 17 October 2026

A dated maintainer report from one Windows 11 / Intel Arc Pro B60 24 GB workstation: ThinkingCap-Qwen3.8-27B Q4_K_M, llama.cpp Vulkan/Intel flash attention, DFlash2 draft model. Two local batches are covered: throughput recovery and conservative AUTO admission. These are not new model versions or a new tagged repository release.

**Evidence boundary:** these are maintainer-recorded synthetic-request observations. Full per-request response JSON and deterministic seeded quality trials were not retained with this public addendum. They are not an independently reproduced benchmark dataset. Existing benchmark tables remain unchanged because the methodologies differ.

## 1. Measured recovery — context trade-off included

The same existing `merge_intervals` request asked for strict validation, non-mutation, three pytest tests and complexity. Output cap 700; temperature 0.6, top-p 0.95, top-k 20, thinking off. Tokens/s is native server `predicted_per_second`, not prefill or accepted-task throughput.

| Observation | Native context | Output tokens | Generation tokens/s | Request wall time |
| --- | ---: | ---: | ---: | ---: |
| Before recovery | 53,248 | 700 | 22.16 | 33.2 s |
| Reload alone, repeat | 53,248 | 700 | 21.80 | 32.5 s |
| Larger sizing reserve / smaller context, warm-up | 32,768 | 700 | 46.61 | 15.7 s |
| Same request, repeat | 32,768 | 700 | 50.21 | 14.3 s |
| Follow-up after GPU process-attribution repair | 32,768 | 700 | 45.84 | 16.0 s |

Before versus measured repeat: **126.6% higher generation rate; 56.9% less request time**. Native context was **38.5% smaller**. Cache reuse, desktop allocation and non-deterministic output are confounders; this does not isolate one causal variable. Reloading alone did not recover speed in this observation.

A different `parse_duration` coding request exposed competing GPU residency:

| Same request | Output tokens | Generation tokens/s | Wall time |
| --- | ---: | ---: | ---: |
| Second idle Ollama model resident | 862 | 22.1999 | 39.61 s |
| After explicitly unloading that idle model | 799 | 52.6590 | 15.49 s |

That is **137.2% higher generation rate and 60.9% less wall time**, but output length/cache state differ. Generated code was not executed for this comparison: performance evidence, not correctness. The client that later reloaded the competing model was not identified.

**Productivity:** response latency improved on these requests. No percentage gain in completed projects, accepted tasks/hour, cost per accepted task or developer productivity is established. Tokens/s cannot be converted directly into those claims.

## 2. Conservative local AUTO behavior

The locally tested controller now requires all of these for AUTO MAX:

- At least 600 seconds without keyboard/mouse input and four consecutive qualifying samples.
- Valid readings: available RAM >=10 GB, competing dedicated GPU allocation <0.75 GiB, total CPU <25%.
- Windows SMTC media reported inactive. Playing/Changing/Opened, failed, unknown and timed-out observations veto MAX. Some applications do not register playback with SMTC.

BALANCED is the ordinary desktop profile; existing persistent-pressure LEAN and explicit manual overrides remain. Profile names are not speed guarantees. Optional BALANCED-to-MAX resizing predicts the loaded variant's calibrated context before unloading. Unknown/non-growing targets and insufficient recent-session-plus-8,192-token headroom veto it. Existing request, protected-load, quiet-time and reload-rate guards remain. MAX-to-BALANCED does not reload merely to change priority.

A fresh check at the actual prewarm dispatch boundary covers delayed retries and shutdown waits. This fixes a discovered stale-decision bug: MAX could otherwise start after the user returned or media began during the wait. OFF and unknown mode/profile veto queued warm-ups. Mocked integration tests exercise actual production function/branch bodies rather than separate policy copies.

The 3 GiB margin is a **launch-sizing target**, not a continuously guaranteed free-memory floor; minimum context/session preservation may constrain sizing. Windows-native monitor sleep remains in use. The resolution-changing helper was left disabled: changing resolution is not turning monitors off.

## Verification and public-source boundary

- Local governor: **190 passed / 0 failed** under PowerShell 7 and **190 / 0** under Windows PowerShell 5.1, both exit 0.
- Separate local gateway completion/local-LLM/Studio suite: **52 passed**. Truncated/malformed replies fail instead of being marked complete; tool arguments require verified tool-call completion.
- Independent review found the stale-prewarm defect, then accepted the repaired frozen source. Governor-only activation preserved the model/cache; readback was AUTO/BALANCED, ready, 32,768 context, no degraded state/loop errors.
- Completion-guard source is tested; persistent gateway clients still require safe reconnection before adoption can be claimed.

**This commit publishes a report, not a private-runtime export.** Repository governor/gateway source is not claimed to match the local revision. The 190/52 checks are not newly available public test commands. A separately sanitized, compatibility-tested source port is required before these controls can be advertised as an installable repository release. Do not overwrite configuration from this report.

Reviewed local governor SHA-256: `3A5631FD2080B00DF07D67AF5FA07B8470266F8CDA21915C68E4E9579268DAB4`; regression script: `3A65920B6A03B38D8EDADE7A73F8F150721EE806D044DD42B3C59570B0C3ADA0`. Hashes identify assessed artifacts; they do not make unpublished source reproducible.

## Remaining limits and reproduction

Current native window **32,768**, client budget **24,576** after an 8,192-token reserve. **50–60K without performance/quality loss is not qualified.** KV compression changes memory use, kernel behavior and potentially quality. No larger-context benchmark completed in this batch; AUTO itself has no newly measured speed gain.

Use the existing [benchmark contribution procedure](../CONTRIBUTING.md) for public results. Retain full machine-readable output, exact engine/model hashes, context/KV formats, prompt/cache state, competing GPU load, output length, latency, quality checks and repeated runs. Separate prefill, decode and complete accepted-task time. Do not generalize one workstation's results to other Arc cards.
