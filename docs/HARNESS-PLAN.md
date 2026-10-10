# Harness plan (expert review, 2026-10-10)

This is the plan from the expert review that produced the [phone tool gateway](GATEWAY.md). Most P0 items are deployed: the harness text, result trimming, `skills`, `share_file`, the startup changes and the policy fixes. The `:chat` preset was not deployed: its reasoning-effort parameter name is unconfirmed. P1 is still open. Lines marked [CONFIRM] were not verified when the plan was written.


Verdict: the model is fine (same Qwen scores 97/100 under Claude Code). The phone path fails on harness discipline, all of it in code we own. Keep Open WebUI as the thin phone client; make the gateway the harness. Do not adopt OpenCode/Qwen Code for the phone path tonight (reasoning in section 5).

Sandbox note (VERIFIED): `pip install fastmcp==3.4.8` works here and all of gateway.py's imports resolve. gateway.py's docstring says 4.1.0; live is 3.4.8. Pin 3.4.8 everywhere.

## 1. Diagnosis (evidence in brackets)

**Tool use inconsistent**
- The model gets zero rules. FastMCP's defaults are the only guidance: `search_tools` = "Search for tools using natural language…", `call_tool` = "Call a tool by name… discovered via search_tools" [bm25.py:120, base.py:234]. `FastMCP(instructions=...)` is unused [gateway.py:186]. No preset system prompt tells Qwen to search before saying "I can't", to copy `input_schema` exactly, or how NEEDS APPROVAL works. Claude Code works because every tool carries usage rules and the system prompt defines the loop; we ship none of that.
- Every "do" action costs two round trips (search, then call): nothing pinned acts [pin: Read/Grep/Glob/fetch/time]. At ~30 tok/s with thinking, that is minutes.
- Thinking per step: with tools present the template injects "Reasoning effort is set to xhigh…" on every request [qwen38-template.jinja:66-67]; the default preset sends `thinking_budget_tokens: 2048` [config.yaml:29], a key I cannot confirm llama-server honours [CONFIRM]; if ignored, the server cap 4096 applies = up to ~2 min of thinking per tool step.
- No result truncation in the gateway. pc_PowerShell/pc_Read output is capped only by Claude Code's 30,000-char default (claude-mcp.cmd sets no caps). One big result fills a 57K window and evicts the cached prefix.
- `pc_Skill` is classed `write` [policy.write]: loading a skill needs phone approval.
- Duplicate tool servers: mcpo/config.json spawns time/files/context7/fetch/browser/pc AND /gw spawns the same set (two Claude Code instances, two Playwrights, an npx registry check each start).

**Skills feel absent**: only reachable via `pc_Skill` (behind search, write-intent, Claude-skills-only). No catalogue, no progressive disclosure. Open WebUI 0.11's built-in `view_skill` needs built-in tools on (+5,350 prefix tokens, TOOL-CALLING.md) — reject.

**Startup**: (a) mcpo starts ~8 stdio servers sequentially, twice (above); (b) `npx -y` and `uvx` resolve at each start; (c) BALANCED unloads the 17 GB model after 30 idle min [profiles.json], so the first phone message after a break pays a model load plus a cold tool-bundle prefill (15.6 s measured). Nothing logs startup time.

**Files**: Qwen writes to C:\AI\shared; nothing serves it. `tailscale serve` changes need UAC, but /tts (8092) is on the tailnet and already proxies /approvals to 8093 — reuse it.

## 2. P0 tonight (gateway + bundle; all testable here)

