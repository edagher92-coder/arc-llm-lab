"""
Snow Flow Sydney — Meta Ads API toolkit
Direct Graph API access. No browser, no permission popups.

SETUP (one time):
1. Get an access token (see TOKEN section below)
2. Save it in a file called meta_token.txt in this same folder (just the token, nothing else)
   — OR set the META_ADS_TOKEN environment variable.
3. Run:  python meta_ads_api.py status      <- safe read-only test

GUARDRAIL: budget/spend functions print a confirmation and require typing YES.

NOTE ON ENVIRONMENT: this must run where (a) meta_token.txt / META_ADS_TOKEN is present
AND (b) the network can reach graph.facebook.com. The Claude Code *web* sandbox blocks
facebook.com ("Host not in allowlist"), so run this from your connected Snowflow Socials
project (or any machine with the token + open network), not the code sandbox.
"""

import sys
import os
import json
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

API = "https://graph.facebook.com/v25.0"
AD_ACCOUNT = "act_179081790"  # Snow Flow Sydney ad account

TOKEN_FILE = Path(__file__).parent / "meta_token.txt"


def token() -> str:
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    env = os.environ.get("META_ADS_TOKEN")
    if env:
        return env.strip()
    sys.exit("No meta_token.txt next to this script and no META_ADS_TOKEN env var. Paste your access token first.")


