# Acceptance test specification

**Scope:** this is a *reproducible acceptance test* on one fixed contract. It is **not** a hardware-wide minimum-throughput guarantee. Throughput depends on content (DFlash acceptance), context depth, driver and desktop load.

## A. Fixed sustained comparison (throughput contract — unchanged from current practice)
- Same binary, model, draft and flags as production. One variable changes per A/B. Governor profile MAX, with the RAM-cache setting recorded.
- Seeds 4242, 4243, 4244; temperature 0.2 (record the *effective* sampler after preset filtering); 2304 output tokens; thinking disabled; the same shallow prompt.
- Order: ABBA interleaved (A1 B1 B2 A2 per seed), with one warm-up generation discarded after each load.
- Record per run: native gen s; tokens (state whether the first token is excluded); rounds; drafted; accepted; **tokens/round; ms/round**; empty-draft steps; first-content s; wall s; finish reason; driver version; desktop state (displays/apps); free VRAM before/after (DXGI).
- **Pass (≥40 contract):** all 6 runs of the candidate ≥ 40.0 t/s, **and** mean ms/round improved over baseline by more than 2× the baseline's seed-matched spread, **and** acceptance (tokens/round) within ±3% of baseline. That last check rules out a "win" coming from content drift.
- **Stretch:** mean ≥ 45. "Approaching 50" requires ms/round ≤ ~101 at 5.03 tokens/round.
- **Fail / reject:** any run < baseline min, any correctness diff (below), or free VRAM below the governor reserve.

## B. Completed agentic coding tasks (the real objective)
- A fixed suite of ≥12 tasks with hidden tests (e.g. the existing 16-task suite noted in the pack: "16/16 agent tasks, 60.5 s"; that is unverified here). Each task runs through the **real MCP path**.
- Measure per task: `t_first_native_token`, **`t_first_visible_mcp_output`** (client-side timestamp when the MCP tool result or first streamed chunk reaches the agent), **`t_task_total`** (request → tests pass), number of turns, tool-call parse failures, continuation failures (truncation/finish=length mid-edit), and tests passed.
- **Pass:** tests passed ≥ baseline (no regression on any task), zero new tool-call parse failures, median `t_task_total` ≤ 0.95 × baseline, p90 not worse.
- **Correctness guard for engine changes:** greedy (temp 0, thinking off) output on 5 fixed prompts must be **token-identical** to the baseline engine for kernel-only changes. Speculative decoding is lossless under greedy verification. Any diff is a bug until explained.

## C. Desktop responsiveness and headroom (B60 drives the display)
During runs: record DWM frame time or a simple UI-latency probe, and dedicated/shared GPU memory. **Fail** if shared-memory spill grows (WDDM paging) or the governor's headroom alarms fire.
