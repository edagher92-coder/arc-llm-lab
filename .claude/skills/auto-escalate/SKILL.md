---
name: auto-escalate
description: |
  [EFFICIENCY] Apply a quality-first two-dial policy across model tier
  (haiku→claude-sonnet-5→opus→fable) and reasoning effort
  (low→medium→high→xhigh→max). The pinned main session is Claude Opus 5 at
  high effort. Trigger when the user asks to escalate, use Opus, think harder,
  take time, do this perfectly, use ultimate effort, or double escalate.
---

# Auto-escalation — Sonnet 5 quality-first

The pinned main session is **Claude Opus 5 at high effort**. A user-selected model always wins; never demote an explicit Opus or Fable selection. Escalate only the bounded sub-problem that needs more capability, then integrate and verify its result in the main task.

## Dial 1 — effort

| Effort | Use for |
|---|---|
| low | Mechanical inventories, copies, formatting, and safe bulk transforms |
| medium | Routine judgement and template-driven work |
| high | Default serious work on Sonnet 5 |
| xhigh | Hard bounded debugging, agentic work, edge-case sweeps, and adversarial review |
| max | Exceptional final verification or frontier work when the active surface supports it |

Increase effort before model tier when the problem is deep but narrow. Sonnet 5 at xhigh is the preferred first escalation for a difficult bounded sub-problem.

## Dial 2 — model

- **Haiku:** low-risk mechanical fan-out. Never use it for final high-stakes judgement.
- **Claude Sonnet 5:** default implementation, analysis, extraction, and orchestration.
- **Opus 5:** financial/legal/safety stakes, system-spanning architecture, security review, unresolved root cause, critical public output, or a Sonnet attempt that failed verification.
- **Fable:** frontier-scale or long-running work, a failed verified Opus attempt, or explicit user selection. Follow Elie's premium approval rule where one is configured.

Do not escalate what a deterministic test can settle. Improve the prompt, evidence, context, and verification before escalating solely because the first answer feels uncertain.

## Escalation protocol

1. Define the exact sub-problem and acceptance test.
2. Supply a self-contained prompt with relevant evidence, constraints, and required output.
3. Choose the lowest tier that meets the stakes and difficulty; round up when quality materially matters.
4. Integrate the result rather than copying it blindly.
5. Verify with tests, invariants, primary sources, or direct readback.
6. Escalate one rung if the improved attempt fails verification or uncertainty remains material.
7. Report any escalation in one concise line in the final response.

## Quality-intent override

When Elie says “take your time”, “be serious”, “do this perfectly”, “best possible”, “deep audit”, or “do not stop until verified”:

1. invoke `frontier-work`;
2. keep Sonnet 5 at high or xhigh unless stakes or failed verification require Opus;
3. do not offload the final decision or deliverable to an unverified local/cloud open model;
4. complete the verification matrix before reporting success.

The policy improves observable reliability; it does not claim perfect answers or reproduction of another model's hidden reasoning.
