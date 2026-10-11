# Remote GUI spec: Control Centre 2 (phone-first PWA for the arc-llm-lab server)

Status: design spec and implementation plan. Written 2026-10-11 against arc-llm-lab 2.2.1 (`voice/tts_server.py` Control Centre at `/tts/stats`, `gateway/approvals.py`, `gateway/agent.py`, `gateway/outbox.py`, `governor/governor.ps1`). Nothing here is implemented yet; Sonnet lanes build from it.

Scope: one Windows 11 PC (Ryzen 7 3700X, 32 GB, Arc Pro B60 24 GB) running llama.cpp b11524 Vulkan + llama-swap (:8090), the PowerShell governor, Open WebUI 0.11.4 (:8446), the FastMCP gateway (approvals on :8093), Kokoro TTS + Whisper STT (:8092, published as `/tts`, `/stt`). The owner reaches it from a Samsung S25 Ultra over Tailscale (`https://<pc>.ts.net:8445`).

---

## 1. Principles

1. **Chat stays in Open WebUI. Everything about the machine lives in the Control Centre.** Two apps, one design language. We do not rebuild chat.
2. **Honest numbers, measured labels.** Every speed figure is live or labelled `measured`, `estimated` or `last reply`. ETAs come from the measured table in section 3.1; the UI never invents a rate.
3. **Read is free, write is a ceremony.** Reads need no session. Any change to the PC (profile, load/unload, stop-thinking, agent start/resume/cancel, approvals, link revoke) needs the PIN session cookie plus `X-Requested-With`, with a visible "unlocked until HH:MM" state. Destructive actions add press-and-hold.
4. **The model never gets a button.** Model-authored text (tool args, agent summaries, file names, outbox HTML) is rendered as text with `textContent` or served under `CSP: sandbox`. Action buttons are only created by the GUI from GUI state, never from model output. A link is only clickable if it matches the server's own outbox base.
5. **Thumb-first at 390 px.** Primary actions in the bottom 40 % of the screen; 44 px minimum targets; one-hand tab bar; sheets slide up, never modals in the top half.
6. **Degrade visibly, never silently.** Offline, stale, unauthenticated, no-PIN-set, gateway-down and model-unloaded are first-class states with their own copy and next step.
7. **Calm by default, alive when it matters.** Deep navy surfaces, one ember accent reserved for activity and attention. Motion is short (120 to 240 ms) and respects `prefers-reduced-motion`.
8. **Stdlib and static.** Served by `tts_server.py` from a small static folder; no bundler, no CDN, no external fonts. One service worker for installability and offline shell.

---

## 2. Information architecture and navigation

### 2.1 Decision: one Control Centre PWA with five tabs, alongside Open WebUI

| Concern | Lives in | Why |
|---|---|---|
| Conversation, streaming replies, tool approval cards for the current turn, `ask_user`, `/compact`, voice chat, attachments | **Open WebUI** | 0.11 already does delta streaming, tool approval cards and ask_user well. Rebuilding chat is high risk, low gain. |
| Live speed, prefill progress, stop-thinking, context ring | **Control Centre: Live** | Open WebUI shows a spinner; the owner wants to know *why* it is slow and whether to wait. |
| Long-running `agent` runs: start, watch steps, pause/resume, results and links | **Control Centre: Tasks** | A run outlives a chat turn; Open WebUI's request timeout is the wrong container for a 15-minute job. |
| Approvals (gateway writes, agent pauses) | **Control Centre: Approvals** | Out-of-band by design: the PIN must live on a page the model cannot reach. |
| Shared files / outbox | **Control Centre: Files** | Token links, expiry and revoke are server state, not chat state. |
| Profile switch, load/unload/restore, VRAM/RAM/disk/slot files, services | **Control Centre: System** | Governor and llama-swap state. |
| Notifications (chat finished/failed from Open WebUI webhooks, approval waiting, task paused/done) | **Control Centre: inbox drawer** + OS notifications | One place, one badge. |

Rejected alternatives:
- *Fold everything into Open WebUI as a Function/Pipe UI*: the approvals page must be a separate origin from anything the model can drive, and Open WebUI functions cannot host a PIN session safely.
- *Separate mini-apps per concern* (current state: `/tts/stats`, `/tts/approvals`, voice.html): three looks, three cold loads, no shared auth state. This is the thing we are replacing.

### 2.2 Navigation model

- **Bottom tab bar** (fixed, 56 px + safe-area): `Live` · `Tasks` · `Approvals` · `Files` · `System`. Badge counts on Tasks (paused runs) and Approvals (pending). Approvals badge is ember; others cobalt.
- **Status strip** (sticky under the header, 36 px, on every tab): model state dot + one line (`Generating · 41.5 tok/s` / `Reading prompt 62 %` / `Loading model, about 9 s` / `Idle, unloaded`) + lock pill (`Unlocked 11:42` or `Locked`). Tapping the strip jumps to Live; tapping the lock opens the PIN sheet.
- **Sheets** for all actions (PIN, confirm, task start, voice entry, file detail). One sheet at a time, dismiss by swipe-down or Close; never trap focus in a way that hides the status strip's `aria-live` announcements.
- **Deep links** (hash routes, PWA-safe): `#live`, `#tasks`, `#tasks/<id>`, `#approvals`, `#approvals/<id>`, `#files`, `#system`. The approvals message the model gives the user ("approve request a1b2c3 on your approvals page") links to `#approvals/a1b2c3`.
- **Open WebUI handoff**: header has a `Chat` button (opens `:8446` in the browser, or the installed Open WebUI PWA). Open WebUI's system prompt tells the model to reference `https://<pc>.ts.net:8445/tts/cc/#approvals/<id>` for approvals and `#tasks/<id>` for agent runs.

### 2.3 URL layout (served by `tts_server.py`)

```
/tts/cc/                 app shell (index.html)       static
/tts/cc/app.css          tokens + components           static
/tts/cc/app.js           router, store, polling        static
/tts/cc/live.js tasks.js approvals.js files.js system.js voice.js notify.js
/tts/cc/sw.js            service worker                static, Service-Worker-Allowed: /tts/cc/
/tts/cc/manifest.webmanifest
/tts/stats               301 -> /tts/cc/#live  (keep /tts/stats.json as is)
/tts/approvals           301 -> /tts/cc/#approvals (API routes under /tts/approvals/* unchanged)
```
Multiple static files is still "no build chain": plain ES2017, no modules bundler, loaded with `<script defer>` in order. One cache-busting query from a `BUILD` constant in `tts_server.py`.

