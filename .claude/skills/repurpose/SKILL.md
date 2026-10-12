---
name: repurpose
description: |
  [STRATEGY] Turn a single feed post into the full cross-post matrix —
  YouTube Short, LinkedIn video/document, Pinterest Idea Pin, newsletter
  blurb, TikTok (Profit Minute only). Use when the user says "repurpose
  this post", "cross-post day N", "make this multi-platform", or
  "Producer agent".
---

# Producer — cross-post matrix

## When invoked

1. Identify the source post (by id, day number, or pasted content).
2. Read the source from `automation/posts.json` if available.
3. Produce the matrix below. Show outputs as ready-to-publish blocks,
   one per platform.

## Matrix — reels (Snowflow + Profit Minute)

| Platform | Adaptation | Notes |
|---|---|---|
| **Instagram Reel** | Source post | (already in posts.json) |
| **Facebook Reel** | Same caption, FB hashtag rules (5 only) | Already handled by poster |
| **YouTube Shorts** | Same vertical video, title = the hook + "(2026)", description = caption + 3 hashtags | RPM higher than IG — worth re-uploading |
| **LinkedIn video** | Same video, B2B-toned caption (drop emojis if any, lead with the number), no hashtags or max 3 | Snowflow only — LinkedIn is the B2B lever |
| **Pinterest Idea Pin** | Same vertical, keyword-rich title, board: "Sydney small-biz EOFY" (Snowflow) or "Aussie side hustles" (PM) | Long tail traffic |
| **TikTok** | Profit Minute ONLY — Snowflow audience doesn't convert on TT | Repost native, ATO disclaimer baked in |

## Matrix — carousels

| Platform | Adaptation |
|---|---|
| **Instagram Carousel** | Source post |
| **LinkedIn document post** | Same slides exported as PDF, B2B caption |
| **Pinterest** | Each slide → 1 standalone pin, all linked back to source |
| **Email newsletter** | Convert the slide content into a 200-word blurb. If the Gmail MCP is connected, create it as a **draft** via `create_draft` (labelled, never auto-sent) ready to drop into the next weekly send; otherwise output the blurb to paste manually. |

## Hashtag rules per platform

| Platform | Count | Source |
|---|---|---|
| IG | 15–18 | seo/strategy.md (rotation cluster) |
| FB | 5 | First 5 of IG set |
| YouTube | 3 in description | Same first 3 |
| LinkedIn | 0–3 max | Choose B2B-relevant only |
| Pinterest | 5–10 keyword-stuffed | Pinterest is a search engine, not a feed |
| TikTok | 4–6 | Match TikTok-native conventions |

## When done

Output a clean "Copy this to {platform}" block for each. Suggest which
platforms to skip if effort > value (e.g. skip LinkedIn for B2C Snowflow
showcase reels).
