# claude-defaults/tools

Account-wide helper tools distributed by `bootstrap.sh` into `~/.claude/tools/`.

## `ollama_route.py` — the Ollama bridge (tier 0/1)
Lets a Claude Code session or subagent offload **heavy, non-stakes** work to a
local or **Ollama Cloud Pro** model, so the big cheap open models carry the
mid-tier grunt work instead of spending Claude quota. This is the arm the router
uses to reach the Ollama Cloud tier the policy reserves.

```bash
python ~/.claude/tools/ollama_route.py --model gpt-oss:120b-cloud "Summarise ..."
echo "refactor this module ..." | python ~/.claude/tools/ollama_route.py --route heavy-code
python ~/.claude/tools/ollama_route.py --list          # models the server can see
```

Routes: `heavy-code` → `kimi-k2.7-code:cloud`, `heavy-reason` → `gpt-oss:120b-cloud`,
`trivial` → `llama3.2:3b`, `classify` → `llama3.2:3b`. Stdlib only, no deps.
The heavy/mid routes are `:cloud` tags — they bill the flat-rate Ollama plan and
never load onto a local GPU; the trivial/classify floor is the ONE model a
workstation hosts locally (see "Workstation hosting" below).

**NUMBERS RULE:** never send customer-facing price/quote/invoice/legal here — those
stay on Claude (Sonnet/Opus). This tool is for heavy NON-stakes work only.

## `claude_status_line.py` — live tier + offline/cloud badge

A cross-platform (Windows/Mac/Linux, plain `python3`, no deps) Claude Code
`statusLine` command. Shows the active Claude tier every render, plus a live
badge whenever a **local ("offline")** or **Ollama Cloud** model was used in
the last 10 minutes — by the classifier hook (`claude-routing-classifier.ps1`)
or the bridge (`ollama_route.py`), both of which now write a small state file
(`~/.claude/.routing-status.json`) on every successful Ollama call.

```
🤖 Sonnet 5
🤖 Opus 4.8  ·  🖥️ offline (llama3.2:3b, 8s ago)
🤖 Sonnet 5  ·  ☁️ cloud (gpt-oss:120b-cloud, 2m ago)
```

Wire it once — this repo already carries it fanned out via the sync-defaults
mechanism (see `settings.json` in this directory's parent), so most child
repos get it automatically. To wire it manually (e.g. a `~/.claude/settings.json`
user-level install), add:

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/tools/claude_status_line.py",
    "refreshInterval": 10
  }
}
```

For a repo-local install (tools land at `<repo>/.claude/tools/`), use the
relative path instead: `.claude/tools/claude_status_line.py`.

On Windows without Git Bash (shebang execution won't resolve), override the
command to `python ~/.claude/tools/claude_status_line.py`.

Fails open like everything else in this kit: any error, missing state file,
or unreachable Ollama → falls back to just the Claude tier badge, never a
blank or broken line.

## Workstation hosting: one floor model (local installs)

Model Routing Policy v5.1 already sends the heavy tiers off-box — HEAVY/mid
work goes to **Ollama Cloud** (the flat-rate plan) or the **Tailscale hub**,
never a workstation GPU. `bootstrap.ps1` reflects that with two profiles:

- **workstation (default):** hosts exactly ONE local model, `llama3.2:3b` —
  the floor that serves both the classifier and the `trivial` basic-tasks
  route — plus runtime caps so nothing stacks (`OLLAMA_MAX_LOADED_MODELS=1`,
  `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_CONTEXT_LENGTH=8192`,
  `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`). That is ~2GB
  resident at most — about 25% of an 8GB card, against the ~94% the old full
  local package (VRAM-tiered daily model + classifier + embedder, all
  resident) measured on the RTX 2080 work PC. Leftover package models get an
  `ollama rm` hint; nothing is auto-deleted.
- **dedicated (`-DedicatedGpu`):** the box exists to serve models (the hub),
  so the full VRAM-tiered package applies and no runtime caps are set.

Changed caps only apply to an already-running Ollama after it restarts (tray →
Quit Ollama, reopen); the script says so when needed and immediately unloads
resident models either way, so VRAM is freed on the spot.

## Main server + Tailscale (multi-PC)
Both the bridge and the classifier hook read **`CLAUDE_ROUTER_OLLAMA_URL`**
(default `http://localhost:11434`). Run Ollama on one **main server** (elzydlab)
and point every other PC at it over Tailscale — no per-PC Ollama install:

1. **Main server (elzydlab):** run Ollama listening on the Tailscale interface —
   set `OLLAMA_HOST=0.0.0.0` (env var / service config) and restart Ollama.
2. **Every PC (incl. the main one, for consistency):** set
   ```
   CLAUDE_ROUTER_OLLAMA_URL=http://elzydlab.tail76b098.ts.net:11434
   ```
   (or the Tailscale IP `http://100.122.28.89:11434`). The hook + bridge then use
   the shared hub. On the main server itself you can leave it as `localhost`.
3. Install the kit on each PC with `bash claude-defaults/bootstrap.sh --user`.

### Alternate hub — a second PC
A second PC is also reachable on the tailnet at `100.81.52.33`. Point a machine at
it the same way instead of elzydlab:
```
CLAUDE_ROUTER_OLLAMA_URL=http://100.81.52.33:11434
```
That PC needs Ollama running with `OLLAMA_HOST=0.0.0.0` for this to work, same as
the main server. (Only relevant on a machine actually on the tailnet — a cloud
sandbox session can't reach either Tailscale address.)

The cloud models still bill your **Ollama Pro** sub, not Claude — that's the point:
mid-tier load moves off the Claude weekly limit onto the flat-rate Ollama Cloud plan.
