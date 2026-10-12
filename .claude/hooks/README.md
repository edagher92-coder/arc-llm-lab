# claude-defaults/hooks

Account-wide Claude Code hooks. `bootstrap.sh` copies this folder into a repo's
`.claude/hooks/` (or `~/.claude/hooks/` with `--user`), so a hook lands in every
repo/machine from one command.

## `claude-routing-classifier.ps1` — UserPromptSubmit
The **Model Routing Policy v5.1** classifier hook. On every message it classifies
the task (STAKES / EXTRACTION / HEAVY / TRIVIAL / NORMAL) and injects a `ROUTING HINT`
naming the Agent model to delegate to (or, for HEAVY non-stakes work, offloading to
Ollama Cloud via `tools/ollama_route.py`). Hardened: a deterministic money→STAKES
regex gate (fires before the model, so money never demotes even if Ollama is
down), `temperature 0` + fixed seed, single-token output, a one-time Fable-approval
gate, and fail-open on any error. Full policy:
`edagher92-coder/Claude-code-Agents` → `docs/model-routing-policy-v4.md`.

### Wire it (Windows, once) in `~/.claude/settings.json`
```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command",
        "command": "powershell -NoProfile -ExecutionPolicy Bypass -File \"%USERPROFILE%\\.claude\\hooks\\claude-routing-classifier.ps1\"" } ] }
    ]
  }
}
```
Requires an Ollama with `llama3.2:3b` pulled — local **or** the shared hub (below).
It is **not** wired into the shared `claude-defaults/settings.json` on purpose —
that file is portable, and a Windows-only PowerShell hook would error on
Linux/cloud sessions. Wire it per the snippet above; on other environments the
hook is simply absent (and would fail open regardless).

### Shared classifier hub (preferred topology)

The classifier's ~2 GB model lives ONCE on the main server; every other PC is a
thin client over Tailscale — no local models, no per-machine RAM cost.

**Hub (main server, one-time):** run Ollama with `OLLAMA_HOST=0.0.0.0` (so it
listens on the Tailscale interface) and `OLLAMA_KEEP_ALIVE=24h` (so the
classifier stays resident for all clients); `ollama pull llama3.2:3b`. If the
hub also runs `bootstrap.ps1` locally, pass `-DedicatedGpu` — only a box that
exists to serve models hosts the full package or fills its GPU. Every other PC
defaults to the workstation profile: a single locally hosted floor model
(`llama3.2:3b`, shared by the classifier and basic tasks), with the heavy/mid
tiers on Ollama Cloud or the hub (see `tools/README.md`).

**Clients (each PC, one command):**
```powershell
.\bootstrap.ps1 -OllamaHub http://elzydlab.tail76b098.ts.net:11434
```
This persists `CLAUDE_ROUTER_OLLAMA_URL` (User env var), verifies the hub is
reachable and has the classifier model, and skips all local model installs.

Behaviour notes: against a remote hub the hook does **not** send `keep_alive`
(the server's own residency policy governs — clients can't unload the model
under each other); against localhost it sends `2m` so a single-machine setup
releases RAM between bursts. `CLAUDE_ROUTER_DISABLE_LLM_CLASSIFIER=1` remains
the zero-cost kill-switch either way, and the hook always fails open — hub
down means Claude-only routing, never a blocked prompt.

## `gstack-session-start.sh` — SessionStart

Makes [gstack](https://github.com/garrytan/gstack) (MIT, 54 role-based skills:
`/office-hours`, `/plan-ceo-review`, `/review`, `/qa`, `/ship`, …) available in a
**cloud/web** session.

Local machines get gstack from `bootstrap.sh --user`, which clones it once into
`~/.claude/skills/gstack`. Cloud and web sessions never run bootstrap — they
start from a fresh container holding only what the repo carries. Committing
gstack per repo would be ~57MB through the fan-out **and** would freeze it at
whatever was last pasted in, breaking its own `/gstack-upgrade`. So the session
clones it at start: ~2s, nothing committed, container is ephemeral anyway.

**This is the one hook the father wires automatically** (in
`claude-defaults/settings.json`), which is a deliberate exception to the
"wiring stays manual" rule above. It earns it by being unable to fail:

- every failure path prints a warning and exits 0 — a missing skill pack is an
  inconvenience, a broken SessionStart hook is a session that will not start;
- a failed clone is deleted rather than left looking installed;
- it returns immediately when gstack is already there, so resumed sessions pay
  nothing;
- the wiring is `... || true` as well, belt and braces.

Verified against: git absent, clone failing, already-installed, and opt-out.

**Opt out** on a machine or in a repo with `GSTACK_SKIP=1`.

**Cost, measured:** ~2s clone, and ~4.4k tokens of always-loaded skill
descriptions (54 skills). Full skill bodies load on demand only — the whole
corpus is ~830k tokens and is never loaded at once. If that always-on cost is
not paying for itself, set `GSTACK_SKIP=1` rather than half-removing it.

**Note:** gstack ships `/review`, which shadows Claude Code's built-in
`/review`. Its `setup` was checked and writes nothing outside its own directory
— it does not touch `settings.json`.
