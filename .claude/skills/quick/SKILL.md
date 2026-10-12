---
name: quick
description: |
  [EFFICIENCY] Switch to token-saving mode for simple tasks — short responses,
  minimal reasoning, Haiku subagents. Use when the user says "quick mode",
  "save tokens", "be brief", "simple question", or types /quick.
---

# Quick Mode — Token-Saving Profile

You are now in **quick mode**. Apply these rules for the rest of this session
(until the user switches with `/deep` or `/balanced`):

## Response rules
- Keep responses under 3 sentences unless the user asks for more
- Skip extended thinking — answer directly
- No headers, tables, or markdown formatting unless the content demands it
- One tool call at a time — don't parallelize unless critical

## Subagent routing (cost-saving overrides)
When you need to spawn subagents (Agent tool), use these overrides:
- **Tier 3 — search, grep, lookups**: `model: "haiku"`, `effort: "low"`
- **Tier 2 — all code edits, single-file, repetitive work**: `model: "haiku"`, `effort: "low"`
- **Tier 1 — only multi-file architecture or security**: `model: "sonnet"`, `effort: "high"`
- Main session stays on Opus 5 / high (the pinned default) regardless of this mode

## What NOT to do
- Don't generate planning documents or analysis unless asked
- Don't read files you don't strictly need
- Don't explain what you're about to do — just do it
- Don't recap what you did — state the result in one line

Confirm the switch by saying: **Quick mode on. Responses will be short, subagents routed to Haiku.**
