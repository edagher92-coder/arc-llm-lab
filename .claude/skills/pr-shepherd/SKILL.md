---
name: pr-shepherd
description: >
  The push → PR → watch → merge loop done to house standard — branch
  hygiene, verified-before-push, draft PRs with honest bodies, webhook-based
  watching (never polling), merged-branch restart rule. Use whenever work
  ships through a pull request, which is nearly always.
---

# pr-shepherd — ship through PRs without babysitting

Mined from account history: the father rule's webhook-only monitoring, and
the shipping loop proven across this account's sync/orchestration PRs.

## Extracted logic

1. **Verify before push, every time:** run the repo's checks locally (tests,
   linters, structural validators) before pushing — CI is confirmation, not
   discovery. A red PR you predicted is a process failure.
2. **Branch hygiene:** one logical change-set per branch; if the branch's PR
   was MERGED, never stack new commits on the old history — restart the
   branch from the latest default (`git fetch origin main && git checkout -B
   <branch> origin/main`) and open a NEW PR.
3. **PR body = honest evidence:** what changed, what was verified and HOW
   (paste the command + result), what was deliberately not done. Mirror the
   repo's PR template when one exists. Draft first; ready-for-review is a
   deliberate act.
4. **Watch by webhook, never by polling:** subscribe to PR activity and end
   the turn; act on events as they arrive. At most one scheduled check-in
   (~hourly) as fallback for events webhooks don't deliver (CI success,
   merge conflicts) — and delete the trigger the moment the PR is merged or
   closed. No self-re-arming loops beyond that.
5. **On CI failure:** read the actual log before touching anything;
   re-diagnose fresh each round (the second failure is often a different
   fault); push the fix; don't narrate each round — the diff is the record.
6. **On review comments:** ambiguous or architecturally significant → ask
   the human with enough context to answer cold; clear and small → fix and
   push; duplicate/no-action → skip silently. Reply on the thread only when
   it resolves the task or a suggestion is wrong — be frugal with comments.
7. **Merge discipline:** merge only when checks are green and the human has
   asked (or standing authority exists). Match the repo's merge method
   (look at its history). After merge: clean up triggers/subscriptions.

## Verification

- Local checks ran before every push; PR body cites real verification;
  no polling loops; triggers deleted after merge/close.
