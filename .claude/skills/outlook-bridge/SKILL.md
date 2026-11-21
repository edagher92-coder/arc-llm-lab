---
name: outlook-bridge
description: Read and write Elie's Outlook through Sam's Outlook bridge (the office PC companion) — list the forwarded emails Sam holds, queue a reply as an Outlook DRAFT, write or cancel hire diary entries in the Outlook calendar, and check that the PC saved them. Use when Elie says "add it to the Outlook calendar", "queue the reply", "put it in Outlook", "through the bridge", "which emails are waiting", or asks whether a draft or diary entry landed.
---

# Outlook bridge (Sam's queue)

Sam (https://sam-snowflow-sydney.onrender.com) holds a queue that the office PC companion works through. Through it any
Claude thread can:

| Want | Command (from a `edagher92-coder/snowflow-ask-sam` checkout on `main`) |
|---|---|
| See the emails Sam holds (id, sender, subject, state; never a body) | `node tools/outlook-queue.mjs emails --business <brand> [--limit 25] [--state new]` |
| Re-run Sam's verified draft for an email (and see why one failed) | `node tools/outlook-queue.mjs prepare --intake <in_…> --business <brand>` |
| Queue **Sam's own** verified draft, house format (preferred) | `node tools/outlook-queue.mjs draft --intake <in_…> --business <brand> --verified [--attach file.pdf]` |
| Queue a reply you wrote as an Outlook **draft** | `node tools/outlook-queue.mjs draft --intake <in_…> --business <brand> --body reply.txt [--attach file.pdf]` |
| Write diary entries (hire-diary job JSON) | `node tools/outlook-queue.mjs calendar job.json --business <brand> --status tentative\|confirmed` |
| Cancel those entries | `node tools/outlook-queue.mjs calendar job.json --business <brand> --cancel` |
| Did the PC do it? | `node tools/outlook-queue.mjs status <jobId> …` |

`<brand>` is `snowflow-sydney` or `slushieco-sydney`, whichever mailbox the email came into. Add `--dry-run` to see
what would be queued without queueing it.

## What it can and cannot do

- **Nothing is ever sent.** A queued reply becomes an Outlook draft; Elie opens it and presses send. The queue token
  cannot approve, claim or send anything.
- **"QUEUED" is not "done".** Only `status` reporting `saved` (draft) or `saved` / `in the calendar` (diary) means the
  PC did it. Say exactly that, and never report an entry as in the calendar before it does. `uncertain` or `not_found`
  are reported as they are.
- **Prefer `--verified`.** It queues Sam's prepared draft rendered by the server in the house format (plain text,
  UPPERCASE labels, `-` bullets, "Kind regards," / "Elie", no signature block), so a verified reply is never retyped.
  If the emails list shows `draft failed (…)` or `needs_review`, run `prepare` first and read its reason.
- **A draft must match Sam's own verified draft.** The server refuses it (409) unless Sam has prepared a verified
  reply for that same email and every dollar amount in your body appears in the same order as in Sam's draft (the
  dollar guard). `needs_attention` / "Prepare the verified reply" means Sam has no priced draft for that email yet:
  re-prepare it in Inbox Sam, or send by hand. Never work around the guard. Any `[CONFIRM: …]` in the body is refused.
- **Diary files** follow the house format (rule `hire-diary-format.md`, tool `tools/hire-invite/hire_diary.py`):
  `Drop Off:` / `Pick Up:`, `Bump In:` / `Bump Out:`, `Pickup:` / `Return:`, unknowns written TBC. Raise `sequence` to
  change entries already in the calendar.

## Access (the token)

The CLI reads the queue token from `INBOX_OUTLOOK_QUEUE_TOKEN` only, never a flag.

- **Cloud sessions:** the token is a **network secret** on the session's environment (host
  `sam-snowflow-sydney.onrender.com`, header `Authorization`). The proxy injects it, so give the CLI a dummy value and
  route Node through the proxy:
  ```bash
  export SAM_BASE_URL=https://sam-snowflow-sydney.onrender.com
  export INBOX_OUTLOOK_QUEUE_TOKEN=dummy-dummy-dummy-dummy-dummy-dummy-00   # replaced by the proxy
  export NODE_USE_ENV_PROXY=1 NODE_EXTRA_CA_CERTS=/root/.ccr/ca-bundle.crt
  ```
  Without `NODE_USE_ENV_PROXY=1` Node bypasses the proxy and the server answers 401 to the dummy.
  An environment without that network secret cannot use the bridge: ask Elie to add it in that environment's
  settings (Network secrets), with `request_credential` where offered. Never ask for the token in chat.
- **Desktop / Cowork on Elie's PC:** set `INBOX_OUTLOOK_QUEUE_TOKEN` in the user environment (not in a repo, not in
  chat) and point `SAM_BASE_URL` at the server.
- **No checkout?** Clone `edagher92-coder/snowflow-ask-sam` (read access is enough) and run the CLI from it. Don't
  hand-roll HTTP calls: the CLI validates diary requests with the server's own code.

## House rules that still apply

Customer replies follow the account email rules (one plain-text box, UPPERCASE labels, `-` bullets, sign off
"Kind regards," / "Elie" only, THREAD SO FAR and REPLY SUMMARY outside the box). Never queue a price or date that is
not from the verified sources, and nothing goes to a customer without Elie's accept.
