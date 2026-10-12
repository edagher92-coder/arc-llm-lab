---
name: profit-minute-week
description: |
  [CONTENT · Profit Minute] Generate the next 7 days of PROFIT MINUTE AU
  posts — receipt-card captions with real AUD margins, hashtags, Canva
  designs, posts.json entries, Google Calendar reminders. Use when the
  user says "next week of Profit Minute", "draft PM week N",
  "generate side-hustle posts", or "expand Profit Minute".
---

# PROFIT MINUTE AU — generate next week of posts

## When invoked

1. Find the next undrafted week in `profit-minute/content/30-day-calendar.md`.
   Cross-check `automation/posts.json` for missing `pm-day-N` IDs.
2. For each day:
   a. Read pillar from calendar: Cart / Service / Educational / Weekend /
      Vending / At-home
   b. Draft caption in **receipt-card format**:
      ```
      STARTUP             $X,XXX
      COST PER UNIT       $X.XX
      SELL PRICE          $X.XX
      MARGIN              XX%
      YEAR @ N EVENTS    $XX,XXX
      PAYBACK             X.X weeks
      ```
      Real AUD numbers sourced from `profit-minute/content/week-*-posts.md`.
   c. Hashtag set (15–18 IG) from `profit-minute/seo/strategy.md`
   d. Affiliate-tagged firstComment link per `profit-minute/monetization.md`
   e. Append JSON entry to `automation/posts.json` with id `pm-day-N`
   f. Invoke `canva-design` skill — cream paper #FAF9F4 + receipt aesthetic +
      Aussie-gold #F2A93B accent stamp
3. If a Google Calendar reminder is missing, create it (sage/green colorId 2).
4. Report what landed + gaps.

## Hard constraints

- Numbers-first, anti-hype voice (opposite of "I made $50K in 30 days" gurus)
- Tax/ABN/GST mentions: **"Information only — see your accountant."**
- Every post has a real cost stack — never fabricated
- Snowflow cross-promo on the 6 calendar days marked ✅: slushy, fairy floss,
  popcorn, açaí, soft serve, snow cone. Natural mention, no overt ad copy.
- One CTA per post — `profitminute.com.au` lead magnet OR an affiliate link
- Faceless. No people in shot.
- Caption ≤600 chars

## Affiliate stack (match to topic — don't crowbar)

Direct Snowflow link · Square · Xero/MYOB · Hnry · Stripe · Officeworks (via
Commission Factory) · Amazon AU · **Notion ($30/signup) · ChatGPT Teams ($50)
· Canva Pro ($36) · ElevenLabs ($25) · Adobe Creative Cloud ($60) · Shopify
AU ($58–150)**. The SaaS partners go on Wednesday educational carousels and
content-creator at-home posts where audiences are researching tools.

## When done

Report new `pm-day-N` entries + Canva URLs. Flag if Snowflow tie-in days
weren't naturally hit.
