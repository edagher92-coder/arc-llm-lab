---
name: apis
description: The account's complete API, MCP-server and connector registry — every model API, self-hosted MCP server, managed connector and service API we call, with its endpoint, key name, owning repo and guardrail. Use when Elie types /apis or asks what APIs/connectors/MCP servers we have, where something is hosted, which model IDs or prices are current, which key a thing needs, or how a machine reaches a service.
---

# APIs, MCP servers and connectors — the full registry

Everything we can call, in four groups. **Only groups 1 and 4 are self-hosted** —
group 2 is account-level OAuth managed by claude.ai, so there is no process to
move to the server PC.

Longer runbook (systemd/NSSM units, transport switching): `docs/mcp-hub.md` in
`Claude-code-`. This skill is the registry; that doc is the how-to.

Two rules govern every row below, and they are not negotiable:

- **NUMBERS RULE** — never fabricate a price or a date, and never send
  customer-facing prices, quotes, invoices or legal content to a non-Claude
  model. Unverified → `[CONFIRM: …]` gap.
- **Money/send guardrail** — anything that moves money or sends a message is
  READ/DRAFT-ONLY without an explicit YES from Elie.

---

## 1 · Model APIs

| Vendor | Endpoint | Models | $/Mtok (in/out) | Key |
|---|---|---|---|---|
| **Anthropic** | `POST api.anthropic.com/v1/messages`<br>headers `x-api-key`, `anthropic-version: 2023-06-01` | `claude-opus-5` **(pinned default lead)**, `claude-sonnet-5` (fan-out workhorse), `claude-haiku-4-5` (mechanical), `claude-fable-5` (frontier reserve) | 5/25 · 3/15 · 1/5 · 10/50 | `ANTHROPIC_API_KEY` |
| **OpenAI GPT-5.6** | `POST api.openai.com/v1/responses` (canonical for 5.6; chat/completions still accepted) | `gpt-5.6-sol` (alias `gpt-5.6`), `gpt-5.6-terra`, `gpt-5.6-luna` | 5/30 · 2.50/15 · 1/6 | `OPENAI_API_KEY` |
| **Ollama** (flat-rate sub) | `POST {base}/api/generate` · `GET {base}/api/tags`<br>Anthropic-compat path lets Claude Code itself run on it (Ollama ≥ 0.14) | 18-model fleet; bridge tier defaults to `glm-5.2:cloud`, the weekly bench re-allocates it | **$0 marginal** | `OLLAMA_API_KEY` |

**Sol** — GA 9 Jul 2026, self-serve, **1,050,000-token context**, 128k max output.
Also on AWS Bedrock via the `openai/v1/responses` path.

**Ollama bases** (`CLAUDE_ROUTER_OLLAMA_URL`, `CLAUDE_KIMI_OLLAMA_URL`):
Ollama Cloud `https://ollama.com`, or the Tailscale hub
`http://elzydlab.tail76b098.ts.net:11434`. Heavy/mid models never live on a
daily-use PC's GPU — a workstation hosts at most `llama3.2:3b` as the routing
classifier's floor.

**Boundary:** the OpenAI key is used only by `bench/frontier_bench.py` in
`claude-model-router`. **No production path routes customer work to a non-Claude
vendor.** The router enforces this in code — `validate_task_envelope` rejects
`stakes=True` paired with a bridge model.

Ladder (`router.py`): `haiku → sonnet → glm → opus → fable`. Live allocation:
`python3 router.py --doctor`.

---

## 2 · Self-hosted MCP servers (ours — group 1)

| Server | Repo → path | Launch | Surface |
|---|---|---|---|
| **snowflow-quoting** | `Claude-code-` → `snowflow/mcp/` | `python -m snowflow.mcp.server` | Quoting: `get_price`, `search_items`, `delivery_fee`, `build_quote_from_enquiry`, `machine_instructions`, resource `snowflow://pricing/catalogue`<br>Console: `ask_sam`, `list_inbox`, `ingest_email`, `draft_reply`, `approve_reply` |
| **hq-orchestrator** | `claude-model-router` → `hq_orchestrator/` | `python -m hq_orchestrator.server` | Delegation: task envelopes, artifacts, the cheapest-capable worker ladder |
| **snowflow-outlook** | `Claude-code-Agents` → `mcp-outlook/` | `snowflow-outlook-mcp` | `list_messages`, `get_message`, `create_draft`, `create_reply_draft`, `update_draft`, `list_drafts`, `send_draft`, `send_mail`, `move_message`, `delete_message`, `poll_inbox`, `create_event`, `find_meeting_times` |

Each is registered in its owning repo's `.mcp.json` and launches over **stdio**
locally — `pip install "mcp[cli]"` once. hq-orchestrator also needs `anthropic`
and `ANTHROPIC_API_KEY`; snowflow-outlook needs the Azure app registration
(`SNOWFLOW_OUTLOOK_TENANT_ID`, `SNOWFLOW_OUTLOOK_CLIENT_ID`) against Microsoft
Graph `v1.0`.

