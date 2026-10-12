---
name: agent-graph
description: >
  Execution semantics for multi-agent runs over STATE.json — supervisor loop,
  ready-set scheduling, checkpoint/resume, speaker selection, termination
  conditions. Use when the orchestrator runs a dependency graph, resumes a
  crashed run, or a run risks looping. Not for single delegations (use
  delegate).
---

# agent-graph — state-machine orchestration semantics

Distilled from `langchain-ai/langgraph`, `microsoft/autogen`,
`crewAIInc/crewAI` (all MIT).

## Extracted logic

1. **Typed state, single writer** (LangGraph): the graph state (our
   STATE.json) has a schema and exactly one writer — the supervisor. Workers
   return deltas (result envelopes); the supervisor reduces them into state.
2. **Ready-set scheduling**: a task is `ready` iff all `depends_on` are
   `done`. Each supervisor tick: promote pending→ready, dispatch every ready
   task (parallel where independent), await, reduce, repeat. No task is ever
   dispatched twice concurrently.
3. **Conditional edges = audit gate**: the edge out of every worker node is a
   decision — `pass → unblock dependents`, `fail(attempts<max) → retry with
   audit_notes`, `fail(attempts=max) → re-plan or surface`. Encode retry
   ceilings in state, not vibes.
4. **Checkpointer/resume** (LangGraph's checkpointer, our files): persist
   state after *every* reduce. Resume = load STATE.json, reconcile
   `dispatched` tasks via `get_task_status`, continue the tick loop. Never
   re-run `done` work unless its inputs changed.
5. **Speaker selection** (AutoGen group-chat, simplified): route by
   `task_type` table, not by asking a model who should speak — deterministic
   routing is cheaper and auditable. Model-judged routing only for
   `task_type: "unknown"`.
6. **Role cards** (CrewAI): every worker gets role + goal + constraints (our
   system cards). A worker without a card is a bug.
7. **Termination conditions** (AutoGen): a run ends on (a) graph terminal,
   (b) human-input-needed, (c) budget ceiling (tasks, tokens, or wall clock),
   whichever first. Every loop has an explicit ceiling — the father rule's
   "no self-re-arming loops" applied to graphs.

## Procedure (supervisor tick loop)

```
load STATE.json → validate → reconcile in-flight
while ready-set not empty and budget remains:
    dispatch ready tasks → collect result envelopes
    audit each (evidence, not claims) → reduce into state → persist
report: done / blocked-on-human / budget-stop (never silent)
```

## Verification

- STATE.json validates after every tick; audit_log explains every status
  change; a killed-and-resumed run completes without duplicating work.
