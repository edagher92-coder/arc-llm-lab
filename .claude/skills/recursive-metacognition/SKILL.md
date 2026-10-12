---
name: recursive-metacognition
description: Apply automatically on every non-trivial task (reasoning, analysis, drafting, coding, planning) — it is the account's default prompting protocol, not an opt-in. Combines the two evidence-backed ideas behind the viral "MIT recursive meta-cognition" technique — recursive decomposition of large problems/context (MIT CSAIL Recursive Language Models, arXiv:2512.24601) and a bounded metacognitive plan→attempt→critique→refine loop (metacognitive-prompting literature) — with a hard depth cap so reflection never degrades into overthinking or token burn. Also trigger when Elie says "recursive metacognition", "think recursively", "self-critique this", or "MIT method".
---

# Recursive metacognition — the default prompting protocol

Two research-backed moves, fused. Apply on any non-trivial task; skip only for
trivial mechanical work (a rename, a lookup, a one-line answer) where a loop
adds cost but no quality.

**Provenance (honest version):** the viral "MIT Recursive Meta-Cognition prompt"
misdescribes MIT CSAIL's actual paper — *Recursive Language Models* (Zhang,
Kraska & Khattab, arXiv:2512.24601), an inference framework where the model
**decomposes long input and recursively calls itself over sub-segments** instead
of processing one giant prompt (fixes "context rot"). The self-evaluation half
comes from the separate metacognitive-prompting literature (e.g.
arXiv:2311.11482 formalising Recursive Meta Prompting). A 2026 reproduction
("Think, But Don't Overthink", arXiv:2603.02615) shows unbounded reflection
*hurts* — hence the hard caps below. Use both ideas; never cite the 110% viral
number as fact.

## Move 1 — Recurse over the PROBLEM, not one giant pass (RLM)

Before answering anything large:

1. **Decompose.** Split the task/context into sub-problems or context slices.
   Never linearly grind a huge input in one pass — that is where quality rots.
2. **Recurse cheaply.** Solve each slice with the cheapest capable engine —
   subagents, the model router's tiers, or a focused re-read of just that slice
   — per the delegation reflex (north star). The lead loop holds only the plan,
   the acceptance checks, and the synthesis.
3. **Synthesise from findings, not raw dumps.** Sub-answers come back as
   conclusions; the lead never re-ingests what a slice already digested.

This is the same principle as the router's input auto-compaction and Claude
Code's autoCompact — decompose/condense context *before* it degrades output or
burns credit.

## Move 2 — Bounded metacognitive loop (plan → attempt → critique → refine)

For each substantial output:

1. **Frame (metacognition first).** State to yourself: what is actually being
   asked, what would make the answer wrong, and 2–4 explicit acceptance checks
   (correctness, completeness, numbers/dates verbatim, edge cases, format).
2. **Attempt.** Produce the full candidate answer.
3. **Critique adversarially.** Re-read the candidate AS A SCEPTIC against the
   acceptance checks: what's missing, what's unverified, where would an expert
   push back, does any number/date lack a source? Rubber-stamping is a protocol
   violation — find the weakest point every pass.
4. **Refine.** Fix only what the critique found. If the critique found nothing
   material, STOP — do not polish further.

**Hard caps (anti-overthinking, evidence-backed):**
- Max **2** critique→refine passes per output (1 for routine work). A third
  pass requires new external evidence, not another re-read.
- Never sacrifice a number, caveat, or requested item to make a critique pass
  "cleaner" — quality is the ceiling, cost the floor.
- Stakes work (customer money/quotes/invoices/legal) keeps every existing gate:
  verified sources only, `[CONFIRM: …]` gaps, Claude-tiers-only. Metacognition
  supplements the NUMBERS RULE; it never replaces it.

## Passing it down the ladder

Workers have no native discovery: when delegating, embed the loop in the
delegate's prompt — "decompose first; state acceptance checks; attempt;
critique your attempt against the checks once; refine; return the refined
answer plus what your critique caught." One line of the worker's reply should
say what the self-critique changed — that is the observable evidence the loop
ran (honest-envelope rule).

## When NOT to use

- Trivial/mechanical tasks (Haiku-tier): the loop costs more than it adds.
- Latency-critical one-liners.
- As a substitute for real verification — tests, `--doctor`, rendered previews
  and primary sources still outrank self-assessment every time.