---

## 3. Screens (390 × 844, dark shown; light mirrors)

Measured speed facts used by every ETA and label (keep in `live.js` as `MEASURED`; update when the owner re-benchmarks):

### 3.1 Measured table
| Quantity | Value | Label text |
|---|---|---|
| Decode with DFlash2 drafter | ~44 tok/s | `drafter on` |
| Decode without drafter | ~16 tok/s | `drafter off` |
| Prefill, short prompt | ~610 tok/s | ETA basis below 8K depth |
| Prefill at 32K depth | ~420 tok/s | ETA basis above 8K (linear between) |
| Slot restore (43K prompt) | 4.5 s | `restoring saved context` |
| Cold model load | 8 to 13 s | `loading model, 8 to 13 s` |
| Desktop VRAM share | 2.7 GB | shown as its own band in the VRAM bar |
| ThinkingCap xhigh | 15.9 tasks/min vs 4.1 old default | tooltip on Tasks effort selector |

### 3.2 Live (`#live`)

Purpose: answer "is it working, how fast, how long to wait, should I stop it" in one glance.

```
┌──────────────────────────────────────┐
│ Control Centre            [Chat] [🔒]│ header 56
│ ● Generating · 41.5 tok/s   Unlocked │ status strip 36
├──────────────────────────────────────┤
│ ╭──────── hero (navy gradient) ─────╮│
│ │ ● Model loaded · generating       ││
│ │ ThinkingCap-27B · 64K ctx  BALANCED│
│ │                                   ││
│ │   41.5  tok/s     ◯ 28%           ││  big number left, context ring right
│ │   drafter on · 71% accepted       ││  ring: cobalt <65, amber 65-85, red 85+
│ │   550 of 8,192 max · 13 s         ││
│ │ ▁▂▃▅▆▆▆▆▆▅  sparkline 60 s         ││
│ │                                   ││
│ │ [■ Stop thinking]  [□ Stop reply] ││  44 px, ember outline; hidden when idle
│ ╰───────────────────────────────────╯│
│ Prefill  18,450 / 43,000 · 62 %      │  only while reading prompt
│ ████████████░░░░░░  about 58 s left  │  ETA from measured table, label "estimated"
│ 17,200 cached · 25,800 to read       │
├──────────────────────────────────────┤
│ Queue                                │  from /metrics requests_deferred + /slots
│ 1 running · 2 waiting                │  rows: position n/N, source (phone/agent/
│  ▸ #1 phone chat   running 13 s      │  Claude Code), age, [Cancel] (PIN)
│  ▸ #2 agent 9f3a   waiting           │
├──────────────────────────────────────┤
│ API monitor                     [▾]  │  collapsed by default; last 20 events
│ 11:41:02 completed 1,204 tok 44.1/s │  first-token 0.9 s · prefill 610/s
│ 11:40:10 load restored 4.5 s         │
│ 11:32:55 error 500 model unreachable │
├──────────────────────────────────────┤
│ Live  Tasks  Approvals  Files  System│ tab bar
└──────────────────────────────────────┘
```

States:
- **Idle, loaded**: big number dims to `last reply 41.4`, ring shows last context, stop buttons hidden, hero dot green.
- **Reading prompt**: hero shows `Reading prompt`, prefill card visible, sparkline flat, `Stop reply` visible, `Stop thinking` hidden.
- **Thinking** (reasoning tokens flowing: detected via Open WebUI filter flag, see 6.3): `Stop thinking` primary (ember filled), `Stop reply` secondary.
- **Loading / restoring**: hero shows progress bar `Restoring saved context · 4.5 s typical` or `Loading model · 8 to 13 s`, indeterminate bar with elapsed counter; turns to determinate only when governor reports phases (6.4).
- **Unloaded**: hero `Model idle · not loaded`, VRAM free number, `[Load now]` (PIN) with sublabel `about 9 s, or 4.5 s if a saved context fits`.
- **Gateway down / llama-swap down**: hero red dot, copy `llama-swap is not answering (3 tries). The governor restarts it after 3 misses.`
- **Offline**: see 3.8.

Interactions:
- `Stop thinking` -> `POST /tts/cc/control {action:"reasoning_end"}` (PIN). Button shows a 1.5 s spinner then `Answering now`.
- `Stop reply` -> `POST /tts/cc/control {action:"cancel"}` (PIN) -> slot erase on the single slot. Press-and-hold 600 ms with a fill animation (it throws away the KV cache of the live prompt).
- Tap the ring -> small sheet with tokens used / n_ctx / what happens at 85 % (`Open WebUI will need /compact; decode slows past here`).
- Tap a queue row -> sheet with id, source, prompt tokens, `[Cancel]`. Reorder is a stretch goal (llama.cpp has no reorder API; requires a gateway-side queue; see open questions).

### 3.3 Tasks (`#tasks`, `#tasks/<id>`)

Purpose: start an `agent` run from the phone, watch it step by step, resume after approving, collect results and links.

