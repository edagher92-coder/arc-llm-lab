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

## Remembered devices (gwd)

Enter the PIN once per device; that device then stays logged in for 90 days while its Tailscale IP stays the same.

- `POST /approvals/login` with `{"pin": ..., "remember": true}` also sets `gwd`: 32 random bytes as hex, `Path=/; Max-Age=7776000; HttpOnly; Secure; SameSite=Strict`. Without `remember: true` no `gwd` is set (the approvals page sends it, checked by default).
- Store `gateway/trusted-devices.json` (git-ignored, next to `approval-pin.json`): `sha256(token)` -> `{ip, created, expires, last_seen, ua[:120]}`. The raw token is never stored. At most 10 devices (oldest created is evicted), expired entries pruned on load and save, atomic write (temp + `os.replace`), survives restarts.
- Client IP = first `X-Forwarded-For` hop (added by `tailscale serve`) only when the TCP peer is loopback, otherwise the peer address.
- Device tier: a request with no live `gwa` but a `gwd` whose hash matches an unexpired entry bound to the current client IP gets a fresh normal `gwa` session (same cookie and SESSION_TTL), so every existing path works and `req["tier"]` is `"pin"`. IP mismatch, unknown token or malformed cookie: not authenticated, entry kept, not counted as a PIN failure (the next PIN login rebinds the entry to the new IP).
- Device-minted sessions are flagged. They may use everything (Studio, Code tab, stats, video jobs, mode) except `POST /approvals/<id>/approve|allow|deny` and `POST /approvals/devices/revoke`, which answer `401 {"error":"enter your PIN to approve actions","pin_required":true}`; the approvals page then shows the PIN box.
- `GET /approvals/devices` (any session): `[{id (first 8 hex of the hash), ip, created, expires, last_seen, ua, current}]`. `POST /approvals/devices/revoke {id}` (PIN session). `POST /approvals/devices/forget` (any session, CSRF header): removes this device's entry and clears `gwa` and `gwd` (`Max-Age=0`).
- `GET /approvals/pending.json` adds `X-Device-Until` (epoch seconds) while the session is device-minted; the page shows "This device is remembered until <date> - Forget".
- Studio's own PIN gate (`studio/index.html`) posts `{pin, remember}`, so it can request `gwd` itself; a `gwd` set from the approvals page works on Studio too (same origin, `Path=/`).

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

## M2 (back end)

Additive: nothing in M1 changes shape. Tiers: every route below is `ts` or `pin` except `/api/dev/info` (PIN only).

### GPU metrics (every metric point: `m`, `hello.points`, `/api/stats` fast and slow)

`fields` gains two names at the end: `[..., "tps", "gpu_util", "gpu_mem_gb"]`.

| Field | Meaning |
|-------|---------|
| `gpu_util` | float 0-100, one decimal. PDH `\GPU Engine(*)\Utilization Percentage`: instances summed per (luid, engtype), then the max over the 3D / Compute / Copy / VideoDecode sums (busiest engine on the busiest adapter) |
| `gpu_mem_gb` | GiB, two decimals. Max over adapters of PDH `\GPU Adapter Memory(*)\Dedicated Usage` |

Both are `null` off Windows, before the first two collections (rate counters need two samples), and after any error. Three errors in a row disable the
reader for the life of the process (one line on stderr). ctypes only, no subprocess; one query opened once and collected once per sampler tick (so never
while the sampler is parked); the wildcard counters are re-added every 60 s (the new pair is primed beside the old one, so there is no null gap).
Slow ring: the mean of each, nulls skipped.

### Stage-timing history

When a video job reaches `done`, `failed` or `cancelled` (including cancelled while queued) one line is appended to `<state_dir>/video/stage-history.jsonl`:

```json
{"t": 1760320400.2, "id": "5ee5ee01", "workflow": "ltx_t2v", "w": 768, "h": 512, "frames": 97, "ok": true, "total_s": 312.4, "phases": {"encode": 6.1, "load": 22.0, "stage1": 140.2}}
```

`t` = end epoch. `total_s` = end - start (end - created for a job that never started). `ok` is false for error and cancel. `phases` are seconds spent in each
`phase` value (the phase strip), measured from the moments the job's `phase` changes; the last phase runs to the end. Jobs that never report a phase
(two-process staged workflows, which have no log-parsed phases) have `phases: {}`. `w`/`h`/`frames` are `null` when the job did not carry them. The file is
capped: when it passes 600 lines it is rewritten atomically (temp + replace) to the newest 500. A failed write is logged to stderr and never touches the job.

