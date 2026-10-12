---
name: stripe-billing
description: |
  [FINANCE · money-gated] Operate Stripe for Snow Flow recurring revenue via the
  Stripe MCP — set up Care Plan / consumables products & prices, generate
  payment links, draft subscriptions and invoices, and run the refund runbook.
  Use when the user says "set up Stripe billing", "create a payment link",
  "bill {venue} for Care Plus", "send an invoice", "process the Merivale
  refund", or "set up the subscription".
---

# Stripe billing — recurring revenue (money-gated)

Operationalises `streams/service-contracts.md` (Care Plan $49/$99/$199) and
`streams/consumables-subscription.md` (Always Stocked $89/$179/$349). Mirrors the
`snowflow-ads` guardrail: **anything that moves real money needs an explicit
"YES" from the operator — the tool drafts/assembles, the human approves.**

## Safe to do without extra approval (no money moves)
- **Create Products & Prices** for the 6 tiers (monthly + annual) — one-time setup.
- **Create reusable Payment Links** (one per tier). A link only charges when a
  customer clicks + pays, so generating them is safe. Drop them into the launch
  emails in the stream docs and the Christmas-in-July landing page. Record the
  resulting IDs/URLs in `streams/billing-stripe.md`.
- **Read** anything: `get_stripe_account_info`, list/search invoices, subs, charges.

## HUMAN-GATED — assemble, then require an explicit YES before executing
- **Start / cancel a subscription** (it bills a real customer): assemble
  `customer` + `price` + params, show the operator exactly what will be charged,
  wait for "YES", then create.
- **Finalise / send an invoice** (e.g. EOFY machine deposit, 50% upfront): draft
  it, confirm amount + customer, then send only on explicit approval.
- **Refunds** — hardest stop. Runbook for the **Merivale $2,898.99** case:
  1. **Reconcile** — confirm the original charge exists in Stripe and isn't
     already refunded elsewhere (AR is unreliable; verify against bank).
  2. Operator approves the **exact** amount ($2,898.99).
  3. `create_refund`.
  4. **Void the duplicate INV-2063A in Xero in lockstep** (Xero is read-only via
     MCP, so this step is a manual reminder to the operator).
  No batching, no automation, one at a time.

## Hard rules
- No charge, sub, invoice-send, or refund without an explicit per-action YES.
- Subscription tiers are all <$1k/mo → cards are the right channel (bank-transfer
  policy is for >$1k invoices; see overhead note on Stripe fees).
- Never commit Stripe secret keys — follow the gitignored-token / GitHub Secret
  pattern used for Meta.

## Hand off to
- `/collections` when a chased debtor wants to pay by card (generate a payment link).
- `streams/billing-stripe.md` for the product/price/link IDs once created.