List view:
```
│ Tasks                       [+ New] │
│ ⏸ Paused · needs approval a1b2c3    │ ember left border
│   "Build the invoice page" · 6 steps│
│   [Review approval]   [Cancel]      │
│ ▶ Running · step 4 of 20 · 01:12    │ cobalt pulse dot
│   "Rename photos by date"           │
│ ✓ Done · 2 links · 3 min ago        │
│ ✗ Failed · model unreachable        │
│ (empty) No tasks yet. Start one with │
│  + New or say "run a task" in chat.  │
```
Detail view (`#tasks/<id>`):
```
│ ← "Build the invoice page"      9f3a │
│ ▶ Running · step 4/20 · 01:12 · xhigh│
│ ── plan ──────────────────────────── │
│ 1 ✓ Read the brief                    │
│ 2 ✓ Scaffold index.html               │
│ 3 ⏸ Write C:\AI\shared\inv\index.html │  <- step rows are GUI text; args in <pre>
│     pc_Write · needs approval a1b2c3  │
│     [Approve once] [Deny]  (PIN)      │  inline approval card (same component as Approvals tab)
│ 4 · Verify by share_file              │
│ ── timeline ──────────────────────── │
│ 11:40:02 plan · 1.8 s · 2,823→410 tok │
│ 11:40:09 act pc_Read · ok · 240 ms    │
│ 11:40:21 act pc_Write · awaiting      │
│ ── result ────────────────────────── │
│ (on done) summary text (textContent)  │
│ 🔗 outbox link chip  [Open] [Copy]    │  only if URL starts with outbox base
│ VERIFIED / INFERRED badge             │
│ [Resume] [Cancel run] [Re-run]        │
```
New-task sheet: textarea (voice mic button inside, see 3.7), effort chips `low · medium · xhigh (15.9 tasks/min measured)`, max steps stepper (default 20, cap from config), `Start` (PIN). Copy under Start: `Writes inside the run pause for your approval. "Allow 15 min" never applies to runs.`

States: running / paused (approval) / step_limit (shows `Continue` instead of Resume) / done / failed (shows failure reason and `Re-run`) / cancelled. Empty state above. Loading skeletons for list and detail. If the gateway is down: banner `Tool gateway not running on the PC` and the New button disabled.

### 3.4 Approvals (`#approvals`, `#approvals/<id>`)

Purpose: decide fast and safely, with enough context to not rubber-stamp. Beats the current bare page by: intent class and colour, formatted args with path and command highlighted, source (phone chat / agent run / Claude Code instance), age and expiry countdown, press-and-hold for destructive, deny-first ordering, batch view.

```
│ Approvals (2)             Unlocked 11:42 │
│ ╭─ DESTRUCTIVE ────────────── 14:32 left╮│ red tag
│ │ pc_PowerShell                         ││
│ │ from agent 9f3a · step 3              ││
│ │ why: delete-intent command            ││
│ │ ┌ args ──────────────────────────────┐││
│ │ │ command: Remove-Item C:\AI\shared\ │││  monospace, wraps, path tokens tinted
│ │ │          old\*.bak                 │││
│ │ └────────────────────────────────────┘││
│ │ [Deny]      [Hold to approve once ▸]  ││ hold 800 ms, fill animation, haptic
│ ╰───────────────────────────────────────╯│
│ ╭─ WRITE ─────────────────────── 9:10 left╮
│ │ pc_Write  from phone chat               │
│ │ path: C:\AI\shared\inv\index.html       │
│ │ 4.2 KB · [Preview text ▾]               │ preview = first 2 KB as text
│ │ [Deny] [Allow 15 min] [Approve once]    │ Allow 15 min hidden for agent-origin
│ ╰─────────────────────────────────────────╯
│ History (today)                     [▾]  │ last 20 decisions from audit.jsonl
│ 11:12 approved pc_Write …/notes.md      │
│ 10:58 denied pc_PowerShell Stop-Process │
```
States: locked (PIN sheet inline, with `No PIN set on this PC: run set-approval-pin.ps1` if 403), empty (`Nothing waiting. The model will tell you when it needs a yes.`), gateway down (502 banner), lockout (429: countdown), expired-while-viewing (card greys out with `Expired, the model will ask again`).

Interactions: Approve once / Allow 15 min / Deny -> existing `POST /approvals/<id>/<action>`. After a decision the card collapses with a 240 ms slide; a toast `Approved. The model will repeat the call.` Agent-origin cards also offer `Approve and resume` which chains `/approvals/<id>/approve` then `/approvals/agent/<run>/resume`.

### 3.5 Files (`#files`)

Purpose: everything the model shared, plus what the owner shared back.

```
│ Files                         [Share ▴] │  Share = upload from phone to C:\AI\inbox (PIN)
│ ╭ invoice-site/  (website, 14 files)   ╮│
│ │ 1.2 MB · from agent 9f3a · 23 h left  ││
│ │ [Open] [Copy link] [Revoke]           ││
│ ╰───────────────────────────────────────╯│
│ ╭ report.pdf  2.1 MB · 6 h ago · 18 h   ╮│
│ │ [Open] [Copy link] [Revoke]           ││
│ ╰───────────────────────────────────────╯│
│ Expired (3)                        [▾]  │
│ (empty) Nothing shared yet. Ask the     │
│ model to share_file a path, or tap Share│
```
Open loads the token URL in a new tab (CSP sandbox origin). Copy link uses `navigator.clipboard` with a fallback sheet showing the URL. Revoke (PIN) removes the token now. Upload (PIN, stretch): `POST /tts/cc/inbox` multipart, 50 MB cap, lands in a configured inbox root the model can read.

### 3.6 System (`#system`)

Purpose: the health view and the big levers.

```
│ System                                  │
│ Profile                      active MAX │
│ [AUTO] [MAX] [BALANCED] [LEAN]          │ existing segmented control, PIN
│ Governor wants MAX · loaded as BALANCED │ shows desired vs loaded
│ Next reload fits 65,536 ctx             │ expected_ctx from status.json
├─────────────────────────────────────────┤
│ Model                                   │
│ ● ThinkingCap-27B · loaded 42 min       │
│ [Unload now] [Reload (restore)] (PIN)   │ unload = hold; reload shows ETA
│ Saved contexts: 2 files · 3.1 GB        │ from slots dir listing
│  qwen3.8-27b.bin 43,120 tok · 1 h ago   │
│  [Delete] per file (hold, PIN)          │
├─────────────────────────────────────────┤
│ VRAM 24 GB                              │
│ ███████████████████▒▒▒░░  21.4 used     │ bands: model 16.1 · KV 2.6 · desktop 2.7 · free 2.4
│ ■ model ■ KV cache ■ desktop ■ free     │ pre-load itemisation when unloaded:
│ RAM 32 GB  ████████░░ 19.8 used · 12.2 free  "weights 16.1 + KV 2.6 + compute 0.8 + drafter 0.9 = 20.4"
│ Disk C: 931 GB  ██████░░ 612 free       │
│ CPU 23 % · others 4 % · power PERFORMANCE│
├─────────────────────────────────────────┤
│ Services                                │
│ ● llama-swap :8090  ● llama-server :10001│
│ ● governor 12 s ago ● gateway :8093      │
│ ● Open WebUI :8446  ● TTS/STT :8092/:8091│
│ ● Tailscale backend                      │
│ each: green/amber/red + last seen; tap → │
│ sheet with last 20 governor log lines    │
├─────────────────────────────────────────┤
│ Advanced                           [▾]  │
│ Flags editor (stretch, see 10)           │
│ Kill switch: [Create KILL file] (hold)   │
│ About: build, llama.cpp b11524, uptime   │
```
States: governor status older than 30 s -> amber `governor stale`; swap-down -> red with watchdog note; VRAM free < 1.15 GiB -> ember `low`; slot files none -> `No saved context. The next load is a cold load.`