**Server PC (shared over Tailscale):**
```bash
pip install "mcp[cli]"
cd /path/to/Claude-code-
python -m snowflow.mcp.server --http --host 0.0.0.0 --port 8787
```
then on the laptop swap the stdio entry for:
```json
"snowflow-quoting": { "type": "http", "url": "http://<tailscale-host>:8787/mcp" }
```
**There is deliberately no auth layer — Tailscale IS the auth layer. Never
port-forward 8787 to the open internet;** the catalogue is commercial pricing.

Two safety notes:
- **snowflow-quoting enforces the NUMBERS RULE structurally.** Unverified items
  return `verified: false`, a `[CONFIRM: …]` string and a null price. There is no
  code path that can invent one.
- **snowflow-outlook is send-capable** (`send_mail`, `send_draft`,
  `delete_message`). The money/send guardrail applies in full: draft only, never
  send without an explicit YES. Its auto-drafter watcher has a sender allowlist
  (`AUTO_DRAFTER_ALLOWLIST`) so cold inbound is skipped before the LLM call.

---

## 3 · Managed connectors (claude.ai OAuth — NOT self-hostable)

Attached at session level, not processes on a machine. Managing them means
toggling them in claude.ai connector settings — there is nothing to host.

| Connector | What we use it for | Posture |
|---|---|---|
| **Xero** | Cash, P&L, receivables, top customers — the revenue-rescue numbers | **Read-only** |
| **Stripe** | Invoices, subscriptions, refunds, payment links | Read; **writes gated** |
| **Gmail** | Drafts + labels | **Draft-only** |
| **Microsoft 365 / Outlook** | Search of `sydney@snowflow.com.au`, calendar, Teams, SharePoint | **Read-only** |
| **Google Drive** | Claude HQ shared file layer | Read/write; ask before overwriting shared files |
| **Google Calendar** | Events, reminders | Read/write |
| **Canva** | Design + export; brand kit `kAGvrYhQjjk` | Read/write |
| **GitHub** | Repos, PRs, Actions, code search | Read/write |
| **Zapier** | 9,000+ app bridge | Read; **writes gated** |
| **Supabase** | AdPilot DB (RLS-scoped) | Read/write; never touch prod data |
| **Vercel** | AdPilot deploys, logs, analytics | Read; **deploys gated** |
| **Cloudflare** | Workers, Pages, KV, R2, D1 | Read/write |
| **Higgsfield** | Image/video/audio generation | Read/write |
| **PDF Viewer** | Render PDFs in session | Read-only |

**Money/send guardrail:** Stripe (refunds/charges/invoice-sends) and
Gmail/Outlook are **READ/DRAFT-ONLY without an explicit YES**. Xero is read-only
by design so it physically can't write. Real customer emails go from
`sydney@snowflow.com.au` by manual paste.

**Availability caveat:** a headless or cron run may not have these — an
interactively-authenticated connector can simply be absent. That is exactly why
unattended automation uses our own APIs (group 4) rather than a connector.

---

## 4 · Our service APIs (self-hosted / direct HTTP)

| Service | Endpoint | Key(s) | Notes |
|---|---|---|---|
| **Meta Graph — Ads** | `graph.facebook.com/v25.0` | `META_ADS_TOKEN`, `META_AD_ACCOUNT_ID` (`act_179081790`) | `/snowflow-ads` + `ads-manage.yml`. **PAUSED-only launches; budget changes need an explicit YES; never delete a campaign (archive).** Token never committed. |
| **Meta Graph — pages/posting** | `graph.facebook.com/v25.0` | `META_PAGE_ACCESS_TOKEN`, `META_PAGE_ID` | `automation/poster.mjs` (FB + IG), `ads-report.mjs` (read-only daily pull) |
| **Meta Graph — WhatsApp** | `graph.facebook.com/v21.0` | `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID` | Sam webhook ingress |
| **Sam webhook** | Cloudflare Worker (`automation/sam-webhook/`) | `SAM_APP_SECRET`, `SAM_VERIFY_TOKEN`, `SAM_CONSOLE_TOKEN` | Meta/WhatsApp/Vapi ingress → email/Excel |
| **Vapi (Phone Sam)** | `api.vapi.ai/assistant`, `/call` | `VAPI_PRIVATE_KEY`, `VAPI_ASSISTANT_ID`, `VAPI_WEBHOOK_SECRET` | Answers 0450 878 787; `vapi-register.yml` runs from a runner that can reach it |
| **ElevenLabs** | via Vapi | `ELEVENLABS_API_KEY` | Charlie voice |
| **Resend** | `api.resend.com/emails` | `RESEND_API_KEY` | Transactional email out of the Worker + Vapi webhooks |
| **Twilio** | `api.twilio.com` | `TWILIO_AUTH_TOKEN` | SMS path |
| **Microsoft Graph** | `graph.microsoft.com/v1.0` | `SNOWFLOW_OUTLOOK_TENANT_ID`, `SNOWFLOW_OUTLOOK_CLIENT_ID` | Backs the self-hosted snowflow-outlook MCP + Excel workbook writes. **Needs an Azure app registration** — if you don't have one, use the Zapier Outlook route below instead |
| **Outlook via Zapier** | `microsoft_outlook_*` actions | existing connection, no Azure app | The mailbox path that works **today** on the `sydney@snowflow.com.au` connection alone. Read with `find_email`; reply with **`create_draft_reply`** (draft only). The Sam console uses exactly this. **Never `send_email` / `send_draft_email` / `reply_to_email`** — those send |
| **Cloudflare API** | Workers/Pages deploy | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | `deploy-sam-webhook.yml` |
| **Stripe API** | direct (non-connector paths) | `STRIPE_SECRET_KEY` | **Money-gated** — spec-only from the reply engine; `payment.py` emits a payment-link *spec*, never calls Stripe |
| **Ask Sam** | static `web/` + Node app | — | Brain rebuilt from the verified sources; never hand-edit `knowledge.json` |

