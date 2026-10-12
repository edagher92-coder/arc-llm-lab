---
name: deep
description: |
  [EFFICIENCY] Switch to full-power mode for complex tasks — thorough reasoning,
  Opus subagents, detailed responses. Use when the user says "deep mode",
  "thorough", "complex task", "go deep", or types /deep.
---

# Deep Mode — Full-Power Profile

You are now in **deep mode**. Apply these rules for the rest of this session
(until the user switches with `/quick` or `/balanced`):

## Response rules
- Think thoroughly before responding — use extended reasoning
- Provide detailed analysis with evidence from the codebase
- Structure responses with headers and sections when appropriate
- Anticipate follow-up questions and address them proactively

## Subagent routing (quality-first overrides)
When you need to spawn subagents (Agent tool), use these overrides:
- **Tier 3 — search, grep**: `model: "sonnet"`, `effort: "high"` (not Haiku — need depth in deep mode)
- **Tier 2 — code implementation, single-file**: `model: "opus"`, `effort: "high"` (Opus 5 for quality)
- **Tier 1 — architecture, security, review**: `model: "opus"`, `effort: "xhigh"` (Opus 5, maximum depth)
- **Workflows**: `effort: "high"` on all stages, `"xhigh"` on verify stages
- Main session stays on Opus 5 / high (the pinned default) — this mode pushes subagents to Opus 5

## What to do MORE of
- Read surrounding code before editing — understand the full context
- Run tests after changes
- Consider edge cases and failure modes
- Parallelize independent searches for thoroughness

Confirm the switch by saying: **Deep mode on. Full reasoning enabled, Opus subagents for thorough work.**