### 3.7 Voice entry (sheet, from Tasks new-task and from the header mic)

```
│ ╭────────────── Talk ──────────────╮ │
│ │     ◉  (120 px mic, ember ring)   │ │ hold to talk, release to send to /stt
│ │  "Rename the photos in Downloads  │ │ transcript appears as text, editable
│ │   by date and share a zip"        │ │
│ │  [Use as task] [Send to chat]     │ │ Send to chat = copy + open Open WebUI
│ │  [Read back ▸] (Kokoro, /tts)     │ │
│ ╰───────────────────────────────────╯ │
```
Uses `MediaRecorder` as `voice.html` does today; posts to `/tts/v1/audio/transcriptions`. No model call happens from this sheet; it only produces text the owner then submits. Error states: mic permission denied (copy with how to re-enable in Samsung Internet/Chrome), STT 502, recording over 60 s cut with a toast.

### 3.8 Offline and error states (global)

- **Offline shell**: service worker serves the app from cache. Status strip turns grey `Offline · last data 11:38`. Every number stays visible with a diagonal stale hatch on cards and `aria-label="stale"`. All write buttons disabled with reason. Retry with backoff 1 s to 15 s (existing logic). A `Retry now` button in the strip.
- **Tailscale down vs PC down**: if `fetch` fails in under 100 ms it is likely the tailnet (phone side): copy `Check Tailscale on the phone`. If it times out: `PC not answering over Tailscale`.
- **401 on a write**: PIN sheet opens with the pending action named (`Unlock to switch to MAX`), replays the action on success.
- **429**: countdown, PIN field disabled.
- **502 gateway**: banner on Tasks/Approvals/Files only; Live and System still work.
- **Empty states**: every list has one, with the one next action.
- **Error toast**: bottom, above tab bar, 4 s, dismissible, `role=status`.

---

## 4. Design tokens

Build on the tokens already in `STATS_PAGE`; keep names, add the missing ones. Light and dark, `prefers-color-scheme` plus a manual override stored in `localStorage` (`cc.theme`).

```css
:root{
  /* surfaces */
  --bg:#eef2fb; --card:#ffffff; --card-2:#f5f7fd; --line:#d5ddef; --track:#e1e7f5; --seg:#e6ebf7;
  /* ink */
  --ink:#0d1a36; --mute:#4f5e7c; --faint:#8a97b5;
  /* brand */
  --cobalt:#2850d8; --cobalt-ink:#1d3cae; --on-cobalt:#fff;
  --ember:#e0611f; --ember-ink:#b3400a; --on-ember:#1b0c02;
  /* semantic */
  --ok:#14804a; --warn:#b7791f; --bad:#b42318; --info:#2850d8;
  /* hero */
  --hero-a:#10214a; --hero-b:#193a8f; --hero-ink:#f2f5ff; --hero-mute:#b4c2e6; --hero-track:rgba(255,255,255,.16); --hero-ember:#ff8a4c;
  /* ring thresholds */
  --ring-ok:var(--cobalt); --ring-warn:#f0a030; --ring-bad:#ff6b5e;
  --shadow:0 1px 2px rgba(13,26,54,.06),0 6px 20px rgba(13,26,54,.06);
  /* radius */
  --r-s:10px; --r-m:16px; --r-l:20px; --r-pill:22px;
  /* spacing (4-pt) */
  --s-1:4px; --s-2:8px; --s-3:12px; --s-4:16px; --s-5:20px; --s-6:24px; --s-8:32px;
  /* type */
  --f-ui:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  --f-mono:ui-monospace,"Cascadia Mono","Roboto Mono",Menlo,monospace;
  --t-hero:4.4rem; --t-h1:1.25rem; --t-h2:1.05rem; --t-val:1.7rem; --t-body:1rem; --t-small:.86rem; --t-micro:.76rem;
  /* motion */
  --m-fast:120ms; --m-base:180ms; --m-slow:240ms; --ease:cubic-bezier(.2,.7,.2,1);
  /* layout */
  --tabbar:56px; --strip:36px; --touch:44px;
}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){ /* same as current dark block, plus: */
  --card-2:#0e1730; --faint:#6c7a9c; --warn:#f0a030; --ring-warn:#f0a030; --ring-bad:#ff7b6e; }}
:root[data-theme=dark]{ /* identical dark block */ }
```

Type scale: hero number 4.4 rem (3.8 rem under 370 px), tabular numerals everywhere a number can change (`.num`). Line height 1.4 body, 1.1 values. Weight: 700 titles and values, 600 labels, 400 body. No font smaller than 12.2 px (`--t-micro`).

Motion: value changes crossfade 120 ms; cards enter with 8 px rise + fade 180 ms; sheets 240 ms rise with the ease above; the generating dot pulses 1.2 s; hold-to-confirm fills linearly over 600 to 800 ms. Under `prefers-reduced-motion` all durations become 0 and the pulse becomes a static ring.

Density: 16 px gutters, 12 px gaps between cards, 14 px card padding. Content max-width 960 px; two-column at 760 px and up (hero spans rows, as now).

---

## 5. Components

All components are plain DOM built in JS with `textContent`; no `innerHTML` with dynamic data. Each has a documented set of states.

