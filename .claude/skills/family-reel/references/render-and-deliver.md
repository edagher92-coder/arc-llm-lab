# Render, verify and deliver

## Contents
1. How the engine renders
2. Speed and what slows it
3. Fixing a section after the full render
4. Verifying
5. Delivering (Cowork, local, Claude Code on the web)

## 1. How the engine renders

`reel.js` draws every frame on a canvas as a pure function of time. `render.cjs` serves the
project over http (a `file://` page taints the canvas), steps a headless browser
frame by frame, and pipes JPEG frames into ffmpeg: H.264 High, CRF 17, AAC,
`+faststart`. The audio is `score.wav`, `"music"` from `scenes.json`, `--music file`,
or silence.

The browser is found in this order: `$CHROME_PATH`, then Playwright's Chromium, then
installed Google Chrome, then Microsoft Edge, then a system Chromium. Windows always has
Edge, and most Macs have Chrome, so a blocked Chromium download is not fatal.

Opening `reel.html` through any local web server (for example `python -m http.server`)
plays the reel live with the score. That makes a quick preview for the user before the
full render.

## 2. Speed

- **Rendering:** about 0.17-0.2 s per frame on 4 cores (30 fps: about 6 s of work per
  second of reel). 45 s takes about 5 minutes; 2 minutes takes about 12 minutes.
- **Depth parallax:** pre-render it with `parallax.py` (OpenCV, all cores, about 80 s for
  20 shots). Don't use WebGL in a headless browser: software WebGL (SwiftShader) runs at
  about 1.2 s per frame and its flags push the 2D canvas onto the software GPU (5x slower
  overall). The engine only uses WebGL as a fallback, and `render.cjs` only enables it
  with `WEBGL=1`.
- **Spot-check first:** always run `node render.cjs --stills 3,12,25,...` before a full
  render (seconds instead of minutes).
- **Large renders:** run them in the background and poll the log. The renderer prints
  its progress and the minutes left.

## 3. Fixing a section after the full render

Don't re-render everything for a local fix (a label collision, a caption typo in one
scene):

```bash
node render.cjs --range 71.5,109                               # frames 2145..3269, video only
python SKILL/scripts/finish.py out/reel.mp4 --splice out/segment-71.5-109.mp4
```

Start the range a little before the first changed frame and end it a little after (for
example, a whole ageing window plus its fades). `finish.py` splices by frame number,
keeps the original audio, and forces the frame rate on every pass. Without `-r`, ffmpeg
tags a concat as 25 fps and a two-pass encode fails. Check the frames before and after
each seam on the sheet.

## 4. Verifying

`python SKILL/scripts/finish.py out/reel.mp4` prints the frame count (expect
`duration x fps`), duration, size, audio presence, decode errors and loudness (expect a
mean of about -16 to -18 dB and a peak of about -1.5 dB). It also writes a 12-frame
`*-sheet.jpg`. Look at the sheet and at full-size stills of every face-heavy moment.

## 5. Delivering

**Cowork, or any local run:** the file is already on the user's machine. Name it clearly
(for example `Amelia-Mae-reel.mp4`) in the folder they shared, and give the path. For a
phone: AirDrop, Photos, Google Drive, or the Instagram app directly.

**Size limits:** shrink with `finish.py out/reel.mp4 --target-mb 29` (two-pass; about 1.8
Mb/s holds up well for a 2-minute 1080x1920 reel).

**Claude Code on the web (remote container):** a file attachment (SendUserFile) is
limited to 30 MiB, and some apps won't open it. When the user can't open an attachment,
publish a private artifact download page:

1. Split the MP4 into 10 MB parts, and give each a `.mp4` name so the artifact host serves
   it. The artifact host refuses `.bin` and `.zip`, and binaries over about 15 MB.
2. Publish the page with `capabilities: {"downloads": true}` and the parts in `files`.
3. In the page, fetch the parts in order into one `Blob` (type `video/mp4`). Play it from
   a `blob:` URL and save it with `(await claude.use("downloads")).save({filename:
   "reel.mp4", data: blob})`. The viewer confirms the save; on iPhone it opens the share
   sheet ("Save Video" puts it in Photos).
4. After publishing, read the parts back from the artifact, join them, and compare the
   sha256 with the original.

The artifact host cannot serve a zip. For a skill or code download, link the GitHub
branch archive (`https://github.com/<owner>/<repo>/archive/refs/heads/<branch>.zip`)
instead.

**Instagram specs:** 1080x1920 (9:16), H.264 High, AAC 48 kHz, 30 fps. Reels play up to
3 minutes, but 30-90 s holds attention best. Keep text between y 250 and 1470.
