---
name: kimi-code
description: Launch or explain a Claude Code session backed by a Kimi model (K3 Max when available, kimi-k2.7-code today) through Ollama's Anthropic-compatible API — zero Claude quota, flat-rate Ollama Cloud. Use when Elie says "kimi in claude code", "kimi session", "link kimi k3", "run claude on kimi", or asks to code with Kimi. NON-STAKES ONLY (NUMBERS RULE).
---

# Kimi-backed Claude Code (via Ollama)

Ollama >= 0.14 serves the **Anthropic Messages API**, so the real Claude Code
CLI can run against any Ollama model. The launchers in `.claude/tools/`
(`kimi-code.sh` / `kimi-code.ps1`) point Claude Code at the local daemon and
pick the best Kimi tag — **preferring `kimi-k3*` automatically the moment it
lands on Ollama Cloud (~2026-07-27)**, falling back to `kimi-k2.7-code:cloud`
(the current bench clean-sweeper for code). `:cloud` tags proxy through the
signed-in daemon to Ollama Cloud — flat rate, **zero Claude quota**.

## One-time setup per machine (laptop + server PC — both already signed in)

PowerShell (run once; adds a `kimi` command):

```
Add-Content $PROFILE "`nfunction kimi { & `"`$HOME\.claude\tools\kimi-code.ps1`" @args }"
. $PROFILE
```

Then from any terminal:

```
kimi                      # best Kimi (auto-upgrades to K3)
kimi kimi-k2.5:cloud      # explicit tag
kimi -List                # show available Kimi tags
```

(macOS/Linux: `alias kimi='bash ~/.claude/tools/kimi-code.sh'` in ~/.bashrc.)

The tools land on both machines via the father sync (`.claude/tools/` in every
repo) or `bootstrap.ps1`. A laptop without its own daemon can use the server
hub: `$env:CLAUDE_KIMI_OLLAMA_URL = 'http://elzydlab.tail76b098.ts.net:11434'`.

## Hard rules

- **NUMBERS RULE:** a Kimi session is for heavy NON-stakes work — bulk coding,
  refactors, drafts, research digests. Customer prices, quotes, invoices, and
  legal content stay in a real Claude session (Sonnet/Opus/Fable). Kimi output
  is never final authority on anything customer-facing.
- This runs the **model** through Ollama, not Anthropic — Ollama's
  Anthropic-compat has gaps (no prompt caching, approximate token counts,
  no tool_choice enforcement, base64-only images). Expect a capable but not
  identical Claude Code experience.
- Escalation still applies: if Kimi flails on a task, bring it back to a
  Claude-backed session rather than retrying the same losing config.
