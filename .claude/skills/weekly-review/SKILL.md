---
name: weekly-review
description: |
  [REVIEW] Run the Analyst agent on the tracking dashboard — review the
  past week's posts, surface what worked, recommend what to double down on
  and what to cut. Use when the user says "weekly review", "what's
  working?", "Sunday retro", "analyse the week", or "what should I boost?".
---

# Weekly retro — Analyst agent

## When invoked

0. **Pull the real money numbers first** (this is now a money + content retro,
   not just reach). If the Xero/Stripe MCP servers are connected:
   - **Xero** (read-only): `get_cash_position` (cash + overdue), `get_profit_and_loss`
     (revenue/expense trend), `get_contacts_and_receivables` (overdue ageing),
     `get_top_customers_by_revenue`. Report the week's cash movement + overdue
     total alongside content metrics — content that doesn't move dollars is noise.
   - **Stripe** (read-only): real sales / subscription / invoice activity for the
     week (Care Plan + consumables MRR, new subs, failed payments).
   - **Ad spend/results**: trigger `ads-report.yml` via `mcp__github__actions_run_trigger`
     (or read `tracking/dashboard.md` + `ads-log.json`) for real Meta spend vs result.
   If those servers aren't connected, skip and note the retro is reach-only.
1. Read `tracking/dashboard.md` for the past 7 days of logged metrics
   (Snowflow + Profit Minute combined).
2. Read `automation/posted-log.json` to confirm which posts actually went
   live and any errors encountered.
3. For each brand, compute the top + bottom 3 posts by:
   - Reach (or impressions if reach unavailable)
   - Saves + shares (intent signal — better than likes)
   - DM/comment ask-rate (leads-per-1k-reach)
   - For Snowflow: link clicks → snowflow.com.au
   - For Profit Minute: newsletter signups + affiliate clicks
4. Produce a 5-section retro:

### Section 1 — Top 3 winners (with WHY)
What pattern is repeatable? (Hook, format, time slot, hashtag set, visual.)

### Section 2 — Bottom 3 (with WHY)
Was it the topic, the slot, the hook, the visual, or just noise?

### Section 3 — Boost candidates
1–2 winners worth promoting with paid spend per `ads/eofy-ad-pack.md`.
Recommend budget tier (low: $5/day × 3 days; mid: $20/day × 7 days).

### Section 4 — Next-week adjustments
3 concrete moves: e.g. "Move Tuesday slot from 12:15 to 18:00 — 2 of 3
Tuesday posts underperformed at lunch."

### Section 5 — Pipeline health
- Calendar gaps (days without posts.json entries)
- Pending design tasks (post IDs without images in automation/media/)
- Posted-log errors needing investigation

## Format

Plain markdown, scannable in <60 seconds. Numbers first, narrative second.

## When done

Optionally suggest:
- `/snowflow-week` or `/profit-minute-week` to fill calendar gaps
- The boost candidates to set up in Meta Ads (point at `ads/eofy-ad-pack.md`)