### P0-1 Harness text: instructions + tool descriptions (gateway.py, new `prompts/phone-system.md`)
Spec:
- `FastMCP(name, instructions=PROMPT)`.
- New `Describe(Transform)`: rewrites descriptions of `search_tools`, `call_tool` and pinned tools from `CFG["descriptions"]` (≤300 chars each, with usage rules, e.g. search_tools: "Find a tool when none shown fits: shell, edit/write files, browser, desktop, docs, skills. One short query of nouns. Then call_tool with the exact name and arguments matching input_schema."). Schemas unchanged.
- `prompts/phone-system.md` (~350 tokens, byte-stable): identity; "never say you lack a tool before search_tools"; one call per step unless independent; keep outputs small (Select-String/-Tail/line ranges); NEEDS APPROVAL flow (one line to user, repeat the same call after approval); deliverables → `share_file`; procedures → `skills`; end with VERIFIED/INFERRED. Install: paste into an Open WebUI model preset "Qwen (phone)" with built-in tools off, or inject from the `smart_tool_router` inlet when no system message is present.
Tests: list_tools shows rewritten descriptions; pinned count/order unchanged; tool-list hash identical across two calls.
Effect: fewer "no tool" refusals and wrong-name calls; target ≥8/10 on a 10-prompt phone eval (`tests/eval_prompts.json`, run on PC). Risk: one cold prefill. Rollback: remove config key.

### P0-2 Result truncation + loop hygiene (gateway.py Guard)
- In `on_call_tool` after `call_next`: for each TextContent, if len > `policy.max_result_chars` (default 12,000) keep head 9,000 + tail 2,500 + "[gateway: trimmed N chars; narrow with line ranges / Select-String / offset]". Log `ms`, `chars_in`, `chars_out` in audit.
- Unknown tool name in `call_tool`: catch, run BM25 on the name, return "Unknown tool X. Closest: a, b, c" (ToolError text, not exception trace).
- claude-mcp.cmd: `set BASH_MAX_OUTPUT_LENGTH=12000`, `set MAX_MCP_OUTPUT_TOKENS=6000`, `set CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH=512` [VERIFIED env names, research report §3].
Tests: 100 KB result trimmed to spec; small result untouched; non-text content passes; unknown name returns suggestions.
Effect: no single call can wipe the window; the model self-corrects names. Risk: none material. Rollback: `max_result_chars: 0`.

### P0-3 `skills` tool (new `skills.py`, mounted as local FastMCP tool, pinned)
- Config `skills.roots`: `C:\AI\skills`, `%USERPROFILE%\.claude\skills`, `%USERPROFILE%\.codex\skills` (the roots listed in `C:\AI\local-brain\SKILLS-INDEX.md`). Index every `*/SKILL.md` at start, re-index when a root's mtime changes; parse frontmatter `name`/`description` (fallback: dir name, first paragraph).
- One tool `skills(action: "search"|"load", query: str)`. search → top 6 `{name, description≤140, path}` via the BM25 index class. load → body without frontmatter, truncated per P0-2, plus "Reference files are under <dir>; pc_Read them when the skill says to." Intent `read`. Description ≤300 chars: "Your playbooks (ops, releases, debugging). search first, then load one and follow it."
- `pc_Skill` → `hide` (replaced).
Tests: fixture tree with 3 skills (one bad frontmatter); search ranks by description; load strips frontmatter; `../` rejected; missing root tolerated.
Effect: skills usable from the phone for ~120 prefix tokens. Rollback: unpin.