def call(method: str, path: str, params: dict | None = None) -> dict:
    params = dict(params or {})
    params["access_token"] = token()
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        req = urllib.request.Request(f"{API}/{path}?{data.decode()}")
    else:
        req = urllib.request.Request(f"{API}/{path}", data=data, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        sys.exit(f"Meta API error {e.code}: {body}")


# ---------- READ (safe, no confirmation needed) ----------

def status():
    """List campaigns -> ad sets with status, budget, results."""
    camps = call("GET", f"{AD_ACCOUNT}/campaigns",
                 {"fields": "name,status,daily_budget,lifetime_budget,objective", "limit": 50})
    for c in camps.get("data", []):
        print(f"\nCAMPAIGN  {c['name']}  [{c['status']}]  id={c['id']}")
        adsets = call("GET", f"{c['id']}/adsets",
                      {"fields": "name,status,daily_budget,lifetime_budget", "limit": 50})
        for a in adsets.get("data", []):
            budget = a.get("daily_budget") or a.get("lifetime_budget") or "campaign-level"
            if str(budget).isdigit():
                budget = f"${int(budget)/100:.2f}"
            print(f"   ad set  {a['name']}  [{a['status']}]  budget={budget}  id={a['id']}")


def insights(days: int = 7):
    """Spend + results for the last N days."""
    r = call("GET", f"{AD_ACCOUNT}/insights",
             {"fields": "spend,impressions,reach,clicks,actions",
              "date_preset": f"last_{days}d" if days in (7, 14, 30) else "last_7d",
              "level": "campaign"})
    print(json.dumps(r.get("data", []), indent=2))


def pages():
    """List the pages this token can use (find your Snow Flow page_id + instagram id)."""
    r = call("GET", "me/accounts", {"fields": "name,id,instagram_business_account", "limit": 50})
    for p in r.get("data", []):
        ig = (p.get("instagram_business_account") or {}).get("id", "—")
        print(f"PAGE  {p['name']}  page_id={p['id']}  ig_id={ig}")


def _resolve_page():
    """Auto-pick the Snow Flow page (or the first page) + its linked Instagram id."""
    r = call("GET", "me/accounts", {"fields": "name,id,instagram_business_account", "limit": 50})
    data = r.get("data", [])
    if not data:
        sys.exit("Token has no pages (need pages_show_list scope). Run `pages` to check.")
    pick = next((p for p in data if "snow" in p.get("name", "").lower()), data[0])
    ig = (pick.get("instagram_business_account") or {}).get("id")
    return pick["id"], ig


def _cta(cta, link):
    """Build a call_to_action object for a link or message ad."""
    if cta == "MESSAGE_PAGE":
        return {"type": "MESSAGE_PAGE", "value": {"app_destination": "MESSENGER"}}
    if cta:
        return {"type": cta, "value": {"link": link}}
    return None


def _ad_image_urls(ad):
    """All image URLs an ad references (carousel cards or single image)."""
    if ad.get("cards"):
        return [c.get("image_url") for c in ad["cards"]]
    return [ad.get("image_url")]


# ---------- WRITE: status toggles (no money moves) ----------

def pause(object_id: str):
    """Pause a campaign, ad set or ad by id."""
    r = call("POST", object_id, {"status": "PAUSED"})
    print("Paused:", r)


def activate(object_id: str):
    """Activate a campaign, ad set or ad by id."""
    r = call("POST", object_id, {"status": "ACTIVE"})
    print("Activated:", r)


# ---------- WRITE: budget (GUARDED — requires typed confirmation) ----------

def set_daily_budget(object_id: str, dollars: float):
    """Change daily budget. Confirms before sending."""
    cents = int(round(dollars * 100))
    print(f"About to set daily budget of {object_id} to ${dollars:.2f} AUD.")
    if input("Type YES to confirm: ").strip() != "YES":
        sys.exit("Cancelled — no change made.")
    r = call("POST", object_id, {"daily_budget": cents})
    print("Budget updated:", r)


_IMAGE_HASHES: dict = {}


def _image_hash(acct: str, url: str) -> str:
    """Download a creative image and upload it to the ad account -> image_hash.

    Creatives built from external `picture` URLs fail intermittently (generic
    subcode 1487390) — pre-uploading via /adimages is the documented-robust
    path and also normalises formats Meta won't fetch (e.g. webp).
    """
    if url in _IMAGE_HASHES:
        return _IMAGE_HASHES[url]
    import base64
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as r:
        blob = r.read()
    resp = call("POST", f"{acct}/adimages", {"bytes": base64.b64encode(blob).decode()})
    images = resp.get("images", {})
    h = next(iter(images.values()))["hash"]
    _IMAGE_HASHES[url] = h
    print(f"      uploaded image ({len(blob)//1024} KB) -> hash {h[:12]}…")
    return h


def _with_targeting_automation(targeting: dict) -> dict:
    """The API requires an explicit advantage_audience flag (subcode 1870227).

    Default it OFF (0) so the ad set targets exactly the audience defined in
    ad-campaigns.json — Advantage audience expansion is a deliberate opt-in
    via a targeting_automation block in the JSON, never a silent default.
    """
    t = dict(targeting)
    t.setdefault("targeting_automation", {"advantage_audience": 0})
    return t


def _find_by_name(edge: str, name: str):
    """Return the id of an existing object with this exact name, or None.

    Makes launch --live idempotent: a re-run after a partial failure adopts
    the objects it already created instead of duplicating them.
    """
    r = call("GET", edge, {"fields": "name", "limit": 200})
    for o in r.get("data", []):
        if o.get("name") == name:
            return o["id"]
    return None


# ---------- LAUNCH: create corrected ads from ad-campaigns.json (all PAUSED) ----------

def launch(live: bool = False):
    """Create the campaigns/ad sets/ads defined in ad-campaigns.json.

    Everything is created with status PAUSED — nothing spends until you ACTIVATE it
    yourself in Ads Manager after review. Default is a dry run (prints the plan).
    Pass --live to actually create the objects.
    """
    cfg_path = Path(__file__).parent / "ad-campaigns.json"
    if not cfg_path.exists():
        sys.exit("No ad-campaigns.json next to this script.")
    cfg = json.loads(cfg_path.read_text())
    acct = cfg.get("ad_account") or AD_ACCOUNT
    page_id = cfg.get("page_id")
    ig_id = cfg.get("instagram_actor_id")
    if ig_id and "REPLACE" in str(ig_id):
        ig_id = None

    if live and (not page_id or "REPLACE" in str(page_id)):
        # No page_id set — resolve it from the token instead of making the user edit JSON.
        page_id, _auto_ig = _resolve_page()
        # Deliberately do NOT auto-attach the page's instagram_business_account
        # id as instagram_actor_id: adcreatives requires an IG account connected
        # to the AD account (a different id space) and rejects the business-
        # account id with "(#100) must be a valid Instagram account id". Without
        # the param, Meta uses the Page-backed IG identity automatically. Set
        # instagram_actor_id in ad-campaigns.json only with a verified id.
        print(f"Auto-resolved page_id={page_id}")

    print("LIVE — creating objects PAUSED.\n" if live else "DRY RUN — no API calls. Pass --live to create (PAUSED).\n")

    if live:
        missing = [ad["name"]
                   for camp in cfg["campaigns"]
                   for aset in camp["adsets"]
                   for ad in aset["ads"]
                   if any((not u) or "REPLACE" in str(u) for u in _ad_image_urls(ad))]
        if missing:
            sys.exit("Set a REAL Snow Flow machine photo URL (image_url) for these ads before --live: "
                     + ", ".join(missing)
                     + "\n  - easiest: open the product on snowflow.com.au, right-click the photo, Copy image address (a cdn.shopify.com URL), paste it as image_url"
                     + "\n  - or commit the photo to automation/media/ and use its jsDelivr URL")

    for camp in cfg["campaigns"]:
        print(f"CAMPAIGN  {camp['name']}  [{camp['objective']}] -> PAUSED")
        cid = None
        if live:
            cid = _find_by_name(f"{acct}/campaigns", camp["name"])
        if live and cid:
            print("  campaign id:", cid, "(reused existing)")
        elif live:
            c = call("POST", f"{acct}/campaigns", {
                "name": camp["name"],
                "objective": camp["objective"],
                "status": "PAUSED",
                "special_ad_categories": json.dumps(camp.get("special_ad_categories", [])),
                # Required by the API when budgets live on the ad sets (error
                # subcode 4834011). False = each ad set keeps its own budget,
                # no 20% cross-sharing — budget changes stay an explicit-YES.
                "is_adset_budget_sharing_enabled": "false",
            })
            cid = c["id"]
            print("  campaign id:", cid)

        for aset in camp["adsets"]:
            print(f"  ADSET  {aset['name']}  ${aset['daily_budget']}/day  [{aset.get('destination_type', 'LINK')}]")
            asid = None
            if live:
                asid = _find_by_name(f"{cid}/adsets", aset["name"])
            if live and asid:
                print("    adset id:", asid, "(reused existing)")
            elif live:
                body = {
                    "name": aset["name"],
                    "campaign_id": cid,
                    "status": "PAUSED",
                    "daily_budget": int(round(aset["daily_budget"] * 100)),
                    "billing_event": aset.get("billing_event", "IMPRESSIONS"),
                    "optimization_goal": aset.get("optimization_goal", "CONVERSATIONS"),
                    # The API now requires an explicit bid strategy (error
                    # subcode 2490487). Lowest-cost auto-bidding needs no bid
                    # amount and matches the previous implicit behaviour.
                    "bid_strategy": aset.get("bid_strategy", "LOWEST_COST_WITHOUT_CAP"),
                    "targeting": json.dumps(_with_targeting_automation(aset["targeting"])),
                }
                if aset.get("destination_type"):
                    body["destination_type"] = aset["destination_type"]
                if aset.get("promoted_object"):
                    body["promoted_object"] = json.dumps(aset["promoted_object"])
                elif aset.get("destination_type") == "MESSENGER" and page_id:
                    body["promoted_object"] = json.dumps({"page_id": page_id})
                a = call("POST", f"{acct}/adsets", body)
                asid = a["id"]
                print("    adset id:", asid)

            for ad in aset["ads"]:
                kind = "carousel" if ad.get("cards") else "single image"
                print(f"    AD  {ad['name']}  cta={ad.get('cta')}  ({kind})")
                if live and _find_by_name(f"{asid}/ads", ad["name"]):
                    print("      ad exists (reused) — skipping create")
                elif live:
                    base_link = ad.get("link", "https://www.snowflow.com.au")
                    link_data = {"link": base_link, "message": ad["primary_text"]}
                    top_cta = _cta(ad.get("cta"), base_link)
                    if top_cta:
                        link_data["call_to_action"] = top_cta
                    if ad.get("cards"):
                        kids = []
                        for c in ad["cards"]:
                            kid = {
                                "link": c.get("link", base_link),
                                "image_hash": _image_hash(acct, c.get("image_url")),
                                "name": c.get("headline", ""),
                                "description": c.get("description", ""),
                            }
                            cc = _cta(ad.get("cta"), kid["link"])
                            if cc:
                                kid["call_to_action"] = cc
                            kids.append(kid)
                        link_data["child_attachments"] = kids
                        link_data["multi_share_optimized"] = True
                    else:
                        if ad.get("headline"):
                            link_data["name"] = ad["headline"]
                        if ad.get("description"):
                            link_data["description"] = ad["description"]
                        if ad.get("image_url"):
                            link_data["image_hash"] = _image_hash(acct, ad["image_url"])
                    oss = {"page_id": page_id, "link_data": link_data}
                    if ig_id:
                        oss["instagram_actor_id"] = ig_id
                    cr = call("POST", f"{acct}/adcreatives",
                              {"name": ad["name"] + " creative", "object_story_spec": json.dumps(oss)})
                    adobj = call("POST", f"{acct}/ads",
                                 {"name": ad["name"], "adset_id": asid, "status": "PAUSED",
                                  "creative": json.dumps({"creative_id": cr["id"]})})
                    print("      ad id:", adobj["id"], "(PAUSED)")

    print("\nDone. Everything is PAUSED — review in Ads Manager, then ACTIVATE (status toggle).")


# ---------- CLI ----------

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        print("Commands: status | insights [7|14|30] | pages | pause <id> | activate <id> | budget <id> <dollars> | launch [--live]")
    elif args[0] == "status":
        status()
    elif args[0] == "insights":
        insights(int(args[1]) if len(args) > 1 else 7)
    elif args[0] == "pages":
        pages()
    elif args[0] == "pause":
        pause(args[1])
    elif args[0] == "activate":
        activate(args[1])
    elif args[0] == "budget":
        set_daily_budget(args[1], float(args[2]))
    elif args[0] == "launch":
        launch(live="--live" in args)
    else:
        print("Unknown command.")
