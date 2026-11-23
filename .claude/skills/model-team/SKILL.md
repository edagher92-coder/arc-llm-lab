---
name: model-team
description: |
  [OPS] Run a piece of work through Elie's four-model team so it gets the best
  result for the least credit: Fable plans and is the final gate, Opus
  delegates and reviews everything, Sonnet and Haiku do the production work and
  report back up the chain. Use when Elie says "use the team", "run the model
  team", "Fable plan it, Opus manage it", "pass it down the chain", "best
  result, cheapest credits", or a task is multi-step, quality-critical or big
  enough to split. Not for a one-line answer or a single small edit.
---

# Model team: Fable plans and releases, Opus manages and reviews, Sonnet and Haiku produce

Elie's standing decision (23 Nov 2026). The aim is the best result at the
lowest credit cost: each model does only the part it is best value for, and
each one's weak spot is covered by another's check.

## The chain

```
Fable   plan + acceptance checks  ──►  final gate: release, or send back
  │                                          ▲
  ▼                                          │ verified package
Opus    briefs, dispatch, review every output, integrate
  │            ▲
  ▼            │ output + evidence, "done" or "blocked"
Sonnet  production: build, write, analyse, fix
Haiku   production: search, extract, reformat, classify, first-pass checks
```

| Model | Its job here | Strength used | Weak spot, and who covers it |
| --- | --- | --- | --- |
| **Fable** | Plans the work, sets the acceptance checks, decides each slice's tier, and is the final gate that releases the result. | Deepest reasoning, sees the whole problem and its traps. | Most expensive per token. Covered by keeping it to the plan and the gate, on summaries and diffs, never bulk reading or production. |
| **Opus** | Turns the plan into worker briefs, dispatches every slice, reviews every output, runs the checks, sends work back, integrates. | Strong judgement and adversarial review at a fraction of Fable's cost. | Costly to use as a typist, and can over-build. Covered by not producing (only delegating) and by Fable's plan fixing the scope. |
| **Sonnet** | Production: code, multi-file changes, drafting, analysis, fixes. | High quality per credit. | Blind spots in its own work. Covered by Opus reviewing every output. |
| **Haiku** | Production: file and code search, extraction, reformatting, classification, bulk simple edits, first-pass checks. | Fast and cheapest. | Weak judgement. Never final on anything that matters: Sonnet or Opus checks its output. |

## When to use the full chain

Proportional, or the chain itself wastes credit:

- **Full chain:** multi-step or multi-file work, anything quality-critical,
  anything that will ship, be published or reach a customer.
- **Short chain (no Fable):** a bounded task with an obvious plan. Opus briefs,
  Sonnet or Haiku produce, Opus reviews and releases.
- **No chain:** a question, a lookup or a one-line edit. The session just does it.

## Steps

1. **Plan (Fable).** Write the outcome, the slices, each slice's acceptance
   check, what is out of scope, and the tier per slice (Haiku for mechanical,
   Sonnet for everything else that is production). Name the stakes slices
   (money, prices, quotes, invoices, legal, customer-facing).
2. **Brief and dispatch (Opus).** One brief per slice: goal, files or sources,
   acceptance check, rules (the NUMBERS RULE, no secrets, no pushes unless
   told), and the smallest relevant SKILL.md content pasted in (workers cannot
   discover skills). Independent slices go out in parallel.
3. **Produce (Sonnet, Haiku).** Do the slice, prove it (tests, a failing test
   first for a fix, a source for every fact), and report up: what changed,
   evidence, and anything unverified or blocked, said plainly.
4. **Review (Opus).** Treat every report as a claim. Re-run the checks, read
   the diff, try to break it. Send it back with specific feedback once; a
   second failure moves the slice up one tier (Haiku to Sonnet, Sonnet to
   Opus). Opus produces itself only for a slice that failed at Sonnet, or a
   stakes slice that needs it.
5. **Package (Opus).** Integrate, run the whole suite, and hand Fable a short
   package: what was done, evidence per acceptance check, open risks,
   anything unverified.
6. **Gate (Fable).** Check the package against the plan's acceptance checks.
   Release it to Elie, or send named items back to Opus. Fable writes the
   final report.

## How to run it in Claude Code

- Subagents take a model: the Agent tool's `model` (`fable`, `opus`, `sonnet`,
  `haiku`), or `agent(prompt, { model })` inside a Workflow script.
- **Session on Fable:** the session is Fable. Spawn one Opus manager per
  workstream with the plan; Opus spawns the Sonnet and Haiku workers.
- **Session on Opus (the pinned default):** the session is the Opus manager.
  For a full-chain task, spawn a Fable agent for the plan first and a Fable
  agent for the final gate at the end, each given only what it needs
  (the goal and constraints; later the package and the diff).
- **Session on Sonnet:** spawn an Opus manager and work under it.
- Keep Fable's and Opus's context small: pass summaries, paths and diffs, not
  whole files or transcripts.
- Where subagents cannot be chosen by model (a plain chat), keep the same
  stages in one conversation and say which stage each step is.

## Credit rules

- Brief precisely; a vague brief costs a second round.
- Cheapest capable tier per slice; when torn between two tiers, round up.
- Raise effort before raising the tier for a narrow, hard slice.
- Parallel slices for independent work; one worker per slice.
- No standing loops, no polling, no scheduled model runs without Elie's
  budget decision.
- GitHub Actions: validate locally, work on a draft PR, push once per
  finished batch (the "GitHub Actions budget" rule in the account defaults).

## Hard rules

- Stakes work (money, prices, quotes, invoices, legal, customer-facing) stays
  on Claude, is reviewed by Opus and gated by Fable. Never on the GLM or Ollama
  bridge. The NUMBERS RULE applies: no fabricated price, date, spec or fact;
  anything unverified becomes a `[CONFIRM: ...]` gap.
- A worker's "done" is a claim until Opus has checked it. "A worker said so"
  is never evidence.
- Every level reports blockers and unverified items up, plainly.
- A model Elie selects for the session always wins; never demote it.
- Irreversible or outward actions (deploys, sends, payments, merges, deletes)
  need Elie's yes, whoever in the chain proposes them.
