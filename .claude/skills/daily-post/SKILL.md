---
name: daily-post
description: |
  [CONTENT · Both brands] Produce a single ad-hoc post for either Snowflow
  or Profit Minute — caption, hashtags, Canva design, posts.json entry,
  optional calendar reminder. Use when the user says "draft today's post",
  "make a post about X", "single post for Snowflow / PM", or
  "one-off post on {topic}".
---

# Single post — either brand

## When invoked

1. Ask the user (briefly) for any of these that aren't already given:
   - Brand: `snowflow` or `profit-minute`?
   - Topic / hook (one line)
   - Date + slot (default: next open slot from the brand's calendar)
   - Format: reel / carousel / photo
2. Locate the brand voice file:
   - Snowflow → `brand/voice-and-style.md`
   - Profit Minute → `profit-minute/brand/identity.md`
3. Draft:
   - Caption ≤600 chars, brand voice locked
   - Hashtags (15–18 IG) from the weekly rotation in the relevant
     `seo/strategy.md`
   - UTM-tagged firstComment URL
4. Invoke the `canva-design` skill with the brand kit + topic.
5. Append an entry to `automation/posts.json` with a unique `id`
   (e.g. `snowflow-adhoc-2026-06-15-launch`).
6. If a calendar reminder is wanted, create the Google Calendar event.

## Apply brand-specific rules

| Field | Snowflow | Profit Minute |
|---|---|---|
| CTA | `snowflow.com.au` or DM | `profitminute.com.au` lead magnet or affiliate |
| Disclaimer | EOFY: rotate from `legal/compliance-notes.md` | Tax/finance: "Information only — see your accountant." |
| Visual style | Midnight + pink, faceless | Cream paper + receipt math + AU stamp |
| Calendar colorId | 5 (banana) | 2 (sage) |

## When done

Hand back: post id, caption preview (first 100 chars), Canva URL list,
calendar event link (if created). Suggest `/post-now --dry-run` to verify
the pipeline picks it up.