| Component | Used on | Notes |
|---|---|---|
| `AppShell` | all | header, status strip, tab bar, sheet host, toast host |
| `StatusStrip` | all | state dot, one-line summary, lock pill; `role=status aria-live=polite` |
| `TabBar` | all | 5 tabs, badges, `aria-current` |
| `HeroCard` | Live | big number, context ring, sparkline, action row |
| `ContextRing` | Live, Live sheet | SVG ring, 3 thresholds (65/85), `role=progressbar` |
| `Sparkline` | Live | reuse current SVG code |
| `ProgressBar` | Live prefill, model load | determinate / indeterminate, ETA slot |
| `StatTile` | Live, System | label, value, unit, note, warn state |
| `SegmentedControl` | System profile | reuse, add `disabled` reason |
| `ActionButton` | everywhere | variants primary (cobalt), accent (ember), ghost, danger; sizes 44/52; loading state |
| `HoldButton` | approvals destructive, unload, cancel, kill | 600 to 800 ms fill, cancel on pointer leave, haptic via `navigator.vibrate(10)` if present |
| `ApprovalCard` | Approvals, Tasks detail | intent tag, origin, why, args `<pre>`, expiry, action row |
| `ArgsView` | ApprovalCard | pretty-prints JSON args; highlights `path`, `command`, `url` keys; 2 KB fold |
| `TaskRow` / `TaskDetail` | Tasks | status glyph, plan list, timeline, result block |
| `StepRow` | TaskDetail | glyph (done / running / paused / todo), tool, duration |
| `LinkChip` | Tasks result, Files | only renders as `<a>` when href starts with the server's outbox base; otherwise plain text |
| `FileRow` | Files | name, kind, size, origin, TTL countdown, actions |
| `ServiceRow` | System | dot, name, port, last seen |
| `StackedBar` | System VRAM/RAM/disk | segments with legend; the desktop's 2.7 GB is always its own band |
| `Sheet` | all actions | focus trap, swipe-down, `inert` on the page behind |
| `PinSheet` | on 401 | numeric PIN, shows what will happen after unlock, replays the action |
| `Toast` | all | 4 s, stack of 2, `role=status` |
| `Banner` | gateway down, stale, offline | top of content, non-blocking |
| `EmptyState` | all lists | icon, one sentence, one action |
| `Skeleton` | all lists | 3 rows, shimmer disabled under reduced motion |
| `MicButton` | Voice sheet, task textarea | hold-to-talk, level ring |

---

## 6. Backend API

All endpoints are reached as `https://<pc>.ts.net:8445/tts/...` via `tailscale serve` to `127.0.0.1:8092` (`tts_server.py`). `tts_server.py` proxies `/approvals*` and `/outbox*` to `approvals.py` (:8093) as today. New write endpoints live in `approvals.py` (it owns the PIN session) and are proxied; `tts_server.py` only ever gains read endpoints or static files, plus one write proxy (`/cc/control`) that forwards the cookie and header exactly like `_approvals()`.

Auth legend: **none** = read, tailnet only; **session** = `gwa` cookie valid + `X-Requested-With: approvals` (403 without header, 401 without session); **hold** = session plus a UI hold (server does not know, but these are also rate-limited to 1 per 5 s).

### 6.1 Existing (unchanged)
| Method | Path | Auth | Source |
|---|---|---|---|
| GET | `/tts/stats.json` | none | `live_stats()`: governor `status.json`, `/slots`, `/metrics` |
| GET | `/tts/approvals/pending.json` | session | `approvals._pending` |
| POST | `/tts/approvals/login` `{pin}` | header only | PBKDF2 check, sets cookie |
| POST | `/tts/approvals/<id>/approve\|allow\|deny` | session | `_pending` |
| POST | `/tts/approvals/mode` `{mode}` | session | writes `mode.txt` |
| GET | `/tts/outbox/<token>/<path>` | none (token) | outbox dir, `CSP: sandbox` |
| POST | `/tts/v1/audio/transcriptions` | none | whisper.cpp |
| POST | `/tts/v1/audio/speech` | none | Kokoro |

### 6.2 New: reads (in `tts_server.py`)
| Method | Path | Auth | Payload / source |
|---|---|---|---|
| GET | `/tts/cc/` and static files | none | files under `voice/cc/`, allowlisted names only, `Cache-Control: max-age=0, must-revalidate`, `ETag` |
| GET | `/tts/cc/snapshot.json` | none | one aggregated poll: `{t, gov, slot, metrics, swap:{running:[{model,state}]}, props:{n_ctx, model_path, build}, sys:{ram, disk, cpu, vram_bands}, phase, thinking, events:[last 20], build}`. `swap` from llama-swap `/running` (key from `api-key.txt`, read server-side), `props` from `/props` (cached 60 s), `sys` from governor `status.json` plus `shutil.disk_usage`, `phase` and `thinking` from 6.4 and 6.3. Served with `ETag`; client sends `If-None-Match` and gets 304 when nothing changed, which is most idle polls. |
| GET | `/tts/cc/events.json?since=<t>` | none | ring buffer (in memory, 200 entries) of monitor events built from deltas in `/metrics` and swap state transitions: `completed`, `error`, `load`, `restore`, `unload`, `deferred`. Each: `{t, kind, tok, tps, ttft_ms, prefill_tps, note}`. |
| GET | `/tts/cc/slots.json` | none | listing of the governor slots dir (`profiles.json` -> `slots.dir`): `[{name, tokens (from sidecar), size, mtime, model}]`. Read-only; never returns the file contents. |
| GET | `/tts/cc/services.json` | none | `{llama_swap, llama_server, governor_age_s, gateway, openwebui, tts, stt, tailscale}` each `{up, detail, checked}`; TCP connect with 1 s timeout to the loopback ports; governor age from `status.json` mtime; Tailscale from `tailscale status --json` cached 30 s (subprocess, read-only). |
| GET | `/tts/cc/manifest.webmanifest`, `/tts/cc/sw.js` | none | static |

