---
name: collections
description: |
  [FINANCE · draft-only] Chase overdue invoices — pull receivables from the
  Xero MCP, draft polite Aussie-toned chase emails as Gmail drafts (never
  auto-send), and label the threads. Use when the user says "chase overdue
  invoices", "who owes us and email them", "collections", "draft chase
  emails", or "follow up unpaid invoices".
---

# Collections — chase the overdue cash (draft-only)

The fastest, cheapest cash is money already earned but uncollected. This skill
turns the Xero overdue list into ready-to-send drafts. It NEVER sends.

## When invoked

1. Pull overdue invoices from Xero: `get_contacts_and_receivables`
   (total, count, biggest + oldest debtors). Optionally `get_cash_position`
   for context ("you're owed Nx your cash balance").
2. **Reconcile first (mandatory).** Open AR is unreliable — flag that some
   "overdue" invoices may be paid-outside-Xero or duplicated (e.g. the Merivale
   INV-2063 duplicate). Recommend the operator confirm against bank payments
   before chasing. Chase only what's genuinely outstanding.
3. Build the **80/20 hit list** — the largest/oldest invoices that cover most
   of the overdue total. Hand-chase those; let Xero auto-reminders handle the tail.
4. For each top debtor, draft a tiered chase email (gentle <30d / firm 30–90d /
   final 90d+) using the scripts in `collections/playbook.md`. Find the contact's
   email via the Outlook MCP (read-only search of `sydney@snowflow.com.au`
   threads) where Xero doesn't expose it.
5. Create the drafts via the **Gmail MCP** (`create_draft`) and label them under
   a "Snow Flow — Overdue" Gmail label (`create_label` + `label_message`).
   Address master drafts to the operator's own inbox with a `[MASTER DRAFT]`
   note + the intended recipient at the top.

## Hard rules

- **NEVER send.** Draft only. Real sends go from `sydney@snowflow.com.au`
  (Outlook), which is read-only here — so it physically can't auto-send. Keep it that way.
- **Reconcile before chase.** Don't chase phantom/duplicate invoices.
- Aussie B2B tone, no threats until genuine final notice; always offer a payment
  plan over a write-off.
- For a debtor who is also a live sales lead, bundle the debt into the new deal
  (see the Trojans example in `collections/playbook.md`).

## Hand off to

- Turn on Xero automatic invoice reminders (Settings → Invoice reminders) for the long tail.
- `/stripe-billing` if a debtor wants to pay by card / set up a payment link.
