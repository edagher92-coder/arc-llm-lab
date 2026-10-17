# Roadmap: next experiments

Planned, **not yet run**. Each step has a pass/fail and a way back. The order matters: every later number depends on E0. Last updated 18 October 2026.

Rules for every step:

- One variable per run.
- Record the llama-server process's **dedicated and shared** memory with every tok/s figure ([how](FIELD-REPORT-20261018.md#1-dedicated-free-vram-is-not-a-real-fit)).
- Throughput claims use the fixed contract: seeds 4242–4244, temperature 0.2, 2,304 tokens, thinking off. Report tok/s, tokens per round and ms per round for each seed.
- A warm 300-token request is a smoke test, not acceptance.
- Scratch launches use another port and a scratch build directory. The production engine, weights and governor are not touched.

## E0: Real VRAM budget and the regression

The first step: no code changes, about 30 minutes.

1. **ECC, clocks, reboot.** Check the ECC toggle in Intel Graphics Software; the 12 October slowdown was ECC. If ECC is already off, read the GPU clock and temperature under load. If neither explains it, reboot.
   - **Pass:** warm decode ≥ 40 tok/s at a 36,864-token window with shared ≤ 0.1 GiB.
2. **Shared = 0 run.** Unload the model, close the browser, and launch the production command line at 32,768 tokens. Then step through 36,864, 40,960, 45,056 and 49,152, stopping at the first window where shared memory exceeds 0.2 GiB.
   - **Deliverable:** a five-row table of window, dedicated, shared and tok/s. That table *is* the per-process budget.
3. **Make the governor honour it.** Set the margin one step below the knee. Optionally, read `Shared Usage` in the governor itself and treat > 0.25 GiB after launch as a reason to refit down.

## E1: Where the 112 ms per round goes

No code changes, about an hour.

From the maintainer's trace: 2,304 tokens in 458 drafter rounds is 5.03 tokens and 133 ms per round. The draft timer accounts for 20.8 ms; one verify pass costs about 36–38 ms at the card's bandwidth. That leaves **about 74 ms per round unexplained**. Reaching 40 tok/s needs only −7 ms per round; 50 tok/s needs −32 ms (arithmetic in [research/dflash_timing_analysis.md](research/dflash_timing_analysis.md)).

Run one seed with `GGML_VK_PERF_LOGGER=1` and read per-graph GPU time for the verify, draft-inject and draft-decode graphs.

- **Pass:** GPU time ≤ 85 ms per round, so ≥ 25 ms is host or sync gap. Go to E2.
- **Fail:** GPU time ≥ 120 ms, so it is kernel time. Look at verify mat-vec efficiency instead.

## E2: Remove one per-round cost

Engine work in a scratch build; only after E1 passes.

Candidates, in order:

1. Skip the inject decode for positions that will be rejected (upstream `TAG_SPEC_AVOID_DRAFT_REEVAL`).
2. Drop a redundant `synchronize()`.
3. Merge inject and draft into one graph.

**Gate:** greedy output must be token-identical to the production binary, then run the three-seed contract. **Pass:** two of three seeds ≥ 40 tok/s, at least 7 ms per round saved, and no token differences.

An **untested** instrumentation diff is in [research/instrumentation_patch_UNTESTED.diff](research/instrumentation_patch_UNTESTED.diff).

## E3: A valid quantised-KV path

Engine work; only if E1 shows the draft's scalar flash attention is > 10% of draft time.

There are two routes:

- Dequantise q8_0 K/V to f16 onto the existing Xe shaders.
- Parametrise the cm1 flash-attention shader to the shape the driver actually enumerates.

Either would also make q8_0 **main** KV viable without the 57% cliff. That is the only honest route to 50–60K on this card. Researched only: [research/coopmat_reconciliation.md](research/coopmat_reconciliation.md).

## E4: Gateway, streaming and reasoning policy

No engine work.

1. Stream tokens from `ask_local` instead of buffering the whole answer. Today a cold 10.9K-token request shows nothing for 22 s.
2. Adopt one reasoning-parameter resolver: an omitted effort means medium, never `xhigh`, and the caller's temperature is kept. The **untested** resolver and its 22-row precedence matrix are in [research/](research/README.md). Its tests passed on the author's machine only, so it must be validated against the live server before use.
3. For Codex, use the lean home ([agents/codex-lean/](../agents/codex-lean/README.md)) and the workarounds in [CODEX-COMPAT.md](CODEX-COMPAT.md).

## E5: Memory the governor can't see

- Find the client that reloads a small Ollama model every 40–70 minutes, and set `OLLAMA_KEEP_ALIVE` to 5 minutes at machine scope. That returns up to 3 GiB at random times.
- The compositor holds 1.7–1.9 GiB with two 3440×1440 panels. A compositor restart and the MPO/HAGS toggles are untested.

What not to spend time on: [TRIED-AND-REJECTED.md](TRIED-AND-REJECTED.md).
