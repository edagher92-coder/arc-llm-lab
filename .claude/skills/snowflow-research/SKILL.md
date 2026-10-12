---
name: snowflow-research
description: |
  [STRATEGY] Pull external signal — competitor moves, seasonal/industry
  news, trending angles — into a dated research brief BEFORE planning the
  week's content. Feeds the weekly-planning skill; never writes captions
  itself. Use when the user says "research this week", "what's trending",
  "check competitors", or "any news to work into content".
---

# Researcher — external signal, before the Strategist plans

A thin, read-only step that runs **before** `/plan-week`: it looks outside
the repo (competitors, industry news, seasonal hooks, trending formats) and
writes a dated brief the Strategist agent can pull straight from. It never
drafts captions, never schedules, never touches `posts.json` — that's
`/plan-week` → `/snowflow-week` / `/profit-minute-week`'s job.

## When invoked

1. **Pick the brand(s):** Snowflow Sydney (B2B frozen-drinks/soft-serve
   equipment, EOFY campaign) and/or Profit Minute AU (faceless AU
   side-hustle margin-math). Default to whichever the user names; ask if
   ambiguous and both are mid-campaign.
2. **Check for an existing brief this week** at
   `tracking/research/YYYY-MM-DD-<brand>.md` (Monday of the current week,
   Sydney date). If one exists and is <7 days old, surface it instead of
   re-running searches — don't burn a research pass twice in one week
   unless the user explicitly asks to refresh.
3. **Run targeted searches** (WebSearch, 4–8 queries, not a broad crawl):
   - Snowflow: competitor hire/sale activity (party-hire equipment AU),
     Sydney hospitality/events industry news, EOFY asset write-off coverage
     for the current FY, seasonal hooks (school holidays, major Sydney
     events, weather-driven demand).
   - Profit Minute: trending AU side-hustle / margin-math topics, ATO/ABN
     changes relevant to hobbyist sellers, platforms other creators in the
     niche are using well.
   - Cross-brand: any format innovation worth testing (a Reel structure,
     hook style) — **never TikTok** per house rule, this repo's channels
     are FB/IG/YT/LinkedIn/Pinterest.
4. **Filter hard.** Most search results are noise. Keep only items that are
   (a) genuinely new since the last brief, (b) specific enough to turn into
   a hook, and (c) compliant with `legal/compliance-notes.md` — do not surface
   an angle that would require discount-based promos, TikTok, generic stock
   photography, or a tax claim broader than `legal/compliance-notes.md` allows.
5. **Write the brief** to `tracking/research/YYYY-MM-DD-<brand>.md`:

```markdown
# Research brief — <brand> — <Monday date>

## Signals worth acting on
- <finding> — source: <url> — suggested angle: <one line, not a full hook>
  (repeat, 3-6 items max — quality over volume)

## Noted but not actionable
- <finding> — why it doesn't fit (off-brand, needs [CONFIRM], too generic)

## Compliance flags
- Anything here that needs a fact check before it becomes a post
  (a price, a date, a regulatory claim) — mark [CONFIRM: ...], never assert it.
```

6. **Hand off, don't draft.** End by offering to chain into `/plan-week`,
   which should read this file alongside the 30-day calendar and dashboard.

## Constraints (non-negotiable, same as the rest of the kit)

- **Never fabricate a price, date, or statistic.** A search result claiming
  a number goes in as `[CONFIRM: <claim> — source <url>]` unless it's
  independently verified against `snowflow/reply_engine/pricing.py` or
  `legal/compliance-notes.md`.
- **No discount-based promotions, no TikTok, no generic stock/mockup
  photography** — filter these out before they reach the brief, don't
  leave it to the Strategist to catch.
- **Real Sydney/AU signal only** — skip US-centric trend reports that
  won't land with a Sydney B2B or AU side-hustle audience.
- Read-only: this skill never writes to `posts.json`, `content/`, or
  `profit-minute/content/`, and never calls `/post-now` or ad tools.

## When done

Present the brief (or the existing one if reused), then ask whether to
chain into `/plan-week` for this week's arc.
