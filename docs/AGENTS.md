# Claude Code and Codex on a local Arc model

Both CLIs work against the local server with no cloud calls. The wrappers in [agents/](../agents/) handle the details. Copy them to `%USERPROFILE%\bin`, put that folder on PATH, and set `LOCAL_QWEN_KEY`.

## Claude Code: `claude-qwen`

Claude Code talks to llama-swap's Anthropic-compatible `/v1/messages` endpoint.

- **FAST mode (default).** `--system-prompt-file agents/claude-local/LOCAL-SYSTEM.md` replaces Claude Code's standard system prompt with a compact one (1,118 bytes, about 1.1 KB, [LOCAL-SYSTEM.md](../agents/claude-local/LOCAL-SYSTEM.md)), keeping the full core toolset (`Bash, Read, Edit, Write, Glob, Grep, WebFetch, Agent, TodoWrite`). Every turn re-sends the system prompt, so a small one matters for local speed.
  - **What "6.6K versus 19K" means.** The "6.6K-token" figure is the observed *total fixed prefix* of a request in FAST mode (our system prompt plus the tool definitions Claude Code adds), and about 19K was the same measurement with the standard prompt. It is **not** the size of `LOCAL-SYSTEM.md`, which is only about 1.1 KB. We measured both numbers during development and did not keep the raw log, so treat them as approximate. To re-measure on your setup, restart the server, send one trivial prompt through `claude-qwen`, and read the processed prompt tokens from the server's `/metrics` counter `llamacpp:prompt_tokens_total` (method in [TOKEN-EFFICIENCY.md](TOKEN-EFFICIENCY.md#how-to-measure)).
- **Live window.** The wrapper asks `qwen window` for the server's current context and subtracts 8K of headroom. It caps that at `QWEN_CLIENT_CAP` (default 32768) and passes the result as `CLAUDE_CODE_MAX_CONTEXT_TOKENS`, so Claude Code compacts before the server could overflow. (v1 also set `CLAUDE_CODE_AUTO_COMPACT_WINDOW`; v2 removes it because its documented range starts at 100000, above any window used here.)
- **Output caps.** `CLAUDE_CODE_MAX_OUTPUT_TOKENS=8000`, `BASH_MAX_OUTPUT_LENGTH=15000`, `MAX_MCP_OUTPUT_TOKENS=8000`.
- **Stable prompt prefix (v2).** `CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS=1`, `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`, `CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1` and `CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH=512` keep the start of every request identical and small, so the server's prompt cache keeps hitting. The full list with what each one saves is in [TOKEN-EFFICIENCY.md](TOKEN-EFFICIENCY.md).
- **Separate config dir** (`CLAUDE_CONFIG_DIR`), so your cloud Claude Code settings, hooks and plugins don't load into the small context.
- **Avoid:**
  - `--bare` leaves only 3 tools.
  - `ENABLE_TOOL_SEARCH` loops with llama.cpp.
- **Options:**
  - `set QWEN_MODEL=qwen3.8-27b:plan` for deep thinking.
  - `set QWEN_FULL=1` for the standard prompt.
  - `set QWEN_BROWSER=1` for Playwright browser tools. This repo does **not** ship `mcp-browser.json`: browser tool schemas are large and load on every turn, so create `C:\AI\claude-local\mcp-browser.json` yourself (same format as [mcp.json](../agents/claude-local/mcp.json)) if you want it. Without the file the wrapper prints a notice and carries on without browser tools.

## Codex: `codex-qwen`

Codex talks to `/v1/responses`. Merge [agents/codex-qwen.config.toml](../agents/codex-qwen.config.toml) into your Codex config as profile `qwen`, with a `model_providers.qwen-b60` block pointing at `http://127.0.0.1:8090/v1`.

- **Live window** with compaction at 85%.
- **Disable heavy or cloud MCP servers** for the local profile: list them in `MCPOFF` in the wrapper (`-c mcp_servers.<name>.enabled=false`). Every enabled server's tool schemas ride along on every request; on our runs Codex's fixed prompt prefix was about 15.8K tokens against about 6.5K for Claude Code.
- **Windows sandbox gotchas** (each cost us hours):
  - Codex's sandbox can't grant itself access to an admin-owned `C:\Temp`, so the wrapper points `TEMP`/`TMP` at `%LOCALAPPDATA%\Temp`.
  - The sandbox runs commands as a separate `CodexSandboxUsers` account. If Python is installed per-user (under `%LOCALAPPDATA%`), that account can't see it, and every "run the tests" step fails. Codex then burns minutes hunting for an interpreter. In our smoke test the same fix took 314 s instead of 41 s. Fix, run once in your own PowerShell:
    ```
    icacls "$env:LOCALAPPDATA\Python" /grant "CodexSandboxUsers:(OI)(CI)RX" /T /C /Q
    ```
    or install Python for all users.
  - `--full-auto` isn't accepted by `codex exec`. Use `-s workspace-write -c approval_policy="never"`.

## Presets (same loaded model, no reload)

| Model name | Use | Behaviour |
|---|---|---|
| `qwen3.8-27b:code` | Agent loops, refactors, tests | No thinking, temp 0.7, top_p 0.8, presence penalty 0.5 |
| `qwen3.8-27b:plan` | Architecture, migrations, specs | Thinking on, 16K budget |
| `qwen3.8-27b:vision` | Screenshots, charts, documents | Short thinking (1K) |
| `qwen3.8-27b` | General chat | Thinking capped at 2K |

A server-wide `--reasoning-budget 4096` stops runaway thinking with "Give the final answer now".

## Other clients

Continue, Cline, Cursor, Open WebUI or anything OpenAI-compatible: use base URL `http://127.0.0.1:8090/v1`, your key, and model `qwen3.8-27b:code`.