`GET /approvals/studio/api/history?workflow=<name>&limit=<n>` (limit 1..200, default 50; out-of-range values are clamped, junk gives 50):

```json
{"v": 1, "records": [ /* newest first, optionally one workflow, failed jobs included */ ],
 "summary": {"ltx_t2v": {"n": 12, "median_total_s": 301.5, "median_phase_s": {"encode": 6.0, "stage1": 139.0}, "median_px_frames": 38076416}}}
```

`summary` uses ok records only, the newest 50 ok records per workflow, over the whole file (not cut by `limit`); with `workflow=` it holds just that workflow.
`median_px_frames` is the median of w*h*frames over those records that carry all three (0 when none do). Medians of an even count are the mean of the middle two.

### ETA from history

Public jobs (`/api/jobs`, stream `job` events and `hello.jobs`, `/api/status.active`) gain `eta_source`: `"live"` (eta_s from the progress parser, as before),
`"history"`, or `null`. `"est"` is reserved for ETAs derived from `est_minutes`; the server derives none, so the page keeps computing that itself and should
show it when `eta_source` is `null`.

While a job is `queued`, `waiting`, `starting` or `running` and has no live ETA, and its workflow has at least 2 ok history records:
`eta_s = median_total_s * clamp(job w*h*frames / median_px_frames, 0.5, 3)`, minus the seconds since `started` for a job that has started (never below 0).
If the job's size is unknown the median itself is used. Finished jobs get no history ETA. With no usable history `eta_s` is absent, exactly as before.

### GET /approvals/studio/api/dev/info (PIN only)

PIN-only through `studio.PIN_ONLY` (`^(GET|POST) /approvals/studio/api/dev(/.*)?$`) and by not being in the ts-tier route list: a `ts` session gets `401`.
Read-only.

```json
{"v": 1, "comfy": {"cmd": ["python", "main.py", "--listen", "--preview-method", "latent2rgb"], "env": {"CUDA_VISIBLE_DEVICES": "0", "HF_TOKEN": "***"}, "log_tail": ["..."]},
 "gateway": {"version": "c296814", "log_tail": null}, "governor": {"profile": "MAX", "mode": "AUTO"}, "llm": {"model": "qwen3-35b"}}
```

- `comfy.cmd` / `comfy.env`: the effective launch config the queue uses (`video.comfy_cmd`, plus the preview flag when enabled; `video.comfy_env`).
- `comfy.log_tail`: last 200 lines of `<state_dir>/video/comfy.log` (tqdm `\r` updates count as lines, ANSI colours removed), `null` if unreadable.
- `gateway.version`: first line of a `VERSION` file next to the code (`gateway/VERSION`), else `null`. `gateway.log_tail`: last 200 lines of `gateway.log` in the
  state dir or next to the code, else `null` (the gateway writes only to stderr today, so this is `null` unless its output is redirected there).
- `governor`: `profile`, `mode` from `public/status.json`; `llm.model`: `id` from governor `running.json`; `null` when missing.
- Redaction: any env key, config key or argument name matching `(?i)key|token|secret|pass|pin|auth|cookie` has its value replaced by `"***"` (`--api-key X`,
  `--api-key=X`, env `HF_TOKEN`). In every log line and value, anything matching `(?i)(bearer\s+\S+|sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{8,}|[A-Za-z0-9_-]{32,})`
  and the value of any `name=value` / `name: value` whose name matches the key pattern (query strings included) becomes `***`.

### Live latent previews (built)

Off by default. Config `video.comfy_preview: true` appends `--preview-method latent2rgb` to `comfy_cmd` (unless a `--preview-method` is already there).
ComfyUI sends previews only as binary frames on its websocket (`/ws?clientId=gw-<job id>`, the same client id the queue submits prompts with), so the gateway
runs a minimal stdlib websocket client (raw-socket handshake, frame reader, ping/pong) for the duration of each submitted graph and keeps the newest JPEG or
PNG per active job in memory (frames of ComfyUI event 1 and event 4 are both understood). `http://` ComfyUI URLs only.

- Job field `preview_t`: epoch (1 decimal) of the newest preview while the job is active, else `null`. Present on every public job; it changes at most once a second.
- `GET /approvals/studio/api/jobs/<id>/preview` (tier `ts` or `pin`): `200` with the image (`Content-Type: image/jpeg` or `image/png`), `204` with an empty body when
  there is none (unknown job, not active, feature off). The page should append `?t=<preview_t>` to defeat caching. The preview is dropped when the job ends.
