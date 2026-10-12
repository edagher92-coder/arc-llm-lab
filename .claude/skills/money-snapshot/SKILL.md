---
name: money-snapshot
description: |
  [FINANCE · read-only] Pull a live financial snapshot from the connected Xero
  MCP — cash position, overdue receivables, P&L trend, top customers — and
  optionally refresh dashboard/data.json. Use when the user says "money
  snapshot", "how's the business doing", "what's our cash position",
  "refresh the dashboard", or "pull the latest Xero numbers". (For chasing/
  emailing debtors use /collections instead.)
---

# Money snapshot — live Xero read

Read-only. Never writes to Xero. The numbers it pulls are the source of truth
for `REVENUE-RESCUE.md`, `dashboard/`, and `/weekly-review`.

## When invoked

1. Confirm the Xero MCP server is connected (tools prefixed
   `mcp__*__get_cash_position` etc.). If not, say so and stop.
2. Pull in parallel:
   - `get_cash_position` → cash balance, amount owed to you, amount you owe, working capital
   - `get_contacts_and_receivables` → overdue total + count + biggest/oldest debtors
   - `get_profit_and_loss` → income/expense/net profit (current FY vs prior)
   - `get_top_customers_by_revenue` → ranked real buyers (note: finance/related
     entities may rank high — flag them, they aren't end-customers)
3. Report a tight scannable summary: cash, overdue (the #1 cash lever), net
   profit YoY, the 2–3 streams growing vs shrinking, and the top debtors to chase.

## Hard rules

- **Read-only.** This skill never moves money. No refunds, no invoices, no sends.
- **AR caveat:** the operator has confirmed open invoices/bills are NOT fully
  maintained — treat the overdue figure as *indicative*, recommend reconciling
  against bank payments before hard-chasing (see `streams/key-accounts.md` §3).
- Trust **closed/paid** data over **open** AR.

## Optional — refresh the dashboard

If the user asks to refresh the dashboard, update both the JS `DATA` object in
`dashboard/index.html` AND `dashboard/data.json` with the new figures and bump
`snapshotDate`. (CI can't do this — the Xero MCP is a harness-level connection,
not callable from GitHub Actions — so it's an in-session action.)

## Hand off to

- `/collections` to chase the overdue invoices it surfaced
- `/weekly-review` for the full money + content retro
