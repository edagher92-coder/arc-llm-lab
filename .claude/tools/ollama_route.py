#!/usr/bin/env python3
"""ollama_route — send heavy, non-stakes work to a local or cloud Ollama model.

The bridge for Model Routing Policy v4.0 tier-0/1 (local Ollama + Ollama Cloud Pro).
Claude Code can't delegate to Ollama natively, so a Claude Code session or subagent
shells out to this CLI to offload bulk coding / long reasoning / summarising to
gpt-oss:120b, kimi-k2.7-code, etc. — keeping Claude quota for stakes work.

Server URL comes from CLAUDE_ROUTER_OLLAMA_URL (default http://localhost:11434).
On a secondary PC, point it at the MAIN server (elzydlab) over Tailscale:

    CLAUDE_ROUTER_OLLAMA_URL=http://elzydlab.tail76b098.ts.net:11434

(The main server must run Ollama with OLLAMA_HOST=0.0.0.0 so it listens on the
Tailscale interface, not just localhost.)

Usage:
    python ollama_route.py --model gpt-oss:120b-cloud "Summarise this changelog: ..."
    echo "refactor prompt" | python ollama_route.py --route heavy-code
    python ollama_route.py --list                       # models the server can see
    python ollama_route.py --route heavy-reason --json "..."   # full JSON response

Routes (task class -> default model; tune to your weekly benchmark):
    heavy-code    -> kimi-k2.7-code:cloud     bulk coding / refactors
    heavy-reason  -> gpt-oss:120b-cloud       long non-stakes reasoning / drafting
    trivial       -> llama3.2:3b              local floor (same model as the classifier)
    classify      -> llama3.2:3b              the router's own classifier

Hosting note (Model Routing Policy v5.1): workstations host ONLY the floor
model locally -- the heavy/mid tiers run on Ollama Cloud (the flat-rate
plan) or the Tailscale hub, so a daily-use PC's GPU stays free for work.

NUMBERS RULE: never send customer-facing price / quote / invoice / legal here.
Those stay on Claude (Sonnet/Opus). This tool is for heavy NON-stakes grunt work.
"""
from __future__ import annotations

import argparse
import json
import ipaddress
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_KEY = os.environ.get("OLLAMA_API_KEY", "").strip()
# Default to the local hub; if only an API key is set (no explicit URL), target
# Ollama Cloud — so this works from any machine with a key, incl. cloud sessions.
_DEFAULT_BASE = "https://ollama.com" if API_KEY else "http://localhost:11434"


def _bases() -> list[str]:
    """Priority-ordered, SSRF-filtered base URLs — same contract as
    router._ollama_bases and ollama_caller._bases. CLAUDE_ROUTER_OLLAMA_URL may
    be ONE url or a comma-separated chain (tailnet server, then a second host);
    https://ollama.com is appended when OLLAMA_API_KEY is set. A rejected base
    is dropped with a warning, never dialled."""
    raw = os.environ.get("CLAUDE_ROUTER_OLLAMA_URL", "").strip()
    urls = [u.strip().rstrip("/") for u in raw.split(",") if u.strip()] or [_DEFAULT_BASE]
    if API_KEY and "https://ollama.com" not in urls:
        urls.append("https://ollama.com")
    out: list[str] = []
    for u in urls:
        if u in out:
            continue
        ok, why = _is_allowed_base(u)
        if not ok:
            print(f"[ollama_route] BLOCKED base {u!r}: {why}", file=sys.stderr)
            continue
        out.append(u)
    return out


