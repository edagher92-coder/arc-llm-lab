# Reasoning policy (Section E)

## Server facts at the revision (tools/server/server-common.cpp, b11524 lines ≈ recon)
1. Request `chat_template_kwargs` is merged per key over the CLI `--chat-template-kwargs` (L1400-1404).
2. Nested `enable_thinking` must be a JSON boolean; a quoted string is rejected (L1407-1414).
3. **Top-level `reasoning_effort` overwrites nested `chat_template_kwargs.reasoning_effort`** (L1417-1425). `"none"` also forces `enable_thinking=false`. Any other value does **not** turn thinking on.
4. Budget = `reasoning_budget_tokens`, else `thinking_budget_tokens`, else **CLI `--reasoning-budget` when the result is -1** (L1458-1462). An explicit `-1` from the caller cannot be told apart from "omitted". The budget only applies when the template exposes thinking end tags (L1464).
5. Anthropic `/v1/messages`: `thinking.type=enabled` without `budget_tokens` defaults to **10000** (server-chat.cpp ~L600-606). Responses API `reasoning.effort` maps to `reasoning_effort` (server-chat.cpp ~L300-306).
6. Effort levels supported by the ThinkingCap template (low/medium/xhigh; high→xhigh) come from the user's statement. **Not verified on the box: I don't have the template.**

## Policy (caller wins, then route default, then global default; the gateway never escalates silently)
- **Code/MCP route:** default `enable_thinking=false`. A caller-supplied explicit `enable_thinking=true` is honoured. Effort alone never turns thinking on (matches server semantics).
- **general/plan/vision:** if effort is omitted, use `medium`/`medium`/`low` (never `xhigh`). Escalate to `xhigh` only when the caller asks.
- **Emit one canonical form:** nested `chat_template_kwargs.{enable_thinking, reasoning_effort}`, no top-level effort (so nothing can clobber the nested value), and an explicit integer `reasoning_budget_tokens` whenever thinking is on.
- **Reject conflicts** (top vs nested effort, `reasoning_budget_tokens` vs `thinking_budget_tokens`, `effort=none` + `enable_thinking=true`, string booleans, unknown efforts) with HTTP 400, rather than following the server's silent overwrite. `conflict_policy="server"` is available for compatibility.
- **Sampling presets:** record the *effective* temperature/top_p/top_k/presence in response metadata. Don't silently replace caller-sent values. The current 0.2 → 0.7 code-preset override is real, and Qwen's non-thinking guidance is 0.7, but it is not shown to cause slowdown. Deciding which value wins is a product decision that needs a quality A/B, not a speed claim.
- **Visible latency:** the MCP helper buffers the whole response, so native TTFT (0.864 s) is not what the user sees. Streaming natively is the only fix. Consuming SSE internally and returning once does not help. Measure `t_first_visible_mcp` separately (acceptance_test_spec.md).

## Precedence tests required before integration
`tests/precedence_matrix.csv` has 22 request shapes with their expected resolved (enable_thinking, effort, budget, error). `tests/test_reasoning_resolver.py` runs them against `tools/reasoning_resolver_UNTESTED.py`, plus 5 regression tests that **demonstrate the pack router's defects**. On the box: **27/27 pass** (`tests/test_run_output.txt`). That is a unit test of the reference logic only.

Integration tests still required (not run here):
1. For each matrix row, send the resolved body to the live llama-server (`/apply-template` or a `max_tokens=1` request) and assert that the rendered prompt has / lacks the think-prefix and shows the expected effort.
2. Budget enforcement: thinking on with budget 64 → assert reasoning tokens ≤ 64 + end tag.
3. No-thinking code mode: 20 MCP coding requests, assert zero reasoning content.
4. Governor interplay: the AUTO/MAX/BALANCED/LEAN profiles must not change the resolved fields.
