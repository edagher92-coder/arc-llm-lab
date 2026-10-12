---
name: model-router
description: >-
  Quality-first algorithm for choosing the Claude model (Haiku 4.5 / Sonnet 4.6 / Opus 5 / Fable 5),
  the effort level (low→max), whether to delegate to subagents, and whether to use Fast mode — per task,
  to get the best possible output at the lowest latency and weekly-limit cost that does NOT sacrifice
  quality. Invoke when deciding how to run work, when results feel slow or expensive, or to set up
  smart model/effort routing in a project.
---

# Model Router — smart, quality-first model & effort selection

Pick the cheapest, fastest configuration **that does not change the quality of the result.** Quality is
never the variable being traded. Cost and latency are minimised only *after* quality is locked in.

## The one hard constraint (read first)

The model running the **main conversation** is set by the harness (`/model` / config). **This skill cannot
silently switch the main model mid-turn** — and neither can any other Markdown file. So it operates on
three real levers:

1. **Routing tag (main loop).** When the current main model is mismatched to the task, emit one line and
   let the human flip it with a keystroke: `⟂ Router: this is an Opus·xhigh task — suggest /model Opus`
   (or `↓ Sonnet is plenty here`). If the current model already fits, say nothing and proceed.
2. **Subagent overrides (fully automatic).** When delegating via the Agent/Task tool, set `model:` and an
   effort hint per subtask. This needs no user action and is where most automatic savings come from —
   heavy reasoning to an Opus subagent, broad search / mechanical work to Haiku/Sonnet subagents, while
   the main loop stays on a cheap model.
3. **Effort + Fast mode.** Dial `effort` (low→max) to the task; use `/fast` only as an explicit
   "need-it-now" override (premium cost).

## Objective (lexicographic — in this order)

1. **Quality** of the output — maximise. Non-negotiable.
2. **Latency** — minimise, given (1).
3. **Cost / weekly-limit burn** — minimise, given (1) and (2).

If lowering cost or latency could plausibly degrade the result, **don't** — stay high.

## Signals to score (cheap to read off any task)

| Signal | Low end → high end |
|---|---|
| **Complexity** | one-step / mechanical → multi-step reasoning, novel design |
| **Blast radius / reversibility** | read-only or trivially revertible → irreversible, prod, money, data loss |
| **Ambiguity** | fully specified → vague, underspecified, judgement-heavy |
| **Breadth / fan-out** | single file/answer → many independent items (parallelisable) |
| **Output type** | search, lookup, format, classify, rote edit → architecture, debugging, prose, design, security |
| **Latency need** | async/background → user is actively waiting |
| **Prior-attempt failures** | first attempt → a lower tier already failed this |
| **Cost-of-error** | caught instantly by tests/review → silent, expensive, user-facing |

## Model tiers

| Model | Price /1M (in/out) | Relative speed | Use for |
|---|---|---|---|
| **Haiku 4.5** | $1 / $5 | fastest | trivial, mechanical, high-volume, latency-critical-simple: lookups, file/path search, formatting, classification, rote edits |
| **Sonnet 4.6** | $3 / $15 (0.6× Opus) | fast | **default daily driver** — most coding, edits, reviews, Q&A, well-specified tasks, prose |
| **Opus 5** | $5 / $25 | slower (reasons more) | hard reasoning, long-horizon agentic, gnarly multi-file debugging, architecture, design, high-stakes/irreversible, security, ambiguous-but-important, anything that failed on a lower tier |
| **Fable 5** | $10 / $50 | slowest | only on explicit request, or frontier reasoning Opus genuinely can't carry |

Sonnet is exactly 0.6× Opus on both input and output → ~40% cheaper per token. **Cost is the reliable
saving; speed is task-dependent** — on small, well-specified tasks Opus can be *more* decisive (fewer tool
calls, fewer tokens), so don't promise Sonnet is "faster" in general. Don't bias model choice on latency
alone; choose on the quality/cost axes and treat speed as a tie-breaker for light, interactive turns.

## Keeping the tiers current (new model releases)

Model names, IDs, prices, and capabilities change — the tier table above is a snapshot, not a constant.
When a newer model ships (e.g. a future top-tier **"5"-generation** Opus/Sonnet, an "Opus 5" / "Claude 5.x",
or anything that supersedes Opus 5), do **not** guess its model ID, price, or capabilities:

1. **Read the `claude-api` skill** (the live source of truth for model IDs/pricing) — or query the Models
   API directly (`client.models.list()` / `client.models.retrieve(id)`) — for the exact string and rates.