def _is_allowed_base(url: str) -> tuple[bool, str]:
    """SSRF guard — identical policy to router.is_allowed_base. Allow http/https
    to loopback, RFC1918 private, Tailscale (100.64/10, *.ts.net), single-label
    LAN, ollama.com, or a host in CLAUDE_ROUTER_OLLAMA_ALLOW_HOSTS. Reject
    file://, 169.254.169.254 (cloud metadata), and arbitrary public hosts."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError as exc:
        return False, f"unparseable URL: {exc}"
    if parsed.scheme not in ("http", "https"):
        return False, f"scheme '{parsed.scheme}' not allowed (http/https only)"
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "no host in URL"
    extra = {h.strip().lower() for h in os.environ.get("CLAUDE_ROUTER_OLLAMA_ALLOW_HOSTS", "").split(",") if h.strip()}
    if host in extra:
        return True, "allowlisted"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if ip.is_loopback:
            return True, "loopback"
        if ip in ipaddress.ip_network("100.64.0.0/10"):
            return True, "tailscale"
        if ip.is_link_local:
            return False, "link-local/metadata IP blocked (SSRF)"
        if ip.is_private:
            return True, "private"
        return False, f"public IP {host} blocked (SSRF)"
    if host in ("localhost", "ollama.com") or host.endswith(".ts.net") or "." not in host:
        return True, "allowed host"
    return False, f"public host '{host}' blocked (SSRF) — set CLAUDE_ROUTER_OLLAMA_ALLOW_HOSTS to permit it"




def _headers(base: str = "") -> dict:
    """Per-base headers (Codex review 2026-07-24): the reusable Cloud bearer
    token rides ONLY on https bases — never over plain-HTTP LAN hops, where it
    would be readable by anyone on the segment. Local daemons ignore auth."""
    h = {"Content-Type": "application/json"}
    if API_KEY and base.startswith("https://"):
        h["Authorization"] = "Bearer " + API_KEY
    return h


# NUMBERS RULE at the direct-CLI path (the bridge's last unguarded door).
# High-precision AND lenient by design (Elie's ruling): reviews / valuations /
# audits / plain code flow to the bridge; real customer commerce or legal
# content is refused. Hardened 2026-07-24 after Codex review, both directions:
#   under-match: "customer quote for 500 AUD" (non-$ currency), "draft the
#     customer contract", bare NDA / commercial lease now refuse;
#   over-match: bare shell params ($1, $2) in heavy-code prompts no longer
#     trip the gate — a $amount counts when money-shaped ($ + 2+ digits or
#     decimals) or next to a commerce verb, not on any dollar-digit token.
import re as _re

_STAKES_HINT_RE = _re.compile(
    r"(?i)"
    # customer-money nouns (any context)
    r"\b(invoice|refund|chargeback|remittance|payable|payslip|superannuation)\b"
    r"|\b(tax\s+invoice|purchase\s+order|payment\s+link|credit\s+card|bank\s+details|bsb|abn|gst)\b"
    # legal
    r"|\bliability\b|\bindemnif|terms\s+(?:and|&)\s+conditions|\blegal\s+(?:advice|letter|contract)\b"
    r"|\bnda\b|\bcommercial\s+lease\b"
    r"|\bdraft\w*\b[^\n]{0,40}\b(?:contract|agreement)\b"
    # customer/client commerce-or-legal combined context (either order)
    r"|\b(?:customer|client)s?\b[^\n]{0,60}\b(?:quote|quotation|contract|agreement|lease|price|pricing)\b"
    r"|\b(?:quote|quotation|contract|agreement|lease|price|pricing)\b[^\n]{0,60}\b(?:customer|client)s?\b"
    # money-shaped amounts: $ + decimals/thousands, $ + 2+ digits, non-$ currency codes
    r"|\$\s?\d+[.,]\d"
    r"|\$\s?\d{2,}"
    r"|\b(?:aud|nzd|usd|gbp|eur)\s?\d"
    r"|\d\s?(?:aud|nzd|usd|gbp|eur|dollars)\b"
    r"|[£€]\s?\d"
    # single-digit $N only with a commerce verb nearby (bare $1/$2 = shell params)
    r"|\b(?:charge|bill|pay|owe|cost|deposit|fee|hire)\w*\b[^\n]{0,30}\$\s?\d"
)


def _looks_like_stakes(text: str) -> bool:
    return bool(text) and bool(_STAKES_HINT_RE.search(text))


ROUTES = {
    "heavy-code": "kimi-k2.7-code:cloud",
    "heavy-reason": "gpt-oss:120b-cloud",
    "mid-tier": "glm-5.2:cloud",     # GLM 5.2: bulk reasoning between Sonnet and Opus
    "trivial": "llama3.2:3b",        # the workstation floor -- the one locally hosted model
    "classify": "llama3.2:3b",
}


_LAST_BASE = ""  # the base a successful request actually used (for status/errors)


def _request(path: str, timeout: int, data: bytes | None = None):
    """Try each SSRF-filtered base in order; return the first success. Raises
    the last error only when EVERY base fails (true multi-base failover).

    EVERY failure advances to the next base (Codex review 2026-07-24): in a
    heterogeneous chain the bases differ in model inventory AND auth — a local
    hub 404s a cloud-only model that ollama.com serves, and a 401 on one host
    says nothing about the next. So no 4xx is treated as globally definitive;
    the last error is surfaced only after the whole chain is exhausted. This
    matches router.py's per-base behaviour."""
    global _LAST_BASE
    bases = _bases()
    if not bases:
        raise SystemExit("no usable Ollama base (all rejected by the SSRF guard or unset).")
    last: Exception | None = None
    for base in bases:
        req = urllib.request.Request(base + path, data=data, headers=_headers(base))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                _LAST_BASE = base
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001 — every base gets its shot
            _LAST_BASE = base   # so _explain names the base that answered last
            last = e
    raise last if last else RuntimeError("all Ollama bases failed")


