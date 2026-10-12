---
name: snowflow-week
description: |
  [CONTENT · Snowflow] Generate the next 7 days of Snowflow Sydney posts —
  captions, hashtags, Canva designs, automation/posts.json entries, and
  matching Google Calendar reminders. Use when the user says
  "next week of Snowflow", "draft Snowflow week 2/3/4/5",
  "generate posts for the Snowflow campaign", or "Snowflow weekly".
---

# Snowflow — generate next week of posts

## When invoked

1. Find the next undrafted week in `content/30-day-calendar.md`. Cross-check
   `automation/posts.json` to see which day IDs (`snowflow-day-N`) are missing.
2. For each day in that week (run as much in parallel as possible):
   a. Pull pillar / format / slot from the calendar
   b. Draft a caption ≤600 chars in the voice defined by `brand/voice-and-style.md`
   c. Build the hashtag set (15–18 IG) by rotating the weekly cluster from
      `seo/strategy.md`
   d. Compose UTM-tagged first-comment URL:
      `https://snowflow.com.au?utm_source=ig&utm_medium=organic&utm_campaign=eofy2026&utm_content=day{N}`
   e. Append a fully-formed entry to `automation/posts.json` (matching the
      schema of the existing entries)
   f. Invoke the `canva-design` skill to generate matching artwork
3. If any Google Calendar reminder is missing for the slot, create it
   (yellow / colorId 5 for Snowflow).
4. Report concisely: days drafted, file paths, Canva URLs, any gaps.

## Hard constraints

- One CTA per post; default `snowflow.com.au` or DM
- EOFY disclaimer in caption (NOT bio) on every EOFY post — rotate phrasing
  using the approved set in `legal/compliance-notes.md`
- Lease vs chattel vs buy: operating leases are NOT IAWO-eligible. Don't
  conflate. Never write "becomes a $1K deduction" — assets >$1K still
  deductible, just depreciated.
- No emoji-spam, no false stock counts, no fake urgency, no people-faces
- Caption max 600 characters (IG truncation point)
- First-comment URL on IG (set `firstComment` field in posts.json)
- All links UTM-tagged per `seo/strategy.md`

## Voice (lock before drafting)

Confident Aussie, B2B-first, no corporate-speak. Sydney suburbs / hospitality
scene references where they fit. Numbers over adjectives. The EOFY tax angle
IS the discount — never add a price discount on top.

## When done

Hand back the list of new `snowflow-day-N` entries that landed in posts.json
and the Canva URLs, then suggest running `/canva-design` again if any design
needs a different angle.