### P0-4 `share_file` outbox (gateway tool + approvals.py route + tts_server.py proxy)
- Config `outbox`: `public_base` ("https://<pc>.ts.net:8445/tts/outbox"), `dir` (C:\AI\outbox), `roots` ([C:\AI\shared, C:\AI\workspace]), `ttl_hours` 24, `max_mb` 200.
- Tool `share_file(path, zip=false)` (intent read, audited): `realpath` must sit under a root (commonpath check; outbox dir and C:\AI\gateway never allowed); file → copy, dir or zip=true → zipfile; dest `dir/<token>/<basename>` with `secrets.token_urlsafe(16)`; write `dir/index.json` {token, name, expires}; purge expired on every call and at start; return `{url, bytes, expires}`.
- approvals.py GET `/outbox/<token>/<name>`: token regex `^[A-Za-z0-9_-]{20,24}$`, name must equal stored basename, expired → 410. Headers: `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`, and **`Content-Security-Policy: sandbox allow-scripts allow-forms allow-popups`** on every response. Reason: the model authors the HTML; on the approvals page's origin it could POST an approval with the viewer's cookie. The sandbox gives it an opaque origin: no cookies, and the custom-header POST needs CORS the server never grants. `.html` inline (so the site opens); everything else `Content-Disposition: attachment`. Stream with `shutil.copyfileobj`.
- tts_server.py: `/outbox*` GET passthrough to 8093 like `_approvals`, streaming, 60 s timeout.
Tests: traversal and symlink escape rejected; token/name mismatch 404; TTL purge; CSP header on .html; zip of a dir; size cap; URL from `public_base`; end-to-end curl against the approvals server on a free port.
Effect: tap the link on the laptop, the site opens. Risk: anyone on the tailnet holding the 128-bit URL can fetch that file (TTL-bounded; acceptable). Rollback: remove tool from config.

### P0-5 Startup and duplication
- mcpo/config.json → only `gw`; delete the six duplicates.
- gateway.example.json files server: replace `cmd /c npx -y …` with the installed `node D:\local-ai-tools\node_modules\@modelcontextprotocol\server-filesystem\dist\index.js` [CONFIRM path; else keep npx].
- gateway.py: audit `ready: N tools from M servers in X.X s` at first list.
- profiles.json BALANCED `idle_unload_min` 30 → 120 (A/B; pressure rules still unload).
Tests: config JSON validity; gateway builds from the example config with a fake stdio server. Effect: one Claude Code process instead of two, ~20-40 s faster hub start [INFERRED], fewer cold model loads. Rollback: `backup/` in the bundle.

### P0-6 Policy fixes
`pc_Skill` → hide; `share_file`, `skills` → read; `max_identical_calls` stays 3. Per-preset: add `qwen3.8-27b:chat` in llama-swap config.yaml = thinking on, `chat_template_kwargs.reasoning_effort: medium` (drops the xhigh instruction), Qwen thinking sampling (temp 1.0/top_p 0.95/top_k 20), and confirm `thinking_budget_tokens` vs the real param name on the PC before relying on it [CONFIRM]. Phone preset uses `:chat`; multi-step jobs use `:code`.

## 3. P1 next

### P1-1 Server-side `agent` tool (the real harness)
`agent(task, preset=":code", max_steps=25)`: a loop inside the gateway against `http://127.0.0.1:8090/v1` with a compact Claude-Code-style system prompt (plan → act → verify, todo list, one tool per step, P0-2 truncation), full catalogue via BM25, same Guard. Transcript persisted to `state/agent-<id>.json`; on NEEDS APPROVAL returns `{status:"paused", approvals:[ids]}`, resumes with `agent(resume=id)`; returns a summary plus `share_file` links. Tests against a mock OpenAI server. Risks: single-slot contention (outer request waits; host-RAM cache restores its prefix, measured 1.5 s), Open WebUI tool timeout [CONFIRM]. This is what lets "build me a website" finish in one phone message.

### P1-2 Lazy downstream spawn
Cache the catalogue (`state/catalog.json`), serve list/search from it, connect a server on first `call_tool` for its namespace; parallel connect on cold start. Risk: stale schemas; refresh on each full start.

### P1-3 Measurement
Per-request `cache_n/prompt_n`, steps and wall time in the audit log; 10-prompt phone eval script; stats page shows "tool steps this reply".

## 4. Harness choice
Keep Open WebUI + gateway. The same model and tools score 97/100 under a disciplined harness; the phone path lacks the discipline, not the model or the plumbing. OpenCode/Qwen Code are desktop coding agents: large fixed prompts (Codex measured 15.8K vs 6.5K), no PIN-approval hook, a second chat history, another tailnet surface to secure. Try Qwen Code later as a desktop CLI beside claude-qwen, not as the phone harness. P1-1 gives us the agent loop where we control prompt, truncation, approvals and audit.
