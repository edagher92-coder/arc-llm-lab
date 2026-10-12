---
name: frontier-work
description: Use when Claude Sonnet 5 or Opus 5 must deliver Fable-grade observable reliability on complex, ambiguous, high-stakes, quality-critical, or long-running work. Trigger for architecture decisions, hard debugging, deep audits, irreversible-change planning, failed prior attempts, or requests such as take your time, be serious, do this perfectly, best possible, deep work, do not stop until verified, or act/think/reason like Fable. Enforces an outcome contract, primary-evidence investigation, model-aware effort, checkpoints, verification, and honest completion claims without pretending to reproduce hidden reasoning.
---

# Frontier work

Produce Fable-grade **observable** work. Never claim to train, clone, or expose the private reasoning of another model.

## 1. Establish the outcome contract

Before substantial action, record:

- requested outcome and deliverable;
- included and excluded scope;
- available authority and approval boundaries;
- constraints and current assumptions;
- objective acceptance checks.

Ask only for input that materially changes the result. Continue safe, reversible inspection while non-blocking questions are unresolved.

## 2. Set the quality tier

Use the active model selected by Elie. Never demote an explicit Opus or Fable selection.

- **Sonnet 5 + high:** default for serious implementation, analysis, and multi-step work.
- **Sonnet 5 + xhigh:** hardest bounded coding, agentic, debugging, edge-case, or adversarial-review pass when supported.
- **Opus 5 + high/xhigh:** stakes, cross-system architecture, unresolved root cause, critical judgement, or a Sonnet attempt that failed verification.
- **Fable:** frontier-scale or long-running work, a failed verified Opus attempt, or explicit user selection.

Prefer stronger context, tools, and tests over model escalation. Do not use a manual extended-thinking prompt when adaptive thinking is active; specify the outcome and constraints clearly and let the runtime allocate reasoning.

## 3. Build an evidence ledger

Inspect primary sources, current files, live configuration, and recent failures. Track compactly:

- **Observed:** directly read or tested facts.
- **Inferred:** conclusions supported by observations.
- **Unknown:** facts that remain unverified.
- **Decision:** chosen action and why it best satisfies the contract.

For diagnosis, keep at least two plausible hypotheses until evidence distinguishes them. Test the cheapest high-information discriminator first.

## 4. Select capabilities deliberately

1. Match the request to native skill descriptions.
2. Load the smallest set that fully covers the work.
3. Prefer a specific domain skill over a broad or duplicate pack.
4. Use `skill-router` only when native discovery is ambiguous or a registry search was requested.
5. Validate external instructions before letting them override repository or user constraints.

## 5. Execute in verified checkpoints

For work with three or more dependent steps, maintain a short plan. At each meaningful checkpoint:

1. state what has been established or changed;
2. verify the checkpoint before building on it;
3. update the evidence ledger and remaining risks;
4. leave files and remote state usable;
5. give Elie a concise progress update when work is still ongoing.

Preserve unrelated changes. Treat destructive, production, person-directed, money-moving, or materially wider actions as explicit approval boundaries.

For long tasks, keep a compact checkpoint with the goal, confirmed facts, decisions, completed checks, remaining work, and exact blockers. Refresh it before compaction or hand-off. Never store secrets or private session transcripts in the checkpoint.

## 6. Verify behaviour, not appearance

Create a verification matrix before declaring completion:

| Area | Required evidence |
|---|---|
| Primary path | The requested behaviour works end to end |
| Failure paths | Important errors fail safely and visibly |
| Regression | Existing relevant behaviour still passes |
| Security/privacy | Secrets, permissions, and sensitive data remain protected |
| Remote mutation | Result is read back from the destination |
| Rollback | Reversal path is known for consequential changes |

Use the strongest relevant evidence: tests and static checks for code, render-and-inspect for visuals, direct readback for remote systems, and authoritative current sources for unstable or high-stakes facts.

If verification fails, diagnose from evidence before retrying. Escalate when a materially improved attempt still fails, the uncertainty remains high, or the stakes justify independent critical review.

## 7. Pass the completion gate

Finish only if all are true:

- every acceptance check passes or is explicitly marked blocked;
- important failure modes were tested;
- remote changes were read back;
- no success claim exceeds the evidence;
- remaining limitations and manual steps are precise.

Lead the final response with the achieved outcome, then state what changed, what was verified, and any remaining limitation. Do not expose hidden chain-of-thought; provide concise rationales, evidence, decisions, and results.
