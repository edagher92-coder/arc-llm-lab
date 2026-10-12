# Troubleshooting

Failures seen while building real reels, and the fix for each.

## Setup
- **`pip` refuses (externally-managed environment, PEP 668).** `doctor.py` retries with
  `--user --break-system-packages`. Otherwise use a virtual environment:
  `python -m venv .venv && . .venv/bin/activate` (Windows: `.venv\Scripts\activate`).
- **Playwright's Chromium download is blocked or slow.** Install Google Chrome or
  Microsoft Edge, or set `CHROME_PATH`; `render.cjs` falls back to them automatically.
- **No FluidSynth.** The built-in synth (`synth.py`) renders the score. For a richer piano:
  `apt install fluidsynth fluid-soundfont-gm`, `brew install fluid-synth` (plus any GM
  `.sf2`, pointed to by `SOUNDFONT`), or `choco install fluidsynth`.
- **Fonts fail to download.** System serif, sans and script fonts stand in. The reel still
  works but looks plainer. Fonts come from the Google Fonts CSS API (GitHub raw URLs
  returned 403).
- **`insightface` fails to install on Windows.** It compiles a C++ extension (needs Visual
  Studio Build Tools). Run the AI tier under WSL, or skip it: the reel is complete without
  AI portraits.
- **Model downloads are blocked.** Hugging Face mirrors (for example `immich-app/buffalo_l`)
  work where GitHub release assets are blocked. If huggingface.co itself is blocked, skip
  the depth and AI tiers and say so.

## Prep
- **iPhone photos (HEIC) won't open.** `pip install pillow-heif` (installed by
  `--install core`).
- **A sideways photo.** EXIF orientation is applied automatically. If a photo still
  appears rotated, add `"rotate": 90` (or 180/270).
- **"clip too short" for a video.** The shot needs more frames than the clip provides after
  slowing. Start earlier (lower `ss`), slow it more (lower `speed`, for example 0.6 or 0.45,
  since slow motion stretches the clip), or shorten the shot.
- **A sprite keeps a halo or loses white patches.** Raise or lower `tol` (default 9). Only
  background touching the frame edge is removed, so fur and white chests stay.
- **Black borders in an AI face crop.** The crop is clamped inside the photo. Use a photo
  where the face isn't at the edge, or give a manual `box`.

## Render
- **`reel.js failed to load: missing asset: ...`** An asset listed in `scenes.json` hasn't
  been prepared. Run `prep.py` (and `ai/finalize.py`, `ai/depth.py` + `parallax.py` for AI
  and depth shots), and check the names match.
- **The render is very slow (over 1 s per frame).** You're on the software WebGL path. Run
  `parallax.py` so depth shots are pre-rendered, and don't set `WEBGL`.
- **A caption overflows or looks tiny.** A line is too long, so it auto-fits and shrinks.
  Split it into two lines.
- **Text overlaps a face or a label.** Move the caption's `y` or the slot/sprite
  coordinates, check with `--stills`, then fix just that section with `--range` and
  `finish.py --splice`.
- **The age counter looks doubled for a moment.** That's the crossfade between steps (about
  0.45 s). Shorten `xfade` if it bothers the user.

## Music
- **Cuts don't land on the beat.** Keep shot starts on the 2.5 s grid (or change `bpm` /
  `beats` so the bar length matches the edit).
- **The score is too quiet or loud.** `compose.py` loudness-normalises to -16 LUFS with a
  -1.5 dB peak. `finish.py` reports the mean and peak.

## Delivery
- **The user can't open the attachment.** Use the artifact download page recipe in
  `render-and-deliver.md`.
- **The splice output has a different frame count, or the two-pass encode fails.** Pass
  `-r <fps>` on every pass. `finish.py` does this.

## Process
- **`pkill -f <pattern>` kills your own shell** when the pattern appears in the command
  line. Kill by PID from `ps` output (`grep "[p]attern"`).
- **Deliver an early version first.** Deliver a good v1 early, then iterate on v2 after
  the family has seen it. Their feedback ("the eyes look wrong", "use a different photo of
  me") matters more than any metric.
