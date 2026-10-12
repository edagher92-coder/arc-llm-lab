---
name: meta-setup
description: |
  [OPS] Walk the user through the ~30 min one-time Meta Auto-Poster setup
  (Facebook App, long-lived Page Access Token, Instagram Business ID,
  GitHub repo Secrets). Use when the user says "set up Meta", "wire up
  the auto-poster", "connect FB and IG", or "configure auto-posting".
---

# Meta Auto-Poster — guided setup

## When invoked

Open `automation/SETUP.md` and walk the user through Steps 1–6
interactively, ONE STEP AT A TIME. Do not dump the whole guide.

### Phase 1 — Meta App (Step 1 in SETUP.md, ~5 min)
Tell the user to go to https://developers.facebook.com/apps/ and create a
Business app. Confirm completion before moving on.

### Phase 2 — Token exchange (Step 2, ~15 min)
This is the hardest step. The user will:
1. Use Graph API Explorer to grant 7 permissions and generate a short-lived
   user token
2. Exchange for a long-lived user token (provide the curl command, ask them
   to paste the response)
3. Convert to a never-expiring Page token (provide the second curl command,
   parse the response, point them at the right `id` and `access_token`)

If they paste curl output, help them identify the right values — never ask
them to read JSON unaided.

### Phase 3 — Instagram Business ID (Step 3, ~2 min)
Give them the curl with their Page ID and Page token substituted. Parse
the response.

### Phase 4 — GitHub Secrets (Step 4, ~2 min)
Tell them exactly which 3 secrets to add and the exact names:
- `META_PAGE_ID`
- `META_PAGE_ACCESS_TOKEN`
- `IG_BUSINESS_ID`

### Phase 5 — Drop in images (Step 5, ~5 min)
Confirm they've exported their chosen Canva designs as 1080×1350 JPGs and
named them to match each post's `id` in posts.json.

### Phase 6 — Test (Step 6, ~5 min)
Direct them to Actions tab → Auto-post to Meta → Run workflow with
`dry_run` ticked. Read the log together. If it works, run without dry_run.

## Security notes

- Never ask the user to paste their App Secret or Access Token into chat.
  Tell them to paste it directly into the GitHub Secrets UI.
- If they accidentally paste a token, immediately tell them to revoke it
  at facebook.com → Settings → Apps and Websites and regenerate.

## When done

Confirm all 3 secrets exist + a successful non-dry run completed. Suggest
`/post-now` for the next manual trigger or just let cron handle it.