def _get(path: str, timeout: int):
    return _request(path, timeout)


def _post(path: str, payload: dict, timeout: int):
    return _request(path, timeout, data=json.dumps(payload).encode())


def _explain(e: Exception) -> str:
    where = _LAST_BASE or ",".join(_bases()) or "(no base)"
    # HTTPError is a URLError subclass: the server WAS reached but returned an error.
    if isinstance(e, urllib.error.HTTPError):
        try:
            body = e.read().decode()[:300]
        except Exception:
            body = ""
        return (f"Ollama HTTP {e.code} from {where}{': ' + body if body else ''} "
                "(server reached — check the model tag, or OLLAMA_API_KEY for the Cloud API)")
    if isinstance(e, ValueError):  # json.JSONDecodeError / UnicodeDecodeError
        return f"Ollama at {where} returned a non-JSON body (a proxy or error page?)"
    return (f"cannot reach Ollama at any of [{', '.join(_bases())}]: {e}. Is it running? On a "
            "secondary PC set CLAUDE_ROUTER_OLLAMA_URL to the main server's Tailscale address, "
            "or set OLLAMA_API_KEY to use the Cloud API.")


def generate(model: str, prompt: str, system: str | None, timeout: int) -> dict:
    payload = {"model": model, "prompt": prompt, "stream": False}
    if system:
        payload["system"] = system
    return _post("/api/generate", payload, timeout)


def _write_status(model: str, role: str) -> None:
    # Records the engine actually used, for claude_status_line.py to render a
    # live "offline"/"cloud" badge. Best-effort: never breaks a dispatch.
    try:
        # Badge derives ONLY from the base that actually served the request
        # (Codex review 2026-07-24): a set API key no longer masquerades a
        # local/Tailscale-served request as "cloud".
        engine = "cloud" if "ollama.com" in _LAST_BASE else "local"
        status_file = Path.home() / ".claude" / ".routing-status.json"
        status_file.parent.mkdir(parents=True, exist_ok=True)
        status_file.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "engine": engine,
            "model": model,
            "role": role,
            "source": "bridge",
        }), encoding="utf-8")
    except Exception:
        pass


def main() -> int:
    p = argparse.ArgumentParser(prog="ollama_route", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("prompt", nargs="*", help="prompt text (or pipe via stdin)")
    p.add_argument("--model", help="explicit Ollama model tag (e.g. gpt-oss:120b-cloud)")
    p.add_argument("--route", choices=sorted(ROUTES), help="pick a model by task class")
    p.add_argument("--system", help="optional system prompt")
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("--json", action="store_true", help="print the full JSON response")
    p.add_argument("--list", action="store_true", help="list models the server can see")
    p.add_argument("--allow-stakes", action="store_true",
                   help="override the NUMBERS RULE refusal (you assert this is NOT "
                        "customer money/legal content)")
    a = p.parse_args()

    if a.list:
        try:
            tags = _get("/api/tags", a.timeout)
        except Exception as e:
            print("error: " + _explain(e), file=sys.stderr)
            return 2
        for m in tags.get("models", []):
            print(m.get("name", "?"))
        return 0

    model = a.model or (ROUTES[a.route] if a.route else None)
    if not model:
        p.error("give --model TAG or --route {heavy-code,heavy-reason,trivial,classify}")

    prompt = " ".join(a.prompt).strip() or sys.stdin.read().strip()
    if not prompt:
        p.error("no prompt (pass as args or pipe via stdin)")

    # NUMBERS RULE: never send customer money/legal content to the open bridge.
    if not a.allow_stakes and (_looks_like_stakes(prompt) or _looks_like_stakes(a.system or "")):
        print("refusing: this prompt looks like customer money/legal content (NUMBERS RULE) — "
              "keep it on Claude (Sonnet/Opus). Re-run with --allow-stakes only if you are "
              "certain it is not.", file=sys.stderr)
        return 4

    try:
        resp = generate(model, prompt, a.system, a.timeout)
    except Exception as e:
        print("error: " + _explain(e), file=sys.stderr)
        return 2

    _write_status(model, a.route or "custom")

    if a.json:
        print(json.dumps(resp, indent=2))
    else:
        text = resp.get("response")
        if not text:
            print("error: no 'response' from the model; server said: "
                  + str(resp.get("error", resp))[:300], file=sys.stderr)
            return 3
        print(text.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
