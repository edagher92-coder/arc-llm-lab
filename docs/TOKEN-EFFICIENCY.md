# Token efficiency: keeping a local agent fast and inside its window

A local model on one GPU has one slot (`-np 1`) and a small context window. Every token an agent wastes is time you wait, and every token of overhead is room the task can't use. This page lists the settings the `claude-qwen` wrapper applies, what each one saves, how to measure it, and what we tried and rejected.

## Why it matters, with numbers from this repo

In [server-test.txt](../data/raw/server-test.txt) the first request on a 29,679-token conversation took **61.0 s** to read (489.9 tok/s). The three agent turns that followed each re-used the cached 29,680 to 36,633 tokens, read only about 3K new ones, wrote 400 tokens and took **17.5 to 19.0 s** each. Without prefix reuse every turn would cost about a minute. That is the whole game: keep the prompt prefix stable so the server can reuse it, and keep what you send small.

## What the Claude Code wrapper sets

`agents/claude-qwen.cmd` points Claude Code at the local server (`ANTHROPIC_BASE_URL`). The environment variables below are documented at [code.claude.com/docs/en/env-vars](https://code.claude.com/docs/en/env-vars); the defaults quoted are the ones that matter for a local model.

| Setting | Value here | What it saves or protects |
|---|---|---|
| `CLAUDE_CODE_MAX_CONTEXT_TOKENS` | live window: server context minus 8K, capped at `QWEN_CLIENT_CAP` (default 32768) | Claude Code compacts **before** the server could overflow. This is the one control that decides when compaction happens. |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS` | `8000` | For a model Claude Code doesn't know, the default is 32000, which on a 32K to 57K window reserves most of the window for output you will never use. |
| `BASH_MAX_OUTPUT_LENGTH` | `15000` | Default is 30000. A noisy command can no longer dump half the window into the conversation. |
| `MAX_MCP_OUTPUT_TOKENS` | `8000` | Default is 25000. Same reason, for MCP tool results. |
| `CLAUDE_CODE_ATTRIBUTION_HEADER` | `0` | Keeps the start of the prompt identical between requests so the server's prompt cache hits. |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | `1` | No background calls to a server that can only do one thing at a time. |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | the same local model | Claude Code uses its small model for background work. Pointing it at the loaded model avoids a second model being requested and swapped in. |
| `--system-prompt-file` | [agents/claude-local/LOCAL-SYSTEM.md](../agents/claude-local/LOCAL-SYSTEM.md) | A compact local system prompt instead of the standard one. See the note in [AGENTS.md](AGENTS.md#claude-code-claude-qwen) about what the "6.6K versus 19K" figures mean. |
| `--strict-mcp-config` with one MCP server | `agents/claude-local/mcp.json` | Only the servers you list load. See the note on MCP below. |
**Not set: `CLAUDE_CODE_AUTO_COMPACT_WINDOW`.** Its documented valid range is 100000 to 1000000, so the 32K to 57K windows used here are out of range; compaction is governed by `CLAUDE_CODE_MAX_CONTEXT_TOKENS`.

**Tested and not adopted ("v2", 2026-10-10):** `CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS=1`, `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`, `CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1` and `CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH=512`, together with a "definition of done" prompt rule. That run scored 93/100 at 1.13 tasks/min against 97/100 at 1.54 for the production wrapper, so the wrapper does not set them ([RELIABILITY.md](RELIABILITY.md)). Three of its tasks were disturbed by an accidental model swap, so this is not proof that each setting hurts on its own.

**MCP schemas load up front.** With a non-Anthropic base URL, Claude Code's MCP tool search is off, so every tool schema of every configured server is sent on every request. Keep the set small: this repo ships one server (context7) and makes browser tools opt-in. On a 32K window a large MCP server can cost more than the code you are editing.

## How prefix reuse works on this model

Qwen3.8-27B is a hybrid model: 16 blocks of three Gated DeltaNet layers and one Gated Attention layer. It also loads a vision projector. That has two consequences for caching:

- **`--cache-reuse` does nothing here.** The server says so at start-up: `cache_reuse is not supported by multimodal, it will be disabled` ([server-57344.log](../data/raw/server-57344.log), line 27). The governor still passes `--cache-reuse 256`; it is inert, and it is harmless.
- **Reuse comes from two other mechanisms**, both on by default: a host-RAM prompt cache (`--cache-ram`, default 8192 MiB; the governor passes `-cram` 8192 / 4096 / 1024 for the MAX / BALANCED / LEAN profiles) and context checkpoints (`--ctx-checkpoints`, default 32, spaced at least `--checkpoint-min-step` 8192 tokens apart). These are documented in llama-server's README for b11524.

So the rule for any client is: **append, don't rewrite.** Anything that changes the early part of the prompt (a timestamp, a re-ordered tool list, a rewritten memory block) makes the server re-read from that point. That is why the attribution header is switched off. For tool-heavy clients the same rule decides how tools should be loaded: see [TOOL-CALLING.md](TOOL-CALLING.md).

**Open WebUI** has the same trap: its background features (titles, tags, follow-up suggestions, autocomplete, query generation, memories) send extra requests to the one slot and disturb its cache. [PLATFORM.md](PLATFORM.md) lists the settings that turn them off.

## Sampling

The Qwen3.8 model card recommends these settings. The presets in [llama-swap/config.yaml](../llama-swap/config.yaml) are close to the card but not identical, as noted below.

| Mode | temperature | top_p | top_k | min_p | presence_penalty |
|---|---|---|---|---|---|
| Thinking | 1.0 | 0.95 | 20 | 0 | 0 |
| Non-thinking | 0.7 | 0.8 | 20 | not set | 1.5 |

Our `:code` preset (thinking off) uses temperature 0.7, top_p 0.8, top_k 20 and a presence penalty of **0.5** rather than the card's 1.5. The default and `:plan` presets (thinking on) use temperature 0.6, top_p 0.95, top_k 20 and no presence penalty, so their temperature is below the card's 1.0. We did not benchmark these differences, so treat them as tunables.

The card also describes a reasoning effort of `xhigh` (the default), `medium` or `low`, with a warning that lower effort can increase retries. For an agent a retry costs more than the thinking it saved.

## How to measure

llama-server exposes Prometheus counters at `/metrics` when started with `--metrics` (the governor does this). Three matter:

| Counter | Meaning (from the server source) |
|---|---|
| `llamacpp:prompt_tokens_total` | Prompt tokens **processed**, excluding cached tokens |
| `llamacpp:prompt_tokens_cached_total` | Prompt tokens **reused from the cache** |
| `llamacpp:tokens_predicted_total` | Tokens generated |

Take a reading before and after a task and subtract. The share of the prompt served from cache is `cached / (processed + cached)`.

```powershell
function M($n) { ((Invoke-RestMethod http://127.0.0.1:10001/metrics) -split "`n" | Where-Object { $_ -like "llamacpp:$n *" }) -replace '.* ', '' }
$a = [double](M 'prompt_tokens_total'), [double](M 'prompt_tokens_cached_total'), [double](M 'tokens_predicted_total')
# ... run your agent task ...
$b = [double](M 'prompt_tokens_total'), [double](M 'prompt_tokens_cached_total'), [double](M 'tokens_predicted_total')
"processed {0}, reused {1}, generated {2}" -f ($b[0]-$a[0]), ($b[1]-$a[1]), ($b[2]-$a[2])
```

Port 10001 is the default variant's backend in [llama-swap/config.yaml](../llama-swap/config.yaml); the governor's `running.json` names the live port. The evaluation harness already does this for every task and stores `srv_prompt_tok`, `srv_cached_tok` and `srv_gen_tok` ([evalsuite/runner.py](../evalsuite/runner.py)), so the numbers are in the results files.

The honest caveat: we have not published a before/after comparison for each individual setting above. The 61 s versus 18 s figure is the measured effect of prefix reuse; the per-setting savings are mechanisms, not measurements. If you measure one, [share it](https://github.com/edagher92-coder/arc-llm-lab/issues/new?template=benchmark.yml).

## What we rejected, and why

- **A quantised main KV cache (q4_0 or q8_0).** It saves VRAM, but Intel's FA prefill kernel only sped up the f16 cache in our tests: with q4_0 the prompt speed at 32K was identical to stock (101 versus 101 tok/s, [compare-q4.txt](../data/raw/compare-q4.txt)). We measured q4_0; we did not benchmark q8_0 for the main model. The *drafter's* KV can stay q8_0 (`-ctkd q8_0 -ctvd q8_0`). Together with `-ub 256` it freed about 0.55 GiB at no speed cost ([tune.txt](../data/raw/tune.txt)), which is the difference between 57K and 64K of context.
- **Stacking an n-gram speculative method next to DFlash2.** Upstream's [speculative decoding docs](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md) say: "If a draft model is combined with a draftless decoding the draftless decoding has higher precedence." So adding an n-gram type would replace the drafter rather than add to it. We did not benchmark it.
- **Turning thinking off, or the reasoning effort down, for all agent work.** The model card warns that lower effort can increase retries, and for an agent a retry costs more than the thinking it saved. We use thinking-off in one place only: the `:code` preset, for routine tool loops with a short, checkable outcome. `:plan` asks for a 16K thinking budget for architecture and migrations, but the server starts with `--reasoning-budget 4096`; whether the preset's larger request overrides that cap has not been verified. There is no thinking-on versus thinking-off comparison on the same tasks in this repo, so treat this as a judgement, not a measurement.
- **A repetition penalty.** The model card recommends a presence penalty, not a repetition penalty, and a repetition penalty can punish code for legitimately repeating identifiers. We did not benchmark it.
- **More draft tokens (`--spec-draft-n-max 15`).** The upstream DFlash example uses 15; on a 24GB card with a 27B model it left 0.96 GiB of VRAM free and generation fell to 27 tok/s ([tune.txt](../data/raw/tune.txt)); draft length and free VRAM changed together, so we can't say which caused it. n=7 is the setting we use.
