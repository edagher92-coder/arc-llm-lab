---
name: balanced
description: |
  [EFFICIENCY] Reset to balanced mode — Opus 5 main session (the pinned default), Haiku for search,
  Opus for escalation. Use when the user says "balanced mode", "reset mode",
  "default mode", "normal mode", or types /balanced.
---

# Balanced Mode — Default Profile (Reset)

You are now in **balanced mode** (the project default). This resets any
previous `/quick` or `/deep` override.

## Response rules
- Match response length to task complexity — short for simple, detailed for complex
- Sonnet 5 uses adaptive thinking — let the model decide when to reason deeply
- Structure with headers only when content has 3+ distinct sections

## Three-tier subagent routing
When you need to spawn subagents (Agent tool), use these defaults:
- **Tier 3 — search, grep, lookups**: `model: "haiku"`, `effort: "low"`
- **Tier 2 — single-file edit, bug fix, repetitive/everyday work**: `model: "sonnet"`, `effort: "high"`
- **Tier 1 — multi-file refactor, architecture, security, deep debug**: `model: "opus"`, `effort: "xhigh"` (currently Opus 5)
- Main session stays on Opus 5 / high (the pinned default)

## General approach
- Read before editing, but don't over-read
- Parallelize independent tool calls
- Run tests when you change code
- One-line summaries at end of turn

Confirm the switch by saying: **Balanced mode on. Sonnet 5 default, Opus on escalation.**