### 6.3 New: control (write proxy in `tts_server.py`, enforcement in `approvals.py`)
| Method | Path | Auth | Behaviour |
|---|---|---|---|
| POST | `/tts/cc/control` `{action:"reasoning_end"\|"cancel"}` | session | `tts_server.py` forwards to `approvals.py` `POST /approvals/control` with cookie and header. `approvals.py` validates the session, then: `reasoning_end` -> `POST http://127.0.0.1:<port>/v1/chat/completions/control {id, action:"reasoning_end"}` where `id` is the current completion id recorded by the Open WebUI filter (`openwebui/live_stats_filter.py` writes `C:\AI\governor\public\current.json {id, started, thinking:true|false}` on stream start and clears it on end). `cancel` -> `POST /slots/0?action=erase` after confirming `is_processing`. Rate limit 1 per 2 s. Audit line in `audit.jsonl` with `tool="cc.control"`. [CONFIRM: the control endpoint accepts the `chatcmpl-` id from the stream; if it needs the internal task id, fall back to `/slots` `id_task`.] |

### 6.4 New: model and governor levers (in `approvals.py`, proxied by the existing `/approvals*` route)
| Method | Path | Auth | Behaviour |
|---|---|---|---|
| POST | `/approvals/model` `{action:"load"\|"unload"\|"reload"}` | session (unload: hold) | writes `C:\AI\governor\request.json {action, t, by:"cc"}`. The governor picks it up on its next sample (`sample_sec`), honours its own "never while busy" rule, and writes `phase` into `status.json`: `loading`, `restoring`, `warming`, `ready`, `unloading`, `postponed-busy`. The GUI shows the ETA from the measured table until phase is `ready`. The governor never acts on a request older than 60 s. |
| POST | `/approvals/slots/<name>/delete` | session + hold | deletes one `*.bin` + `*.json` pair inside the slots dir only (`SlotSafePath` logic duplicated in Python: leaf name, allowlisted extension). |
| POST | `/approvals/kill` `{on:true\|false}` | session + hold | creates or removes `C:\AI\gateway\KILL`. |

