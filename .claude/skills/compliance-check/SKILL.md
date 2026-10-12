---
name: compliance-check
description: |
  [REVIEW] Audit draft posts (in posts.json, weekly drafts, or pasted text)
  against the brand's hard rules — EOFY disclaimer presence + phrasing
  accuracy, UTM tagging, hashtag count, caption length, faceless-visual
  rule, one-CTA rule, tax-fact accuracy. Use when the user says
  "compliance check", "audit these drafts", "is this ATO-safe?",
  "check before I post", or "review for legal".
---

# Compliance audit — pre-publish gate

## When invoked

Run the checklist below against every draft in scope. Report PASS/FAIL per
post with specific reasons. Don't make changes — surface issues only.

## Snowflow checklist

| # | Rule | Source |
|---|---|---|
| 1 | EOFY posts must contain a disclaimer (caption, not bio) | `legal/compliance-notes.md` |
| 2 | Disclaimer phrasing matches an approved variant | `legal/compliance-notes.md` |
| 3 | No "you'll only deduct $1K" / "becomes a $1K deduction" — factually wrong | CLAUDE.md rule 1 |
| 4 | Operating leases NOT presented as IAWO-eligible | CLAUDE.md rule 2 |
| 5 | Caption ≤600 chars | `brand/voice-and-style.md` |
| 6 | One CTA per post (default snowflow.com.au or DM) | CLAUDE.md rule 5 |
| 7 | Hashtags: 15–18 IG / 5 FB | CLAUDE.md rule 6 |
| 8 | UTM-tagged on every link | CLAUDE.md rule 9 |
| 9 | First-comment URL on IG (firstComment field present) | CLAUDE.md rule 8 |
| 10 | Faceless visual prompt — no people / hands / faces | CLAUDE.md rule 7 |
| 11 | No fake stock counts / fake urgency | CLAUDE.md rule 4 |
| 12 | No discount-based promotion (EOFY angle IS the discount) | CLAUDE.md "What NOT to do" |

## Profit Minute checklist

| # | Rule | Source |
|---|---|---|
| 1 | Tax/ABN/GST/BAS/super mentions include "Information only — see your accountant." | `profit-minute/brand/identity.md` |
| 2 | Cost stack matches `profit-minute/content/` — no fabricated numbers | `profit-minute/brand/identity.md` |
| 3 | Anti-hype voice — no "$50K in 30 days" claims | `profit-minute/brand/identity.md` |
| 4 | UTM-tagged affiliate links match `profit-minute/monetization.md` | monetization.md |
| 5 | Caption ≤600 chars | brand/identity.md |
| 6 | One CTA per post | brand/identity.md |
| 7 | Faceless visual | brand/identity.md |
| 8 | Snowflow tie-in days (slushy / fairy floss / popcorn / açaí / soft serve / snow cone) include the natural mention | calendar |

## Output format

```
✓ snowflow-day-5 — PASS
✗ snowflow-day-8 — FAIL (3 issues)
  - Rule 1: EOFY post missing disclaimer
  - Rule 7: 22 hashtags (max 18)
  - Rule 8: firstComment URL has no UTM tags
```

## When done

Summarise: N posts passed, N failed, common failure mode. Suggest specific
edits but do NOT apply them automatically — wait for the user.