2. **Slot it into the tier table by capability and price**: a new flagship that beats Opus 5 takes the
   top "hard reasoning / stakes-gate" slot; re-baseline the Sonnet↔top-tier cost ratio against the new
   prices (today's 0.6× is specific to Sonnet 4.6 vs Opus 5).
3. Today's most-capable "5"-tier model is **Fable 5** (already listed, premium / explicit-request only);
   **Mythos 5** is the same thing behind Project Glasswing. A genuinely new "5.0" flagship is added the
   same way — verify, then slot.

The algorithm itself (stakes gate → score → fan-out → verify → downshift) is **model-agnostic** and does
not change when the roster does — only the tier table and the cost ratio need refreshing.

## Effort

`output_config.effort`: `low` → `medium` → `high` → `xhigh` (Opus 5) → `max`.
- **low** — subagents, trivial/scoped tasks, latency-sensitive simple work. Fewer, consolidated tool calls; terse.
- **medium** — balanced default for moderate everyday work.
- **high** — intelligence-sensitive work; the floor for anything that matters.
- **xhigh** — best for coding/agentic on Opus.
- **max** — correctness >> cost; rare, hardest cases.

Effort moves token spend and latency as much as model choice — right-sizing it is the cheapest speed win.

## The algorithm

```
1. STAKES GATE (overrides everything below):
   irreversible | prod-write | security | money | legal | "ship/merge it"
   → Opus 5, effort ≥ high, and VERIFY. Do not downshift. Stop here.

2. PRIOR FAILURE:
   a lower tier (or lower effort) already failed this exact task
   → escalate one tier AND/OR raise effort. Never silently retry the losing config.

3. SCORE complexity + ambiguity + output type:
   trivial + clear + cheap-to-verify        → Haiku 4.5  (or Sonnet, effort low)
   everyday + well-specified                → Sonnet 4.6, effort medium   ← default
   hard | ambiguous-important | long-horizon → Opus 5, effort high–xhigh

4. BREADTH:
   fan-out across independent items → delegate to PARALLEL subagents,
   each at the tier its subtask needs (search/scan = Haiku, synthesis = Sonnet/Opus).
   Keep the main loop on the cheap tier.

5. LATENCY:
   light + user waiting  → Sonnet/Haiku + lower effort (faster AND cheaper)
   hard + user waiting   → accept Opus latency, or suggest /fast (premium cost, speed only)
   async / background    → optimise cost over speed

6. VERIFY, then DOWNSHIFT:
   produce on the higher tier when unsure; verify (tsc / tests / re-read / oracle);
   once a pattern is proven safe, downshift subsequent similar steps.

7. DEFAULT UP when any signal is uncertain. Quality first.
```

## Subagent delegation (the automatic lever)

When the work fans out or has a heavy-but-isolated core, delegate with an explicit model per subtask. The
main loop stays cheap; only the part that needs Opus pays for Opus.

```
# broad read-only search across many files → cheapest, parallel
Agent(subagent_type: "Explore", model: "haiku", prompt: "find every call site of X …")

# moderate, well-scoped build/refactor → Sonnet
Agent(subagent_type: "general-purpose", model: "sonnet", prompt: "implement Y per this spec …")

# the genuinely hard core (architecture, gnarly bug, security) → Opus
Agent(subagent_type: "general-purpose", model: "opus", prompt: "design/diagnose Z …")
```

Run independent agents in **one message** so they execute concurrently (wall-clock win). Note: switching
the main model mid-session invalidates the prompt cache — prefer a subagent over flipping the main model
for a one-off sub-task.

## Quality guardrails (non-negotiable)

- **Stakes gate wins over cost.** Irreversible/prod/security/money/legal → Opus, verified. Always.
- **Default up under uncertainty.** When unsure which tier, pick the higher one.
- **Escalate on failure.** A failed attempt means the config was too weak — go up, don't repeat.
- **Verify hard outputs** regardless of tier (compile, run tests, re-read the diff, check against an oracle).
- **Downshift only when proven safe** — i.e. a comparable step already succeeded at the lower tier.
- **Fast mode is speed, not savings.** `/fast` is the same Opus 5 at premium price; use it only when the
  user is waiting and speed matters more than cost this turn — never as a default.

## Worked examples

| Task | Route |
|---|---|
| "Rename this variable across the file" | Haiku / Sonnet-low. Mechanical, reversible, cheap to verify. |
| "Find where we handle webhook retries" | Haiku Explore subagent (read-only search), parallel. |
| "Add a tile to the dashboard per this spec" | Sonnet, medium. Well-specified everyday coding. |
| "Why does this sync return 0 rows intermittently?" | Opus, high. Gnarly debugging, high cost-of-error. |
| "Design the multi-tenant token model" | Opus, xhigh. Architecture, ambiguous, high blast-radius. |
| "Merge this to main / wire the prod migration" | Opus, high, **verify** — stakes gate. |
| "Audit 200 files for a security pattern" | Fan-out: parallel Haiku subagents scan, Opus synthesises findings. |
| "Sonnet's refactor broke the build" (retry) | Escalate → Opus, xhigh. Prior-attempt failure. |
| Interactive chat, user waiting, simple Q | Sonnet (or current model), low effort — fast + cheap. |

## Field notes (validated by an A/B test)

A controlled A/B on the same well-specified coding task (build a pure analytics module + vitest suite),
one **Sonnet** arm vs one **Opus** arm, judged by `tsc --strict` + the real `vitest` suite:

- **Quality was equal.** Both compiled strict-clean and passed their own suites (Sonnet 10/10, Opus 8/8).
  No bugs in either. → The "Sonnet for everyday well-specified coding" call holds: equal quality, lower cost.
- **The saving was ~30%, and it came from the rate, not fewer tokens.** Sonnet actually used *more* tokens
  and tool calls and was slightly slower on this task; it still cost ~30% less purely because of the 0.6×
  price. Bank the cost win; don't assume a speed win.
- **Opus self-verified** (ran its own type-check + logic port) without being asked — a real edge for
  high-stakes/irreversible work. Keep the stakes gate.
- **Ambiguous specs make tiers diverge — defensibly, not as bugs.** Cross-running one arm's tests against
  the other's code failed only on the genuinely under-specified points (e.g. "posts per week" = count÷span
  vs interval-rate). The model can't read intent: **pin ambiguous requirements in the spec** rather than
  expecting a higher tier to guess them.

## Output: the routing tag

When a `/model` change is worth it, lead with one line, then proceed; otherwise stay silent:

```
⟂ Router: hard debugging + high cost-of-error → suggest /model Opus (xhigh). Proceeding meanwhile.
⟂ Router: this is routine — /model Sonnet would be ~40% cheaper and faster, no quality cost.
```

Keep it to one line. Don't narrate the scoring; just give the call and the one-clause reason.
