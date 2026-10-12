---
name: add-to-feed
description: |
  [OPS] Append a draft post (or batch of drafts) to automation/posts.json
  in the correct schema so the Meta auto-poster can publish it. Use when
  the user says "add this to posts.json", "queue this post", "stage these
  drafts", or "push this to the feed".
---

# Append to automation/posts.json

## When invoked

1. Read `automation/posts.json` to see the current schema and the highest
   `day` number per brand.
2. For each draft the user provides (or for the drafts already in the
   conversation):
   - Generate a unique `id`: `{brand}-day-{N}` for calendar posts, or
     `{brand}-adhoc-{YYYY-MM-DD}-{slug}` for one-offs
   - Convert AEST slot to UTC for `scheduledAtUtc`:
     `AEST hh:mm → (hh-10):mm UTC` (subtract 10 hours; cross midnight where needed)
   - Compose `imageUrl` as:
     `https://meetsam.netlify.app/media/{id}.jpg` — **never** a jsDelivr/raw.githubusercontent
     URL. `Claude-code-` is a private repo; those CDNs can't serve it and the URL
     will 404 at Meta's fetch time, not at validation time. `netlify.toml` publishes
     `automation/media/` verbatim to `/media/` on that Netlify site — the file must
     actually be committed there under the matching path for the URL to resolve.
   - Include `platforms: ["facebook", "instagram"]` unless specified otherwise
   - Compose `firstComment` with UTM-tagged URL + disclaimer (brand-specific)
   - **If the real photo/export isn't committed yet**, set `"status": "needs-media"`
     on the entry. `validate.mjs` will accept the entry (warning, not error) but
     `poster.mjs` structurally refuses to ever publish it — never invent a
     placeholder image or point the URL at generic stock/mockup art to make
     validation pass silently.
3. Validate caption ≤600 chars. Reject + report any that overflow.
4. Validate hashtag count: 15–18 for IG-bound posts.
5. Append the new entries to the array (do NOT replace existing entries).
6. Run `node automation/validate.mjs` — it fails closed on any image reference
   that isn't a real, committed `automation/media/` file under the
   `meetsam.netlify.app/media/` host (unless marked `needs-media`). Fix before
   committing.
7. Stage + offer to commit. Suggested commit message:
   `feed: queue {brand} {N} new posts`

## Entry schema (canonical)

```json
{
  "id": "snowflow-day-12",
  "brand": "snowflow",
  "day": 12,
  "scheduledAtUtc": "2026-06-08T09:30:00Z",
  "slotAest": "Mon 8 Jun 19:30",
  "pillar": "PROFIT",
  "format": "reel",
  "platforms": ["facebook", "instagram"],
  "imageUrl": "https://meetsam.netlify.app/media/snowflow-day-12.jpg",
  "caption": "…",
  "hashtags": ["#snowflowau", "…"],
  "firstComment": "Link → https://snowflow.com.au?utm_source=ig&utm_medium=organic&utm_campaign=eofy2026&utm_content=day12"
}
```

A carousel post uses `"slides": [...]` (array of the same `meetsam.netlify.app/media/...`
URLs) instead of a single `imageUrl` — every slide is validated individually.

## When done

Report: N entries added, the IDs, and — for any entry still missing its real
image — that it's marked `needs-media` and will not publish until the file is
committed to `automation/media/` and the status is cleared.
