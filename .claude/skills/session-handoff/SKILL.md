---
name: session-handoff
description: >
  Checkpoint and resume long work across sessions/compaction — write the
  state another session can pick up cold: goal, confirmed facts, decisions,
  verification done, remaining work, blockers. Use before ending a long
  session, before compaction on big tasks, when handing work between repos
  or models, and at the START of a resumed task (read the checkpoint first).
---

# session-handoff — no work re-derived, no context lost

Mined from account history: the monorepo's SESSION-HANDOFF.md practice and
the continuity rules in the universal CLAUDE.md, made into a procedure.

## Extracted logic

1. **A checkpoint is for a cold reader.** Write it for a session with zero
   memory of this one: no "as discussed", no codenames without definition,
   file paths absolute-from-repo-root.
2. **The six sections, always in this order** (`SESSION-HANDOFF.md` at repo
   root, or the task's dir):
   - **Goal** — one sentence + the observable definition of done.
   - **Confirmed facts** — only things verified with evidence, each with its
     source (command output, file, PR number).
   - **Decisions made** — with the one-line why; these are settled, the next
     session must not re-litigate them.
   - **Verification completed** — what was tested and how; what passed.
   - **Remaining work** — ordered, with the next single action first.
   - **Blockers** — exactly what is needed and from whom.
3. **What never goes in:** secrets, tokens, private transcript excerpts,
   customer data, and speculation dressed as fact. A checkpoint with an
   unverified claim poisons every session that trusts it.
4. **Update, don't append.** The checkpoint reflects NOW — stale sections
   are rewritten, not stacked. History lives in git, not in the file.
5. **On resume:** read the checkpoint FIRST, verify its top 1–2 confirmed
   facts still hold (cheapest checks only — a branch exists, a test passes),
   then continue from "Remaining work". Re-verify everything = wasted
   tokens; verify nothing = inherited lies.
6. **Compaction defence:** on very long tasks, refresh the checkpoint at
   meaningful milestones so a mid-task compaction costs nothing.

## Verification

- A cold read of the file answers: what's the goal, what's true, what's
  next? No secrets present; every confirmed fact cites its evidence.
