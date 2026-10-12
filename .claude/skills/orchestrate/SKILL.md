---
name: orchestrate
description: >
  [OPS] Run a deep-tech workstream as a Fable-led multi-model chain — Fable
  (this session) plans and synthesises, Opus sub-agents manage the hard
  slices, and workers (Sonnet / Haiku / GLM via router v5.1) execute
  cheapest-first. Use when Elie says "orchestrate this", "run this as a
  fleet", "Fable lead, pass it down", "delegate this across the models",
  or a task is big enough to need parallel workstreams with verification.
---

# Orchestrate — Fable leads, Opus manages, the fleet executes

Full policy: `ORCHESTRATION.md` in `claude-model-router` (hard rules:
NUMBERS RULE, skills-pass-down, honest envelopes, on-demand only).

## Steps

1. **Plan (Fable/this session).** Break the goal into 2-5 workstreams with
   explicit acceptance checks each. Decide which are deep-tech (need an
   Opus sub-manager) vs directly delegable (single worker is enough).
2. **Dispatch sub-managers.** For each deep-tech workstream, spawn an Agent
   with `model: opus`, giving it: the slice objective, acceptance checks,
   the relevant SKILL.md contents pasted in (workers can't discover
   skills), and the standing instruction: *"Do the genuinely hard parts
   yourself; for the rest, spawn subagents on the cheapest capable tier —
   sonnet for normal work, haiku for mechanical transforms — and route
   heavy NON-stakes bulk text through router v5.1's glm tier
   (`python -m router` / `run(task, tier='glm')`) when the bridge is
   configured. NEVER put money/price/quote/invoice/legal work on glm."*
3. **Direct workers.** Simple slices skip the middle tier: spawn `model:
   sonnet` or `model: haiku` agents straight from here.
4. **Collect + verify.** Treat every sub-result as unverified until its
   acceptance checks pass (run tests, re-read diffs, spot-check claims).
   One failed/incomplete attempt at a tier = escalate that slice one tier,
   never silently retry the same rung.
5. **Synthesise (Fable).** Merge verified results, surface every gap or
   unverified claim honestly, and report per-stream outcomes.

## Rules

- Stakes work (money, prices, quotes, invoices, legal, customer-facing)
  stays on Claude tiers — Opus by default. No exceptions.
- Route by evidence: check the latest `bench/reports/` table for the
  fleet's current strong suits before picking non-Claude workers.
- On-demand only: never leave standing loops or cron-driven fleets behind.
- For a durable, resumable run instead (server-side, disk-persisted),
  use `hq_orchestrator` with a `role: "orchestrator"` envelope — see
  ORCHESTRATION.md §2.
