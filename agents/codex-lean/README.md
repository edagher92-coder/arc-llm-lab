# Lean Codex home (opt-in)

Codex sends its whole start-up context with every request: plugins, MCP servers, the global `AGENTS.md` and skills. On a 32–40K local window that is expensive. Pointing `CODEX_HOME` at a separate, minimal home removes it. Your normal `%USERPROFILE%\.codex` stays untouched.

**Measured on 17 October 2026** with llama-server `/metrics`, asking "Reply OK" in an empty project:

| Setup | Start-up prompt | First turn |
|---|---:|---:|
| Normal `~/.codex` with the `qwen` profile | 12,235 tokens | 33 s cold |
| This home, stock Codex instructions | 7,150 tokens | — |
| This home with `instructions-compact.md` | **3,010 tokens** | 8 s cold, 1.6 s cached |

**Not yet measured:** this setup has not been run on the [100-task eval](../../evalsuite/). The compact instructions replace Codex's stock system prompt, so quality could differ. To keep the stock prompt, comment out `model_instructions_file` in `config.toml` (about 4.9K tokens).

## Install (Windows)

1. Copy `config.toml` and `instructions-compact.md` to `C:\AI\codex-local\home\`.
2. Put `codex-qwen-lean.cmd` on your `PATH`. It sets `CODEX_HOME`, reads the live window from `qwen window` (the loaded context minus 8K), and compacts at 75% of it.
3. Make sure `LOCAL_QWEN_KEY` is set (the same key llama-swap uses).

Codex writes six system skills into any new `CODEX_HOME`. `config.toml` switches them off. A short list of `~/.agents/skills` (about 700 tokens) is still injected, because Codex reads that directory from the user profile.

Known protocol gaps between Codex and llama-server are listed in [docs/CODEX-COMPAT.md](../../docs/CODEX-COMPAT.md).
