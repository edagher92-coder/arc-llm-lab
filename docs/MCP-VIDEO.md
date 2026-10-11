# Prompting LTX-2.5 video over MCP

Claude (Desktop/Code), Codex and the local Qwen (Open WebUI via mcpo) drive video through the **gateway**, one stdio MCP server (`gateway/gateway.py`, VERIFIED: `server.run()`, no HTTP port of its own). Background: [VIDEO-GEN.md](VIDEO-GEN.md), [GATEWAY.md](GATEWAY.md). The gateway shows clients only `search_tools` and `call_tool` plus the `pin` list; the video tools are reached with `call_tool` (or add them to `pin`, at the cost of prompt-cache stability).

## Tools

| Tool | Policy | Does |
|---|---|---|
| `video_system` | read | GPU owner (`video`/`llm`/`busy`), ComfyUI session, queue depth, governor mode |
| `video_presets` | read | Quality presets per workflow (`draft`, `daily`, `hero`) and the 17 LTX-2.5 ComfyUI graphs from `presets/ltx25/index.json` |
| `video_workflows`, `video_status`, `video_result`, `video_queue` | read | Existing |
| `video_generate(prompt, workflow, preset, seconds, width, height, seed, image, negative)` | write, PIN | Queue a render. `preset` fills width/height/seconds; explicit arguments win (with no `workflow`, a preset name found in more than one workflow is refused as ambiguous: pass `workflow`). Width/height/seconds snapping (`multiple_of`, 8n+1 frames) is not done by the MCP tool: it is delegated to `video.resolve_params` inside `Queue.submit`. `image` is a path inside `allowed_roots` (image-to-video). Returns at once; poll `video_status` |
| `video_comfy_session(action)` | write, PIN | `start`/`stop` the interactive ComfyUI session on 127.0.0.1:8188 (takes the GPU from the LLM) |
| `video_mode(mode)` | write, PIN | `video` releases the LLM from the GPU, `llm` gives it back |
| `video_cancel` | write, PIN | Existing |

All new tools call `video.Queue` methods (`session_start/stop`, `mode_set/get`, `submit`); the code is `gateway/tools_video_mcp.py`, registered in `gateway.build()` right after `video.register()`. It replaces `video_generate` with the `preset` version.

### Policy (PIN gating)

Unlisted tools get `default_intent: "write"`, so `video_comfy_session` and `video_mode` need the approvals PIN like `video_generate`. `gateway.example.json` already lists the two new read tools in `policy.read`; copy them into your `gateway.json` (otherwise they also ask for approval, which is safe but noisy):

```
"video_system", "video_presets"
```

### Typical flow

1. `video_system` then `video_presets`, then `video_generate(prompt="...", preset="daily", seed=42)` (approve with the PIN).
2. Poll `video_status(job_id)` every 30 to 60 s, then `video_result(job_id)` for share links.
3. For a graph from `comfy_graphs` (IC-LoRA, A2V, HDR...): `video_comfy_session("start")`, open ComfyUI/CueForge, load `presets/ltx25/<file>`; `video_comfy_session("stop")` when done. These graphs do not run through `video_generate`. Session start is refused while a job runs; `video_mode` is refused while a job or session is active.

## Client configs (`configs/mcp/`)

Replace the `C:\AI\...` paths with your install. No keys are stored in these files.

| Client | File | Install at |
|---|---|---|
| Claude Desktop | `claude_desktop.example.json` | `%APPDATA%\Claude\claude_desktop_config.json` (MSIX build: under `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude`) |
| Claude Code | `claude_code.mcp.example.json` | `.mcp.json` in the project root, or `claude mcp add` |
| Codex | `codex.config.example.toml` | `~/.codex/config.toml` (`[mcp_servers.<name>]`) |
| Qwen via Open WebUI | `openwebui-mcpo.example.json` | mcpo `config.json`; tool server `http://127.0.0.1:8100/gw`, Bearer `<MCPO_API_KEY>` |

The approvals page (PIN) is served on port 8093; the gateway process must be able to start it, so run one gateway per user session, not one per client, if you want a single approval queue.

## Raw graphs: Comfy-Org comfy-mcp (optional)

Comfy-Org publishes a first-party `comfy-mcp` server (stdio) that targets a ComfyUI at 127.0.0.1:8188 and exposes `run_workflow`, `set_workflow_slot`, `fetch_outputs` and `validate_workflow`. Use it when an agent should edit and run an arbitrary graph rather than the gateway's fixed workflows.

- It only works **while a ComfyUI session is running**: `video_comfy_session("start")` first, `stop` after. It bypasses the gateway's queue, prompt limits and clip sharing, and its calls are not PIN-gated by this gateway (gate it in the client).
- Tool names above are as supplied for this task: INFERRED, not checked against the repo here.
- Install and launch are INFERRED: `uvx comfy-mcp` with `COMFY_URL=http://127.0.0.1:8188` (package name, command and the env var name are unverified). Check the Comfy-Org README and adjust `claude_code.mcp.example.json` / `codex.config.example.toml`.
- Session ComfyUI runs with `--disable-all-custom-nodes` plus the whitelist in `video.comfy_cmd`; graphs using other nodes will fail validation.
