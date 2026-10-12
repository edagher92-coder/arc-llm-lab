---
name: canva-design
description: |
  [DESIGN] Generate a brand-aligned Canva design via the Canva MCP server.
  Picks the right aesthetic automatically based on brand context. Use when
  the user says "design Day N", "make the Canva", "generate visuals",
  "Canva for {topic}", or when another skill (snowflow-week,
  profit-minute-week, daily-post) needs artwork.
---

# Canva design — brand-aligned

## When invoked

1. Determine brand from context (Snowflow vs Profit Minute) — if unclear,
   ask once.
2. Build the Canva MCP prompt using the brand kit below. Pass the Snowflow
   brand kit id `kAGvrYhQjjk` via `generate-design`'s `brand_kit_id` so the
   palette/fonts come through automatically.
3. Call `mcp__*__generate-design` with `design_type: instagram_post`
   (1080×1350). Returns 4 candidates, each with a `candidate_id`.
4. Return all 4 candidate URLs so the user can pick a favourite. Don't pre-pick.
5. **Close the loop — own the export** (this is the step that finishes the
   asset; don't just "suggest" it):
   a. On the user's pick, call `mcp__*__create-design-from-candidate`
      (`job_id` + `candidate_id`) to materialise a real design (`design_id`
      starts with `D`).
   b. Call `mcp__*__export-design` with `type: jpg`, `width: 1080`,
      `height: 1350` → returns a download URL.
   c. `curl -sL` that URL into `automation/media/<post-id>.jpg`, then commit
      (or use `mcp__github__create_or_update_file`). This closes the manual
      gap that `add-to-feed`, `snowflow-week`, `profit-minute-week` and
      `daily-post` all depend on — the posts.json `imageUrl` then resolves.
   d. Adobe Express MCP is the fallback for post-processing (crop/resize to
      the right aspect ratio, grain, colour overlay) when Canva isn't enough
      — remember `adobe_mandatory_init` before any Adobe tool.

## Snowflow brand kit (Canva brand ID kAGvrYhQjjk)

- Palette: midnight `#0F1B3D` background, brand pink `#FF6FA0`, ice white
  `#FFFFFF`, gold `#E8B96E` accent
- Typography: Inter Tight ExtraBold for headlines, DM Mono for numerals
- Aesthetic: editorial / wedding-magazine, faceless products, golden-hour
  lighting where applicable
- EOFY posts: gold disclaimer footer at 8pt grey
- Faceless. Never include people, hands, or faces.

## Profit Minute brand kit

- Palette: receipt-white `#FAF9F4`, ink black `#0E0E10`, profit green
  `#16A34A`, loss red `#DC2626`, Aussie gold `#F2A93B` (stamp accents)
- Typography: Inter Tight ExtraBold + DM Mono (all dollar figures monospace)
- Aesthetic: torn-edge receipt card, paper texture, AU circular stamp top-left
- Every visual includes a real cost stack (cost / sell / margin / yearly net)
- Faceless. Document-like, not meme-like.
- Disclaimer footer: "Information only — see your accountant." at 8pt grey

## Output format for the user

Show all 4 Canva URLs as bullets. Don't pre-pick — let them choose.
Hint that 1080×1350 JPG is the right export size for `automation/media/`.