### 6.5 New: agent runs (in `approvals.py`; it runs inside the gateway process, so it has `agent.py` and the state dir)
| Method | Path | Auth | Behaviour |
|---|---|---|---|
| GET | `/approvals/agent/runs.json` | session | list of `agent-*.json` in the state dir, newest first, 50 max: `{id, task, status, steps, created, updated, approvals, links, summary}`; never the `messages` array. |
| GET | `/approvals/agent/<id>.json` | session | one run: plan (parsed from the first assistant message's numbered list), `timeline` (from audit lines with that `id`: step, kind, call, verdict, ms, tok), `pending` approval id, `links`, `summary`, `status`. Model text is returned raw; the client renders as text. |
| POST | `/approvals/agent/start` `{task, effort?, max_steps?}` | session | spawns `Agent.run` in a background thread with its own event loop; returns `{id}` immediately. Rate limit: one new run per 10 s, 3 concurrent max. Task text capped at 4,000 chars. |
| POST | `/approvals/agent/<id>/resume` `{note?}` | session | `Agent.run(task=note, resume=id)` in background. |
| POST | `/approvals/agent/<id>/cancel` | session + hold | writes `agent-<id>.cancel`; `run_loop` checks it per step (small change in `agent.py`: treat like the kill file but per run) and finishes with `status:"cancelled"`. |

Runs started from Open WebUI's `agent` tool appear in the same list because they share the state dir.

### 6.6 New: files (in `approvals.py`)
| Method | Path | Auth | Behaviour |
|---|---|---|---|
| GET | `/approvals/outbox.json` | session | from `outbox/index.json`: `[{token, name, kind:file\|site\|zip, size, created, expires, origin?}]`. |
| POST | `/approvals/outbox/<token>/revoke` | session | removes the token dir and index entry (`outbox` gets a `revoke(d, token)` helper). |
| POST | `/approvals/inbox` multipart | session | stretch: saves to `cfg.inbox_dir`, 50 MB cap, filename sanitised, returns path. |

### 6.7 New: notifications
| Method | Path | Auth | Behaviour |
|---|---|---|---|
| POST | `/tts/cc/hook` | shared secret header `X-Hook-Token` (from `gateway.json`), loopback or tailnet | Open WebUI webhook target for chat finished / failed. Appends to the notifications ring buffer. |
| GET | `/tts/cc/notifications.json?since=<t>` | none | ring buffer: `{t, kind: chat_done\|chat_failed\|approval\|task_paused\|task_done\|task_failed\|model_loaded\|low_vram, title, body, href}`. Approval and task items are synthesised server-side from `_pending` and run state changes. Items carry no model text beyond a 120-char title that is rendered as text. |
| POST | `/approvals/push/subscribe` | session | stretch (team vote, section 10): stores a Web Push subscription. Needs a VAPID library (`pywebpush` or `cryptography`), which breaks the stdlib rule, so it is not in phase 1. |

Phase 1 notifications: the service worker polls `notifications.json` while the app is open or recently backgrounded (`periodicSync` where available, else on `visibilitychange`), and shows an OS notification via `registration.showNotification` for new items. The app badge uses `navigator.setAppBadge` with the pending approvals count.

---

## 7. Security model

1. **Trust boundaries.** Tailnet = authenticated network, not authenticated user. Anyone on the tailnet can read status, queue, services, slot file names and notifications titles. Anything that changes state needs the PIN session. Model-authored content is untrusted everywhere.
2. **Session.** Unchanged: PBKDF2 PIN, `gwa` cookie `HttpOnly; Secure; SameSite=Strict; Path=/`, 12 h, 5 fails -> 15 min lockout. The GUI shows the session expiry (server adds `expires` to the login response and to `pending.json` headers as `X-Session-Expires`).
3. **CSRF.** Every POST needs `X-Requested-With: approvals` (preflight-free custom header, so a cross-site form cannot send it) and the SameSite=Strict cookie. No CORS headers anywhere. The outbox origin is sandboxed (`CSP: sandbox`), so model HTML cannot carry the cookie or call these endpoints.
4. **CSP for the app.** `default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; manifest-src 'self'; worker-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`. Moving CSS and JS out of inline is what makes `'self'` possible; no `unsafe-inline` anywhere.
5. **Prompt injection.** The model can at most produce text that lands in: approval args, agent summaries and step text, outbox file names, notification titles. All are set with `textContent`. `LinkChip` only produces an anchor when the URL starts with the server's own outbox base and the token matches `TOKEN_RE`; everything else is plain text. No `javascript:`/`data:` navigation is ever constructed from data. Hash routes are validated against `^#(live|tasks|approvals|files|system)(/[0-9a-f]{4,12})?$`.
6. **Writes are explicit.** No write fires on load, on route change or on a timer. Every write is a tap (or hold) on a GUI-created button, followed by a request that the server authorises independently. The GUI's "approve and resume" is two server calls, each checked.
7. **Agent containment.** Runs started from the GUI go through the same `Agent` class, the same Guard, `once_only` (no 15-minute windows), the kill switch and the audit log. Cancel is a per-run file the loop checks; the kill file still stops everything.
8. **Governor levers.** The GUI never talks to llama-swap or llama-server directly for writes. `approvals.py` writes a request file; the governor decides, respecting busy state. `cc/control` is the one exception (talking to llama-server's control and slot-erase endpoints) because it must act within a second; it is session-gated, rate-limited and audited.
9. **Secrets.** `api-key.txt`, `approval-pin.json`, `gateway.json` are read server-side only and never serialised. `snapshot.json` strips any `Authorization` material and the model path to its basename.
10. **Rate limits.** Login 5/15 min; control 1 per 2 s; model levers 1 per 5 s; agent start 1 per 10 s; all others 10 per s per client IP.
11. **Audit.** Every write from the GUI appends to the same hash-chained `audit.jsonl` with `tool="cc.<action>"` and `by="phone"`. The History section on Approvals reads it back.

---

## 8. Implementation plan: four lanes, exclusive files

Branch: `feature/control-centre-2`. Each lane owns its files; cross-lane needs go through the JSON contracts in section 6 (frozen by this spec). Lane A publishes `app.css` and the component DOM conventions first (day 1, half a day), then the others build on it. Phase 1 is everything not marked stretch.

### Lane A: shell, Live, tokens, PWA (owner of the look)
Files: `voice/cc/index.html`, `voice/cc/app.css`, `voice/cc/app.js` (router, store, polling with ETag and backoff, sheet/toast/pin plumbing, status strip, tab bar), `voice/cc/live.js`, `voice/cc/sw.js`, `voice/cc/manifest.webmanifest`, and the static-serving and `snapshot.json`/`events.json` routes in `voice/tts_server.py` (Lane A is the only lane that edits `tts_server.py`).
Acceptance tests:
- `python -m unittest voice/tests/test_cc_server.py`: static allowlist (a path traversal returns 404), `snapshot.json` shape with llama-server down (every section present with `error` keys, HTTP 200), ETag 304 round-trip, CSP header present on `/cc/`, `/tts/stats` redirects.
- Lighthouse PWA installable on Android Chrome (manifest + SW + offline shell). Offline: airplane mode shows the stale state within 6 s and recovers within 15 s of reconnecting.
- Live: with a 43K prompt in flight the prefill bar shows a percentage and an ETA within 20 % of actual; the big number tracks within 1 tok/s of llama.cpp's own report; `Stop thinking` disappears when `thinking` is false.
- Accessibility: axe-core 0 serious issues; all values have labels; tab order follows the visual order; 200 % font scaling does not clip the hero.
Screenshots required (390 × 844 light and dark, plus 1280 × 800 dark): generating-thinking, reading-prompt, idle-loaded, unloaded, loading-with-eta, offline-stale, locked-401, pin-sheet.

### Lane B: Tasks and Approvals (owner of the write path)
Files: `voice/cc/tasks.js`, `voice/cc/approvals.js`, `voice/cc/components-approval.js` (ApprovalCard, ArgsView, HoldButton, LinkChip), `gateway/approvals.py` (new routes in 6.3 to 6.5 and the `/approvals/control` handler), `gateway/agent.py` (per-run cancel file, `status:"cancelled"`, `effort` override on start), `gateway/tests/test_approvals_cc.py`.
Acceptance tests:
- Unit: every new POST returns 403 without the header, 401 without the session, 200 with both; `agent/runs.json` never includes `messages`; cancel file ends a run with `cancelled` within one step; `once_only` still applies to GUI-started runs (a tool with a live 15-minute allow still pauses).
- Integration (against a fake OpenAI endpoint in tests): start -> paused on a write -> approve on the page -> resume -> done with a link; the GUI timeline shows all four states without a reload.
- Security: an approval whose args contain `<img onerror>` and a `javascript:` URL renders as text; a result link outside the outbox base renders as text.
- Hold-to-approve cannot be triggered by a tap under 600 ms; keyboard users get a two-step confirm instead of a hold.
Screenshots: approvals-destructive-hold-midway, approvals-write-with-preview, approvals-empty, approvals-locked-no-pin, tasks-list-mixed, task-detail-paused-with-inline-approval, task-detail-done-with-links, new-task-sheet.

### Lane C: Files, Voice, Notifications (owner of the edges)
Files: `voice/cc/files.js`, `voice/cc/voice.js`, `voice/cc/notify.js`, `gateway/outbox.py` (`list(d)` and `revoke(d, token)` helpers; routes are registered by Lane B through a tiny hook `approvals.register_extra(route_table)` that Lane B adds on day 1 so Lane C never edits `approvals.py`), the `/tts/cc/hook` and `notifications.json` handlers in a new `voice/cc_notify.py` module that `tts_server.py` imports (Lane A adds the one import line), `gateway/tests/test_outbox_list.py`, `openwebui/webhook-setup.md`.
Acceptance tests:
- Outbox list matches `index.json` after share and after expiry purge; revoke removes files and the entry; a revoked token 404s within 1 s.
- Voice: hold-to-talk records, releases, transcribes via `/tts/v1/audio/transcriptions`, fills the task textarea; mic-denied and STT-down states render.
- Notifications: a posted webhook with the right token appears in `notifications.json` and as an OS notification while the app is backgrounded; a wrong token is 403 and not stored; pending approvals set the app badge count.
Screenshots: files-list, files-empty, files-expired-folded, voice-sheet-recording, voice-sheet-transcript, notification-drawer, android-os-notification.

### Lane D: System, governor phases, slots, screenshot harness
Files: `voice/cc/system.js`, `voice/cc/components-bars.js` (StackedBar, ServiceRow, SegmentedControl move), `governor/governor.ps1` (read `request.json`, write `phase`, extend `status.json` with `ram_total_gb`, `disk_free_gb`, `disk_total_gb`, `vram_bands`), `governor/slotlib.ps1` (phase hooks in `SlotWarmFlow`), `openwebui/live_stats_filter.py` (write `current.json` with completion id and thinking flag), `governor/test_slotpolicy.py` additions, `voice/tests/shoot.py` (Playwright screenshot harness used by all lanes, with a fake `snapshot.json` fixture set under `voice/tests/fixtures/`).
Acceptance tests:
- Governor: a `request.json {action:"unload"}` while a request is running yields `phase:"postponed-busy"` and no unload; while idle, unload within one sample and `phase` walks `unloading -> stopped`; a `load` walks `loading|restoring -> warming -> ready`; a request older than 60 s is ignored and logged.
- `current.json` is written within 300 ms of stream start and removed on completion or error; `thinking` flips to false when the first non-reasoning delta arrives.
- System screen: VRAM bands sum to the heap total within 0.1 GiB; the desktop band is present and labelled even when the model is unloaded; services reflect a stopped llama-swap within 5 s.
- Harness: `python voice/tests/shoot.py --all` produces every screenshot listed in the four lanes under `scratchpad/ui/cc/` from fixtures, deterministic file names, both colour schemes.
Screenshots: system-healthy, system-unloaded-preload-itemisation, system-low-vram, system-governor-stale, system-services-one-down, system-slot-files, slot-delete-hold.

### Sequencing and merge
Day 1: Lane A publishes tokens and shell; Lane B adds `register_extra` and the route stubs returning fixtures; Lane D publishes the `snapshot.json` fixture set. Days 2 to 4: parallel build. Day 5: integration on the PC (owner runs `governor/doctor.ps1` plus the new tests), screenshot pass, 10-case phone walkthrough (install, each tab, one approval, one task, offline, PIN expiry). Release as 2.3.0 in one batch; `/tts/stats` and `/tts/approvals` keep working as redirects, so rollback is removing the redirects.

Status reporting per lane: local / committed / pushed / CI / merged / deployed / live, each labelled VERIFIED or INFERRED.

---

## 9. Scorecard: how each dimension reaches 9/10

| Dimension | What earns the score | Evidence required |
|---|---|---|
| **Usability** | One app, five tabs, bottom bar, every action within thumb reach; each write names its consequence in one line; deep links from the model's own messages land on the right card; PIN sheet replays the action you wanted. | 10-case phone walkthrough with no dead ends; every list has an empty state and one next action. |
| **Clarity** | Measured labels (`drafter on`, `estimated`, `last reply`), desired vs loaded profile, VRAM bands with the desktop's share, intent tags on approvals, VERIFIED/INFERRED on results. | Copy review against section 3; no number without a unit and a source. |
| **Speed perception** | 1 s polling while active with ETag 304s when idle; first paint from SW cache under 300 ms on repeat visits; prefill ETA and model-load ETA so waits are bounded; stop-thinking within 2 s; skeletons instead of blank cards. | Measured on the S25 over Tailscale: repeat-load first paint under 400 ms, action round trip under 700 ms median. |
| **Accessibility** | 44 px targets, 4.5:1 contrast on all text in both themes, `aria-live` strip, progressbars with values, hold buttons with a keyboard alternative, reduced motion honoured, 200 % text without clipping, light theme included. | axe-core clean; manual TalkBack pass on Live and Approvals. |
| **Safety** | Reads free, writes session-gated with CSRF header and SameSite cookie; CSP `'self'` with no inline; model text rendered as text only; links allowlisted to the outbox base; destructive actions hold-to-confirm; agent runs keep `once_only`; everything audited; governor keeps the busy rule. | Section 8 security tests pass; a review lane greps for `innerHTML` and finds none with dynamic data. |

Known gaps that keep this at 9 rather than 10: no Web Push without a crypto library (section 10), no queue reorder (llama.cpp has no API for it), load progress is time-based rather than byte-based.

---

## 10. Open questions for a team vote

1. **Web Push**: allow `cryptography` (or `pywebpush`) in the TTS venv so the phone gets notifications with the app closed, or stay stdlib and accept notifications only while the PWA is open or recently backgrounded? Recommendation: ship phase 1 stdlib, add Web Push in 2.3.1 behind a config flag.
2. **Stop-thinking id source**: confirm on the PC whether `/v1/chat/completions/control` accepts the streamed `chatcmpl-` id. If not, the fallback is `/slots` `id_task`; if neither works for requests that did not come from Open WebUI (Claude Code, agent runs), show `Stop reply` only for those.
3. **Prompt queue reorder and cancel**: llama.cpp defers requests but cannot reorder them. Do we add a tiny gateway-side queue in front of llama-swap for agent runs (gives n/N, reorder, cancel) or show position only? Recommendation: position only in phase 1.
4. **Phone-to-PC upload (inbox)**: in scope for 2.3.0 or later? It is the only endpoint that accepts arbitrary bytes from the phone.
5. **Flag editor** (validated against `llama-server --help` with a denylist): ship as read-only "effective flags" view in System first, editor later via `profiles.json` edits that the governor applies on the next reload?
6. **Approvals history source**: read `audit.jsonl` directly (fast, already there) or keep a separate decisions log so the history does not expose tool arguments to any tailnet reader? Recommendation: the history endpoint is session-gated either way; read the audit log.
7. **Theme override**: ship the manual light/dark toggle, or system-only? (Cost is small; the owner's screenshots show both themes already in use.)
8. **Open WebUI deep-link format**: update `prompts/phone-system.md` so the model says "approve request a1b2c3 (Approvals tab)" and the webhook payload carries the chat id for the notification `href`. Needs the owner to confirm the Open WebUI webhook setting is enabled on :8446.
9. **Static files vs single file**: this spec moves to a small `voice/cc/` folder for a strict CSP. If the team prefers the current single-file approach, CSP needs a per-build script hash; the lanes stay the same.
10. **Attribution**: if any llama.cpp WebUI code is reused (the context ring and API monitor are the candidates), the MIT notice goes in `voice/cc/THIRD-PARTY.md`. Unsloth Studio ideas only, no code.
