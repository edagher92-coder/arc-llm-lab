---
name: snowflow-ads
description: |
  [ADS · live Meta account] Manage Snow Flow Sydney's Meta (Facebook/Instagram)
  ads via the Marketing API directly — no browser, no permission popups. Use
  whenever the user asks to check ad performance, pause/activate campaigns or ad
  sets, change budgets, clean up campaigns, launch the corrected EOFY/Range/Service
  ads, or anything involving Ads Manager / Facebook ads / Snow Flow Sydney ads.
---

# Meta Ads Manager (Direct API)

Manage the ad account through the Meta Marketing API instead of browser automation.
Browser automation on adsmanager.facebook.com triggers un-disableable permission prompts
(ad platforms are gated as high-risk) — the API path has none.

## ⚠️ Where this runs

This skill needs BOTH:
1. **A token** — `meta_token.txt` next to the script, or the `META_ADS_TOKEN` env var.
2. **Network access to `graph.facebook.com`.**

The **Claude Code web / repo sandbox blocks facebook.com** ("Host not in allowlist") and has
no token — so the script **cannot execute there**. Run it from the connected **"Snowflow
Socials (1)"** project (token + open network), or any machine with the token + open network.
From the code sandbox you can still *edit* this skill, the ad copy, and `ad-campaigns.json`.

### Hard-safe durable execution: GitHub Actions (recommended)

GitHub Actions runners have **open network** (not behind the sandbox allowlist), so they CAN
reach the Meta API. This is the secure, durable way to run the toolkit "from the repo":

1. One-time: GitHub repo → **Settings → Secrets and variables → Actions → New repository
   secret** → name **`META_ADS_TOKEN`**, paste your ~60-day token. (Encrypted, never committed,
   masked in logs.)
2. Run it: **Actions tab → "Meta Ads (manual)" → Run workflow** → pick `status` / `insights` /
   `pages` / `launch-dry` / `launch-live`.
3. Token expires (~60 days)? Regenerate (see Token maintenance) and update the one secret.

Budget changes are deliberately **not** exposed via Actions (they need the interactive YES
guardrail) — do those locally or in the Snowflow Socials project.

#### Trigger it for the user (GitHub MCP) — no clicking required

When the **GitHub MCP is connected**, don't tell the user to open the Actions tab — fire the
workflow directly with `mcp__github__actions_run_trigger`:

```
mcp__github__actions_run_trigger(
  owner="edagher92-coder", repo="Claude-code-",
  workflow_id="ads-manage.yml", ref="main",
  inputs={ "command": "status" }    # or insights / pages / launch-dry / launch-live
)
```

Then poll with `mcp__github__actions_list` / `actions_get` and read the result via
`mcp__github__get_job_logs`. Same for `ads-report.yml` (inputs `{ "dry_run": "true" }`).

GUARDRAIL: only `status` / `insights` / `pages` / `launch-dry` and `dry_run` reports are
pre-approved to trigger autonomously. **`launch-live` starts creating ad objects** — treat it
like a spend: get Elie's explicit YES first, exactly as with budget changes.

## Key facts

- Ad account: `act_179081790` (Snow Flow Sydney + Elie's personal — all real campaigns live here)
- Script: `meta_ads_api.py` in this folder
- Token: `meta_token.txt` in this folder (gitignored) or `META_ADS_TOKEN` env var
- Meta app: "Comments", App ID 614890192017160 (Business type, Marketing API enabled)
- API version: v25.0 (matches `meta_ads_api.py`), plain HTTPS via urllib — no pip installs needed

## Usage

```
python3 meta_ads_api.py status              # all campaigns + ad sets with status/budget (read-only)
python3 meta_ads_api.py insights 7          # spend/results last 7 days (read-only)
python3 meta_ads_api.py pages               # find your Snow Flow page_id + instagram id
python3 meta_ads_api.py pause <id>          # pause campaign/ad set/ad
python3 meta_ads_api.py activate <id>       # activate campaign/ad set/ad
python3 meta_ads_api.py budget <id> <AUD>   # change daily budget — see guardrail below
python3 meta_ads_api.py launch              # DRY RUN: print the 3 corrected ads it would create
python3 meta_ads_api.py launch --live       # create them PAUSED from ad-campaigns.json
```

For bulk operations the CLI doesn't cover, call the Graph API directly with the same token
(POST `https://graph.facebook.com/v25.0/<object_id>` with `status=PAUSED|ACTIVE|ARCHIVED`).

## Launching the corrected ads

`ad-campaigns.json` (this folder) encodes the **3 active ads** rebuilt with real pricing and
the DM-lock-in mechanic (full copy: `ads/active-3-refresh.md`):

1. **The Range** (DM lock-in) — "$2,000 to $23,995, a machine for every use case"
2. **EOFY machine sales** — scoped to sub-$20K machines (slush from $2,000)
3. **Service & Repair** — winter counter-seasonal (reel: `ads/service-repair-reel.md`)

Before `--live`: run `pages` to get `page_id`, paste it into `ad-campaigns.json`, and drop the
ad images. `launch --live` creates everything **PAUSED**. You review in Ads Manager, then
`activate <id>` the new ones and `pause <id>` the old ones.

## GUARDRAILS (Elie's explicit instructions — always follow)

1. **Always ask Elie before any budget or monetary change** (budget edits, new spends, boosts).
   Status toggles (pause/activate/archive) and all reads are pre-approved — just do them.
2. **`launch` creates everything PAUSED** — that's not a spend. But do NOT `activate` a newly
   launched ad without Elie's go (activating starts spend).
3. Never DELETE campaigns. Archive instead (reversible). Meta refuses to archive campaigns
   whose source post/page was deleted ("Ad Creative Is Incomplete") — leave those paused.

## Official price range (keep ad copy honest)

- Slush: SFG1 **$2,000** → SFX3 **$4,100**
- Soft serve / froyo / açaí: D200 **$5,500** → F2-E pump **$23,995**
- Full range framing: **$2,000 to $23,995** — "a machine for every use case"
- All inc GST. **EOFY write-off applies to assets <$20K excl GST** — the $23,995 F2-E does NOT
  qualify; never imply the top machine is "instantly deductible."

## Token maintenance

- Token type: ~60-day user token. If API calls return OAuthException 190 (expired):
  open https://developers.facebook.com/apps/614890192017160/marketing-api/tools/ ,
  tick ads_management + ads_read + read_insights, click Get Token, paste it. Save to
  `meta_token.txt` (overwrite). Tokens can't be scraped from the page — Elie must paste.
- PERMANENT FIX (pending, ~July 2026): add act_179081790 to the snowflowsydney business
  portfolio (business_id 1049680525649904) — blocked until Meta lifts the new-portfolio ad
  account cap — then assign to system user "Claude API" (ID 61590489518373) for a
  never-expiring token.

## History / context

Set up 2026-06-07. Account cleanup same day: 17 stale campaigns paused, 15 archived. Live Snow
Flow campaigns: CTWA Warm Retargeting, messenger_doc promos, EOFY posts. Installed into the
Claude-code- repo 2026-06-07 and extended with `launch` + `pages`.