---

## 5 · Skill packs, plugins and agents (the Claude HQ tooling)

Not APIs, but the rest of what the account can call. Source of truth for all
plugin content is `Claude-code-Agents` → `plugins/`; `.github` carries only
pointer JSON, and the Drive **Claude HQ** folder is the policy mirror, not
executable truth. Change the repo, never the Drive copy.

| Pack | What | Default |
|---|---|---|
| **snowflow-hq** | Sam reception bot + Snow Flow operations skills | enabled |
| **hq-playbooks** | Sales / marketing / advisory agent playbooks | enabled |
| **ai-specialists** | 73 named specialist skills + `start-70` router | enabled |
| **community-\*** (20 packs) | 1,940 skills, risk-triaged | **installed, disabled** — enable a pack only when a task needs it, or trigger collisions and context noise follow |

Six external plugins vendored from public repos (MIT/Apache-2.0, attributed):
**watch** (video), **notebooklm**, **graphify-knowledge-graph**, **obsidian**,
**impeccable** (frontend design — the register to read before UI work),
**ponytail** (simplest-working-solution mode).

Business subagents live in `.claude/agents/`, synced from Claude HQ →
*06 - Agents, Playbooks & Skills*: `business-consulting-agent`,
`marketing-content-agent`, `daily-sales-engine`, `sales-hunter` — all governed
by `AGENTS.md` (>$500 escalation, $325 call-out, service area).

The same Drive folder holds the operating rules the agents inherit
(`SNOWFLOW-CAMPAIGN-RULES`, `-COMPLIANCE-RULES`, `-GEO-TARGETING`,
`-CREATIVE-GUIDELINES`, `-CHECKPOINTS`, `-COUNCIL-DECISIONS`). They are mirrored
into the repos; if the two disagree, the repo wins.

## 6 · Keys — where they live

**Never committed.** Env var locally; repo secret in Actions.

`ANTHROPIC_API_KEY` · `OPENAI_API_KEY` · `OLLAMA_API_KEY` · `META_ADS_TOKEN` ·
`META_PAGE_ACCESS_TOKEN` · `WHATSAPP_TOKEN` · `VAPI_PRIVATE_KEY` ·
`VAPI_WEBHOOK_SECRET` · `ELEVENLABS_API_KEY` · `RESEND_API_KEY` ·
`TWILIO_AUTH_TOKEN` · `CLOUDFLARE_API_TOKEN` · `STRIPE_SECRET_KEY` ·
`SNOWFLOW_OUTLOOK_CLIENT_ID`/`_TENANT_ID` · `SAM_APP_SECRET` ·
`CONFIG_SYNC_TOKEN` (father-repo sync) · `ASK_SAM_SYNC_TOKEN` (KB push).

If a key is missing the correct behaviour is a **clear skip with a named
variable**, never a crash and never a fabricated result.

---

## 7 · Adding one

New MCP server → follow `mcp-forge`: tool table first (one verb on one noun,
typed params, enums over free strings); pure-logic module (like
`snowflow/mcp/tools.py`) so it unit-tests without the SDK; thin FastMCP wrapper;
smoke test = `tools/list` + one happy call + one schema-reject returning
JSON-RPC `-32602`. Then register in the owning repo's `.mcp.json`, and add a row
**here and in `docs/mcp-hub.md`** — a server nobody registered is a server
nobody can call.

New third-party API → add the key to the table above with its guardrail, and
state plainly whether it can touch money, send a message, or see a price.
