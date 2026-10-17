# Codex and Claude Code against llama-server: what works

On 15 October 2026 we ran 26 request types against the live stack. The stack was llama-swap → llama-server b11526 (Intel FA build), ThinkingCap-Qwen3.8-27B Q4_K_M with the DFlash2 drafter, the [custom chat template](../governor/qwen38-template.jinja) (qwen3-coder XML tool format), `--jinja --no-context-shift`, and a 40,960-token window. Unless noted, tests used the `qwen3.8-27b:code` preset (thinking off). Every row is a real request.

## The short version

| Feature | `/v1/chat/completions` | `/v1/responses` |
|---|---|---|
| `tool_choice: "auto"` | Works | Works |
| `tool_choice: "required"` when the prompt doesn't need a tool | **Not enforced** (tool call 1/4) | **Not enforced** (0/4) |
| Named `tool_choice` (force one function) | **Silently ignored**, no warning | **Silently ignored**, both shapes |
| `response_format` json_schema (strict) | Enforced, even against an adversarial prompt | — |
| `text.format` json_schema / json_object | — | **Ignored** |
| Top-level `response_format`, `json_schema` or `grammar` | Enforced | **Enforced** (the workaround for `text.format`) |
| GBNF `grammar` | Enforced | Enforced (top level) |
| `parallel_tool_calls` | Honoured | Honoured |
| Tool types `custom` (freeform apply_patch), `web_search`, `local_shell` | — | Accepted, then **dropped** |
| Output cap reached | `finish_reason: "length"` | **`"completed"`**, truncated text, no `incomplete_details` |
| Tool-argument JSON (22 calls with backslashes, nested quotes, `\n`, Unicode) | 22/22 valid | 22/22 valid |
| Reasoning, thinking on | Clean `reasoning_content`, no `<think>` text | Separate reasoning item, no `<think>` text |

Two side effects:

- With `required` and thinking off, a literal `</think>` leaked into the content in 2 of 4 runs.
- With thinking on and a tight output cap, one run spent all 1,200 tokens reasoning and returned no message.

## What to do about it

- **When a tool call is required:** treat a prose answer as a retry. Don't count on the server to force the call.
- **When you need schema output on `/v1/responses`:** send a top-level `response_format`, not `text.format`.
- **When you hit the output cap on `/v1/responses`:** check the text yourself. `"completed"` doesn't mean the answer finished.
- **For agent loops:** use the `:code` preset (1.7–5.3 s turns in these tests) rather than the thinking preset (5–40 s).
- **For Codex:** use the [lean Codex home](../agents/codex-lean/README.md) to cut the start-up prompt from 12,235 to 3,010 tokens.

## Prefix caching

Agent-style requests with a 10,872-token system prompt and 2 tools, on the `:code` preset:

| Request | First token | Prompt work | Generation |
|---|---:|---|---|
| Cold, unique prefix | 22.3 s | 10,872 tokens at 498 tok/s | 37.7 tok/s |
| Same request again | 0.50 s | 4 new tokens (10,868 cached) | 28.7 tok/s |
| Same system prompt, new user turn | 0.87 s | 33 new tokens | 29.0 tok/s |
| Same, via `/v1/responses` stream | 0.98 s | 10,820 cached | 111 tokens in 3.6 s |

A verbatim 1,065-token copy ran at 53–56 tok/s, byte-exact 3 of 3 times; the drafter accepted 931 of 931 tokens. Copy-heavy output is where the drafter shines.

## Open questions

- Codex sometimes prints an "ignored forced-tool parameter" warning. No llama-swap or llama-server response contains one, so it probably comes from Codex itself or the tool gateway after a named `tool_choice` went unobeyed (inferred).
- Third-party guides say Codex has dropped `wire_api = "chat"`; `responses` works here (inferred, not checked against OpenAI's docs).
