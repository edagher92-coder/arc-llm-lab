---
name: plan-week
description: |
  [STRATEGY] Run the Strategist agent — plan the next week's content arc
  for either brand, choosing topics, slots, formats, and the through-line
  that ties the week together. Use when the user says "plan next week",
  "what should I post next week?", "strategy for week N", or
  "build me a weekly arc".
---

# Strategist — plan the next week

## When invoked

0. Check for a research brief at `tracking/research/YYYY-MM-DD-<brand>.md`
   (this Monday, Sydney date). If none exists or it's stale (>7 days), run
   `/snowflow-research` first — external signal should inform the arc, not
   be bolted on after. If the user explicitly wants a fast plan with no
   research pass, skip this step and say so in the WHY THIS ARC section.
1. Read the brand's 30-day calendar (`content/30-day-calendar.md` or
   `profit-minute/content/30-day-calendar.md`).
2. Read the last 7 days from `tracking/dashboard.md` (what's working).
3. Read `automation/posted-log.json` (what actually published).
4. Identify the week's THEME from the calendar's strategy arc:
   - Snowflow weeks: Awareness+Numbers → Product education → Social proof
     → Urgency → EOFY climax
   - Profit Minute: rotates 6 pillars in weekly cycle
5. For each day of the next week, output:

```
| Day | Pillar | Format | Slot AEST | Hook | Cross-post matrix |
```

The hook should be specific enough that a Copywriter could draft straight
from it. The cross-post matrix tells Producer where it goes
(YT Short + LinkedIn + Pinterest for reels; Pinterest + LinkedIn doc for
carousels).

6. Add a 2-paragraph WHY THIS ARC section — what the week is selling, how
   it builds on last week, what next week sets up.

## Constraints

- Stay within the calendar's overall arc unless you have a strong reason
  to deviate (e.g. a trending topic, a winner worth doubling down on)
- Don't suggest new pillars mid-week — the rotation is calibrated
- Snowflow: every Thu must be EOFY, no exceptions
- Profit Minute: every Wed must be Educational (the high-CPM slot)
- Sydney context where natural

## When done

Present the plan as a single table + the WHY paragraphs. Offer to chain
into `/snowflow-week` or `/profit-minute-week` to actually draft it.
