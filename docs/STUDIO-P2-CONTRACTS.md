# Studio Phase 2 contracts (M1)

The interfaces the three Studio Phase 2 lanes build against. Back end: `gateway/approvals.py`, `gateway/studio.py`, `gateway/studio_metrics.py`.
Everything here lives under `/approvals/studio` on the approvals server (127.0.0.1:8093). Times are epoch seconds. `*_gb` values are GiB (2^30),
the unit the governor writes. A value the PC cannot measure is `null`, never a guess.

## 1. Access tiers and cookies

| Tier | How it is obtained | Grants |
|------|--------------------|--------|
| `none` | nothing | Studio shell, manifest, icons (static, no data) |
| `ts` | cookie `gws`, only on the identity listener (127.0.0.1:8096), only while the request also carries an allowlisted `Tailscale-User-Login` equal to the login the cookie was minted for | every Studio route (GET and POST) except PIN-only ones: `POST /api/delete` and any `/api/dev*` route. Never tool-call approvals, history, Control Centre, governor mode/model/kill. |
| `pin` | cookie `gwa`, from `POST /approvals/login` with the PIN | everything |

- `gwa` (existing): `Path=/; Max-Age=43200; HttpOnly; Secure; SameSite=Strict`. Honoured on both listeners. Only the PIN sets it.
- `gws` (new, off by default): `Path=/approvals/studio; Max-Age=43200; HttpOnly; Secure; SameSite=Strict`. Minted on a GET to any `ts` route by an allowlisted login; a POST needs an existing `gws` (plus `X-Requested-With: approvals`, as every POST does). It never sets or satisfies `gwa`.
- Handlers get `req["tier"]` (`"pin"`, `"ts"` or `null`) and `req["login"]` (ts only). `req["authed"]` still means the PIN session only.
- `401 {"error": ...}` = no tier for this route. The page then shows the PIN form; after login the same page is `pin`.
- `Tailscale-User-*` headers are read only on the identity socket and only from a 127.0.0.1/::1 peer, exactly one header, RFC 2047-decoded, trimmed, lower-cased, exact match against `allow_logins`. On 8093 they are never read and are stripped from `req["headers"]`. `tailscale serve` adds them for tailnet users, strips client-supplied copies, and adds none for Funnel or tagged devices (https://tailscale.com/kb/1312/serve), so those fall back to the PIN.

Config (gateway.json, all optional):

```json
"studio": {
  "ts_identity": {"enabled": false, "allow_logins": ["elz@example.com"], "listen": "127.0.0.1:8096"},
  "metrics": {"governor_status": "C:\\AI\\governor\\public\\status.json", "governor_running": "C:\\AI\\governor\\running.json"}
}
```

`enabled` must be JSON `true` and `allow_logins` non-empty, or nothing is bound. A non-loopback `listen` is refused. Publish it with its own
serve port mapped at the root (for example `tailscale serve --https=8446 http://127.0.0.1:8096`) so browser paths start with `/approvals/studio`
and the `gws` cookie path matches.

## 2. `GET /approvals/studio/api/stream` (Server-Sent Events)

Tier `ts` or `pin`. Query: `backfill=0..900` (points in `hello`, default 900).
Response: `200`, `Content-Type: text/event-stream; charset=utf-8`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `Connection: close`,
no `Content-Length`. At most **4** streams at once across the server (this cap is shared with the future chat stream); the 5th gets
`429 {"error": "too many live streams (max 4); close another Studio tab"}`. The server ends a stream after 30 min; `EventSource` reconnects
(`retry: 3000`) and receives a fresh `hello`. Every event is safe to apply more than once.

Frames, in order: `retry: 3000`, then `hello`, then any of `m` / `job` / `sys`, plus a `: ping` comment every 15 s.

```
retry: 3000

event: hello
data: {"v":1,"seq":4182,"now":1760320000.4,"tick_s":1.0,"ping_s":15.0,"fields":["t","cpu","ram_used_gb","ram_total_gb","vram_used_gb","gpu_owner","queue","tps"],"points":[...],"jobs":[...],"sys":{...}}

event: m
data: {"t":1760320001.4,"cpu":12.3,"ram_used_gb":40.12,"ram_total_gb":63.6,"vram_used_gb":21.47,"gpu_owner":"llm","queue":0,"tps":null}

: ping

```

| Event | `data` | When |
|-------|--------|------|
| `hello` | full snapshot: `points` (last `backfill` fast points), `jobs` (same list as `GET /api/jobs`), `sys` | first, and again if the client fell too far behind (replace everything) |
| `m` | one metric point (below) | every sampler tick: 1 s while any stream is open or a job is queued/active |
| `job` | one public job, exactly as in `GET /api/jobs` (upsert by `id`), or `{"id":"5ee5ee01","gone":true}` when it left the list (deleted or aged out) | when that job's public dict changes (state, note, progress, step, eta_s, phase, fav, clips...) |
| `sys` | system dict (below) | when it changes |

Metric point (`m`, and the items of `points` / `fast` / `slow`):

| Field | Source | Notes |
|-------|--------|-------|
| `t` | sampler clock | epoch seconds, 1 decimal |
| `cpu` | Windows `GetSystemTimes` deltas | whole machine %, null off Windows |
| `ram_used_gb`, `ram_total_gb` | `GlobalMemoryStatusEx` (`/proc/meminfo` elsewhere) | |
| `vram_used_gb` | governor `public/status.json` `vram_used_gib` | read only when the file changes; null when missing or older than 120 s |
| `gpu_owner` | video Queue | `"video"` (render, linger or Video mode) or `"llm"` |
| `queue` | video Queue | queued + active jobs |
| `tps` | llama-server `/metrics`: Δ`tokens_predicted_total` / Δ`tokens_predicted_seconds_total` | generation speed of Qwen requests that finished since the previous point; null when none did, in video mode, or when `running.json` gives no port. The front end should hold the last value. |

`sys`:

```json
{"mode": "llm", "gov_mode": "MAX", "hold": false, "linger_until": null,
 "comfy": {"running": false, "session": false, "state": null}, "enabled": true,
 "governor": {"phase": "ready", "phase_since": 1760319000, "mode": "AUTO", "profile": "MAX", "loaded": true, "stale": false}}
```

`mode` is `"video" | "llm" | "busy"` (as `/api/system`). `governor` is null when `status.json` is missing; `stale: true` when it is older than 120 s.
Counters that move every second (ComfyUI idle seconds, disk, last speed) are not in `sys`; poll `/api/system` for those.

## 3. `GET /approvals/studio/api/stats`

Tier `ts` or `pin`. Both rings as JSON; starts (or wakes) the sampler.

```json
{"v": 1, "now": 1760320000.4, "tick_s": 1.0, "fields": ["t", "cpu", "ram_used_gb", "ram_total_gb", "vram_used_gb", "gpu_owner", "queue", "tps"],
 "fast": [{"t": 1760319100.4, "cpu": 8.1, "ram_used_gb": 39.8, "ram_total_gb": 63.6, "vram_used_gb": 21.4, "gpu_owner": "llm", "queue": 0, "tps": null}],
 "slow": [{"t": 1760233200, "cpu": 9.7, "ram_used_gb": 39.91, "ram_total_gb": 63.6, "vram_used_gb": 21.3, "gpu_owner": "llm", "queue": 0, "tps": 18.4}],
 "running": true, "parked": false}
```

`fast`: up to 900 points (1 s apart while watched, 10 s apart otherwise). `slow`: up to 1440 complete minutes; `t` is the minute start;
`cpu`, `ram_used_gb`, `vram_used_gb`, `tps` are means (nulls skipped), `ram_total_gb` and `gpu_owner` the last value, `queue` the maximum.
With nobody watching and no job for 60 s the sampler parks (no probes), so the rings have gaps; plot by `t`, not by index.

## 4. Future `POST /approvals/studio/api/chat` (Sonnet code-tab lane; not built in M1)

Tier `ts` or `pin`; `X-Requested-With: approvals`. Request:

```json
{"messages": [{"role": "user", "content": "Explain this function"}], "system": "optional", "think": "off", "max_tokens": 2048, "temperature": 0.6}
```

`think`: `"off" | "low" | "medium" | "high"`. `max_tokens` 1..8192. Answer: `200` event stream (same headers as section 2, counts towards the
4-stream cap). Closing the connection cancels generation (the slot is erased).

```
event: think
data: {"text": "The user wants"}

event: delta
data: {"text": "This function"}

event: usage
data: {"prompt_tokens": 812, "completion_tokens": 344}

event: timings
data: {"prompt_ms": 640.2, "prompt_per_s": 1268.3, "predicted_ms": 18120.5, "predicted_per_s": 18.98, "draft_n": 210, "draft_accepted": 151}

event: done
data: {"finish_reason": "stop"}
```

`finish_reason`: `"stop" | "length" | "cancelled" | "error"` (`error` adds `"error": "..."`). `usage` and `timings` come once, just before `done`.
Refusals before any stream (plain JSON):

| Status | Body | Meaning |
|--------|------|---------|
| 400 | `{"error": "messages must be a non-empty list"}` | bad request |
| 401 | `{"error": "log in with your PIN first"}` | no tier |
| 409 | `{"error": "...", "reason": "paused"}` | GPU is in Video mode, a render or ComfyUI session holds it, or the governor is OFF |
| 429 | `{"error": "...", "reason": "busy", "retry_after": 5}` | another chat is generating, or the stream cap is reached |
| 502 | `{"error": "the language model did not answer"}` | llama-swap down |

## 5. Front-end modules (Fable lane)

`api` (one per page, owns the single `EventSource`):

```js
api.on(event, fn)        // event: "hello" | "m" | "job" | "sys" | "open" | "error" | "auth"; fn(data). Returns an unsubscribe function.
api.get(path)            // GET  "approvals/studio/api/" + path -> parsed JSON; throws {status, error}
api.post(path, body)     // POST with X-Requested-With: approvals; same errors
api.state                // {points: [...], jobs: Map(id -> job), sys: {...}, live: bool} kept current from the events
```

Rules: open one stream per tab and only while `document.visibilityState === "visible"`; close it on hide. On `401` emit `"auth"` (show the PIN
form). On `429` or repeated errors fall back to polling `/api/stats` + `/api/jobs` + `/api/system` every 5 s. `hello` replaces state;
`job` upserts, `{gone: true}` removes.

`charts`:

```js
const c = charts.spark(el, series, opts)   // el: container element; series: [{t, v}] or [number|null]; returns {update(series), destroy()}
// opts: {min, max, unit: "%" | "GiB" | "t/s", label, height: 32, gap_s: 5, colour: "--accent", fill: true}
```

Inline SVG only (the shell CSP has no external scripts or styles). A `null` value or a gap in `t` longer than `gap_s` breaks the line; never
interpolate across it. Colours come from CSS custom properties so light and dark themes both work. Missing data reads "Unknown".

## 6. Operational notes

- The stream must reach the browser unbuffered. The tts_server `/tts/approvals` proxy reads whole responses (`r.read()`, 15 s timeout), so
  SSE does **not** work through it; reach Studio's stream through a direct `tailscale serve` mapping (8093 or the 8096 identity listener) or
  fall back to polling.
- Sampler budget: one daemon thread, < 0.5 % CPU, < 5 MB. It reads `status.json` only on mtime change and `running.json` likewise.
