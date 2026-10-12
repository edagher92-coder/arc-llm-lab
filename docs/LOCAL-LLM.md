# Local LLM delegation: `ask_local`

`ask_local` is an MCP tool on the local gateway. Claude Code or Codex can hand a cheap, private, low-stakes subtask to the Qwen 3.8 model on the PC (via llama-swap, no-thinking `:code` preset, temperature 0.2).

## Use it for
`task` is one of `summarise`, `classify`, `draft`, `rewrite`, `extract_noncritical`, `code` (write a function, test or script from a spec) or `review` (first-pass defect list for a diff). `code` and `review` get a built-in engineer/reviewer system prompt unless you pass your own. Typical: summarise a long log, classify a batch of notes, rough first draft, tidy wording. The answer is a **draft**: the caller must check it.

## Do not use it for
Money, pricing, quotes, invoices, refunds, tax/GST, legal, irreversible actions, customer-facing final copy, or critical extraction (names, amounts, dates, specs). Prompts matching a simple stakes regex (price, quote, invoice, refund, payment, AUD, `$` amounts, GST, legal, contract, tax) are refused with `status: "refused"`. The regex is a backstop, not a substitute for judgement.

## Result
JSON `{ok, status, text, model, elapsed_ms, note}`; `status` is `ok | paused | busy | timeout | error | refused`.
`paused` is returned immediately (no waiting) when the governor mode file reads OFF or a video job / ComfyUI session holds the GPU: do the task yourself or use the cloud tier.

## Config (existing `video.llm` block, nothing new required)
`swap_url`, `api_key_file`, `model_id` (the tool calls `<model_id>:code`; override with optional `ask_local_model`), `governor_mode_file`. The tool is listed in `policy.read` in `gateway.example.json`. Errors report only the exception class and HTTP status; the key is never logged or returned.

## Claude Code registration (`qwen_mcp.py`)
Claude Code reaches `ask_local` through a stand-alone MCP server that exposes only that tool (no other hub tools, no second video queue):
`claude mcp add qwen --scope user -e PYTHONIOENCODING=utf-8 -- C:\AI\gateway\.venv\Scripts\python.exe C:\AI\gateway\qwen_mcp.py C:\AI\gateway\gateway.json`
It reads the same `video.llm` block and returns `paused` while the governor mode is OFF or the hub's `state/video/gpu.lock` exists, so a render is never interrupted. The QWEN CODING PARTNER block in `~/.claude/CLAUDE.md` tells Claude when to call it.

## `claude-qwen` launcher
`C:\Users\<you>\bin\claude-qwen.v2.cmd` runs Claude Code entirely on Qwen through llama-swap's Anthropic-compatible `/v1/messages`. Anthropic does not support non-Claude models behind Claude Code, so treat it as unsupported: use it only for private/offline grunt work, not for anything that needs the cloud model's reliability.
