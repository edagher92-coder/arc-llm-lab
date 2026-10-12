# Auto Production (Elz LTX-2.5)

Smart prompt generation for the LTX-2.5 ComfyUI setup. You write one line of what happens; Auto Production adds grading, generated sound, effects, styling, camera, lighting, shot type and an optional character, using cheat sheets in plain JSON (MIT). Everything is prompt-level: it only produces text, so it works in any ordinary ComfyUI workflow, including the ones CueForge runs.

## Files

| Path (under `gateway/`) | What |
|---|---|
| `comfy_nodes/elz_nodes/production.py` | `ElzProductionPrompt`, `ElzQwenDirector` (stdlib only) |
| `comfy_nodes/elz_nodes/cheatsheets/*.json` | grading 10, sound 12, effects 9, styling 8, camera 10, lighting 9, shots 9, characters 3, plus `production_presets.json` |
| `comfy_nodes/elz_nodes/web/elz_production.js` | "Production" sidebar tab and menu commands (one-click presets) |
| `presets/ltx25/auto/` | `Auto_Production_T2V_I2V_Two_Stage_Distilled.json` and `..._Single_Stage_Distilled.json` |
| `tests/test_elz_production.py` | schema, determinism, length, fail-soft, link integrity |

## Install

1. Copy `comfy_nodes/elz_nodes/` into `ComfyUI/custom_nodes/` (already whitelisted as `elz_nodes`). Restart ComfyUI. The cheat sheets and the web extension travel with the folder.
2. Copy `presets/ltx25/auto/*.json` into `ComfyUI/user/default/workflows/` so the Production buttons can open them (or open them from the Workflows list).

## ElzProductionPrompt

Inputs: `idea` (multiline), `style`, `grade`, `sound`, `effects`, `camera`, `lighting` (each `auto`, `none` or a sheet id), `length_seconds` (1-60), `auto` (on: `auto` dropdowns are resolved; off: `auto` behaves like `none`), optional `character`, `shot` and `negative_extra`.
Outputs: `positive`, `negative`, `plan` (JSON: the picks and where each came from, the characters, the final prompt, warnings).

- **auto** scores every entry by whole-word keyword hits in the idea (a multi-word keyword counts for its words). Highest score wins, ties go to the entry listed first, no hit falls back to the entry flagged `default` (none for effects). Same idea, same picks, every time.
- **length** under ~1500 characters. If the fragments would exceed it they are dropped in a fixed order (effects, shot, lighting, grade, sound, camera, style); the idea and character are never dropped. The plan lists what was dropped.
- **character** takes an example id (`mara`, `tomas`, `kai`), one JSON object `{"name","look","wardrobe","voice","mannerisms"}`, a JSON list (max 3) or plain text. Put dialogue in the idea, in quotes, naming the speaker.
- The negative prompt merges `negative_extra`, the picked entries' negatives and a short base negative, de-duplicated.

## ElzQwenDirector (optional)

Asks an OpenAI-compatible chat endpoint to rewrite the template prompt into one flowing LTX-2.5 paragraph, keeping every choice. Defaults: endpoint `http://127.0.0.1:8090/v1/chat/completions`, model `qwen3.8-27b`, key file `C:\AI\llama-swap\api-key.txt`, timeout 20 s, `skip_if_unavailable` on.

- **Default to template mode.** While ComfyUI runs, the LLM is normally unloaded to free VRAM, so the director falls back to the template prompt (status `fallback: ...`). To use it, run it before the GPU lease (wake the model, queue a director-only run, copy the result into the idea box with `auto` off) or point it at a small CPU-only model.
- With `skip_if_unavailable` off, a failure raises an error (the message never contains the key).
- Loopback only: an endpoint that is not `localhost`, `127.0.0.0/8` or `::1` is refused (status `fallback: remote endpoint refused (loopback only)`), nothing is sent and no key is read. Redirects are never followed.
- The key is read only from the default key file or the file named by the `ELZ_LLM_KEY_FILE` environment variable (compared by resolved real path); any other `api_key_file` is ignored with `(key file not allowed)` in the status. It is max 512 bytes, sent only as a Bearer header, and never logged or returned.
- The reply is stripped of `<think>` blocks and code fences, and capped at 1500 characters.

## Auto workflows

Copies of `LTX-2.5_T2V_I2V_{Two,Single}_Stage_Distilled.json` with one new node. The old "Prompt (positive)" box is now the **idea** box and feeds `ElzProductionPrompt`; the old "Prompt (negative)" box feeds `negative_extra`. The node's `positive` and `negative` outputs go to the same prompt-subgraph inputs the boxes used, and `plan` goes to a preview node. Every other node and link is unchanged. The node sits in an "Auto Production" group under the inputs. `length_seconds` here only shapes the pacing wording; the real duration is still the "duration in seconds" box.

## Production buttons

Sidebar "Production" (and the command palette, "Production: ...") offers Trailer, Product ad, Music video, Documentary and Social vertical. Each opens the matching auto workflow if none is open, sets the dropdowns and length, fills the idea box if it is empty, and sets width/height (Social vertical is 576x1024; the other presets are 1024x576, all multiples of 64). Leave a dropdown on `auto` afterwards to let your idea decide. The presets live in `cheatsheets/production_presets.json` and are mirrored in the JS; a test keeps them identical.

## Adding or editing entries

Edit the sheet JSON. Each entry: `id` (lowercase, digits, `-`), `label`, `prompt` (one present-tense sentence, under ~260 characters), optional `negative`, `keywords` (used by auto), `notes`, optional `default: true` (at most one per sheet). Keep a whole prompt under ~200 words. Run `python -m pytest tests/test_elz_production.py -q`. Changing a sheet's ids changes the dropdown lists; saved workflows holding a removed id will fail validation until re-selected.

## Notes

- Sound fragments steer LTX-2.5 generated audio. Effects such as slow motion, speed ramp and handheld shake are cues the model approximates, not post-production.
- The phrasing follows Lightricks' public LTX-2 prompting guidance (one flowing present-tense paragraph; action first; movement, appearance, environment, camera, lighting and colour; audio described in the prompt). Sheet text is original.
