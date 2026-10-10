# Claude Code and Codex on a local Arc model

Both CLIs work against the local server with no cloud calls. The wrappers in [agents/](../agents/) handle the details. Copy them to `%USERPROFILE%\bin`, put that folder on PATH, and set `LOCAL_QWEN_KEY`.

## Claude Code: `claude-qwen`

Claude Code talks to llama-swap's Anthropic-compatible `/v1/messages` endpoint.

- **FAST mode (default).** `--system-prompt-file agents/claude-local/LOCAL-SYSTEM.md` replaces Claude Code's roughly 19K-token system prompt with a 6.6K-token one, keeping the full core toolset (`Bash, Read, Edit, Write, Glob, Grep, WebFetch, Agent, TodoWrite`). Every turn re-sends the system prompt, so this matters more than almost anything else for local speed.
- **Live window.** The wrapper asks `qwen window` for the server's current context and subtracts 8K of headroom. It caps that at `QWEN_CLIENT_CAP` (default 32768) and sets `CLAUDE_CODE_AUTO_COMPACT_WINDOW` to match, so Claude Code compacts before the server could overflow.
- **Output caps.** `CLAUDE_CODE_MAX_OUTPUT_TOKENS=8000`, `BASH_MAX_OUTPUT_LENGTH=15000`.
- **Separate config dir** (`CLAUDE_CONFIG_DIR`), so your cloud Claude Code settings, hooks and plugins don't load into the small context.
- **Avoid:**
  - `--bare` leaves only 3 tools.
  - `ENABLE_TOOL_SEARCH` loops with llama.cpp.
- **Options:**
  - `set QWEN_MODEL=qwen3.8-27b:plan` for deep thinking.
  - `set QWEN_FULL=1` for the standard prompt.
  - `set QWEN_BROWSER=1` for Playwright.

## Codex: `codex-qwen`

Codex talks to `/v1/responses`. Merge [agents/codex-qwen.config.toml](../agents/codex-qwen.config.toml) into your Codex config as profile `qwen`, with a `model_providers.qwen-b60` block pointing at `http://127.0.0.1:8090/v1`.

- **Live window** with compaction at 85%.
- **Disable heavy or cloud MCP servers** for the local profile (`-c mcp_servers.<name>.enabled=false`).
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
