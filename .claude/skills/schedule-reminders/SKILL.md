---
name: schedule-reminders
description: |
  [OPS] Create Google Calendar posting reminders for upcoming days in
  either brand's calendar. Use when the user says "schedule reminders
  for week N", "add the calendar entries", "queue the cadence", or
  "I want a popup before each post".
---

# Schedule Google Calendar posting reminders

## When invoked

1. Confirm which days/range/brand if not obvious from context.
2. **Idempotency precheck** — before creating anything, call `mcp__*__list_events`
   over the target date range and skip any day that already has a matching
   `{Brand} · Day {N}` reminder. Re-running this skill must not double-book.
3. For each remaining day, call `mcp__*__create_event` with:
   - `summary`: `{Brand} · Day {N} · {Pillar} {Format} — {topic}`
   - `startTime`: ISO 8601 with `+10:00` (AEST, Sydney is UTC+10 during the
     campaign window May–Sep)
   - `endTime`: startTime + 30 minutes
   - `timeZone`: `Australia/Sydney`
   - `colorId`: `5` for Snowflow (banana), `2` for Profit Minute (sage),
     `11` for EOFY climax (tomato red)
   - `overrideReminders`: `[{method: popup, minutes: 60}, {method: popup, minutes: 15}]`
   - `description`: pillar + format + slot + file reference
     (`content/week-N-posts.md` or `profit-minute/content/week-N-posts.md`)
3. Run as many `create_event` calls in parallel as you can.
4. After all events are created, report:
   - Number of events created
   - Markdown bullet list of htmlLink URLs (grouped by brand)
   - Any failures

## Slot table (memorise)

### Snowflow (AEST)
| Day | Pillar | Slot |
|---|---|---|
| Mon | Profit | 19:30 |
| Tue | Showcase | 12:15 |
| Wed | Venue | 12:30 |
| Thu | EOFY | 19:30 |
| Fri | Events | 11:30 |
| Sat | Showcase | 10:30 |
| Sun | Service | 11:00 |

### Profit Minute (AEST)
| Day | Pillar | Slot |
|---|---|---|
| Mon | Cart | 18:00 |
| Tue | Service | 12:00 |
| Wed | Educational | 13:00 |
| Thu | Cart | 18:00 |
| Fri | Weekend | 12:00 |
| Sat | Vending | 11:00 |
| Sun | At-home | 10:00 |

## When done

If posts.json doesn't yet have entries for those days, suggest running
`/snowflow-week` or `/profit-minute-week` next.
