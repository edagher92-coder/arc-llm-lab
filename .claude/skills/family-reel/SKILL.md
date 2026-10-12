---
name: family-reel
description: |
  [CREATIVE] Turn family photos and videos into an emotional, story-driven vertical
  reel (1080x1920 MP4 for Instagram/TikTok or to keep): original piano-and-strings
  score, animated captions, photos that move in 2.5D, video snippets, an end card,
  and optional local-AI "growing up / ageing together" portraits, all rendered on
  the user's own machine. Use whenever someone wants a keepsake, tribute or story
  video from their photos: new baby, dad and daughter, mum, wedding, anniversary,
  birthday, memorial, a family pet, "animate our photos", "make a reel of us",
  "show us growing old together", "something we can keep forever", even when they
  never say "reel" or "video editor". Works in Cowork, Claude Code and on any
  Windows, Mac or Linux machine with Python and Node.
compatibility: Python 3.9+ and Node 18+. scripts/doctor.py installs the rest (Playwright + a browser, fonts). FluidSynth is optional (a built-in synth stands in). The AI portrait tier downloads about 7 GB of models.
---

# Family reel

Make a short film a family will keep: their real photos, in story order, moving gently,
with words that sound like them and music written for the cut. Everything renders
locally from a JavaScript canvas engine, frame by frame, so the result is exact and
repeatable. `SKILL` below means this skill's folder.

## Ground rules

These exist because a keepsake is personal and permanent. Getting them wrong costs trust.

- **Local by default.** Family photos, especially of children, go to no cloud AI
  service unless the user explicitly asks. Every tool here runs on the machine; say so.
  Paid generators need explicit approval first, and you report what was spent.
- **Privacy pass before rendering.** Blur hospital wristbands and labels (names, dates
  of birth, record numbers) with `blur` boxes. Crop graphic birth moments to faces and
  hands, frame bath photos face-and-shoulders, and leave identifiable strangers out.
- **Never invent facts.** Names, ages, dates and relationships come from the user.
  Confirm the spelling of every name once (it will be on screen forever). Label an
  imagined future as imagined, for example "the years ahead, as we dream them".
- **Faces must look right.** People notice eyes first. Never ship a cross-eyed or
  wall-eyed AI face, and never use a goofy or angled selfie as an AI source. Check
  every face at full size (see `references/ai-portraits.md`).
- **Real beats generated.** Real photos carry emotion; AI supports them. AI
  multi-person scenes lose likeness and AI-aged pets look uncanny. Use portraits,
  real photos, and a keyed sprite of the pet from the user's own clip instead.
- **Keep media out of git.** Projects ship a `.gitignore` for photos, renders and face
  embeddings (biometric data). Delete embeddings when the project is finished.

## Workflow

**0. Check the machine.** `python SKILL/scripts/doctor.py` reports three tiers:
*core* (photos, clips, captions, score, render), *depth* (2.5D moves) and *ai*
(ageing portraits). Install what is missing with `--install core` (about 300 MB),
`--install depth` (about 1.5 GB) or `--install ai` (about 7 GB and 20+ minutes, so ask
first). Run `--selftest` once (about 2 minutes) to prove a render works end to end. If a
download is blocked, drop to the next tier down and tell the user what they are
missing.

**1. Start a project.** `python SKILL/scripts/new_reel.py <folder>/reel` copies the engine,
an example `scenes.json`, AI config templates, a `.gitignore` and fonts. Put the
photos and videos in `uploads/`, or pass their folder to `prep.py`. Run every later
command from inside the project folder. Use `python3` wherever `python` isn't found.

**2. Inventory every upload.** Record what it shows, who is in it, its orientation, its
faces, any privacy issue, and which story beat it serves. Ask only what the photos
cannot answer: spelling of names, ages, what the child calls each parent, pets' names,
target length (30-60 s for Instagram, up to about 2 minutes for a keepsake), and
whether to use the original score or a track they own.

**3. Write the story, then `scenes.json`.** Beats sit on a 2.5 s grid (one chord per
2.5 s), so each photo holds about 5 s and every cut lands on a chord change. A proven arc:

1. A hook: a quote on a dark intro.
2. Before: the couple, the pet.
3. The arrival, with a light bloom and the strings entering.
4. Home life, with video snippets and a laughing montage.
5. Optional: the years ahead, as an ageing time-lapse plus milestone captions.
6. Faith or family.
7. The end card, with face cards and names.

Captions are a short spaced-caps line plus an italic line, in the family's voice. The
schema, caption markup and layout coordinates are in `references/story-and-scenes.md`.
For crop, blur and card coordinates, run `python SKILL/scripts/photo_grid.py uploads/`
and read the labelled grids instead of guessing.

**4. Prep.** `python prep.py` orients, blurs, crops cards, cuts video snippets and keys
sprites. Look at `out/crop_preview.jpg` (the first and last frame of every Ken Burns
move), `out/cards_preview.jpg` and `out/sprite_*_preview.jpg`. Fix framing now, not after a
render.

**5. Optional depth.** `python ai/depth.py && python parallax.py` makes stills feel like
small camera moves. Use `depth` 0.03-0.05 on photos with a clear subject; flat photos
and text cards get none.

**6. Optional AI portraits.** Follow `references/ai-portraits.md`: identity embeddings,
the ageing chain with an eye-checked seed beam, anchor ageing for adults, eye
transplant, then `ai/finalize.py`. Budget about 30 s per image on 4 CPU cores.

**7. Score.** `python compose.py` writes `score.mid` and a loudness-normalised
`score.wav` fitted to the timeline. It uses FluidSynth when installed, otherwise the
built-in synth. To use the user's own track, set `"music": "uploads/song.mp3"`.

**8. Stills, then the full render.** Run `node render.cjs --stills 3,12,25,40` and
look at every still. Check caption collisions with faces, overlaps (sprite vs labels),
the safe zone, and spelling. Then run `node render.cjs`: about 0.2 s per frame on 4
cores, so a 45 s reel takes about 5 minutes. Run it in the background and report
progress.

**9. Verify, fix, deliver.** `python SKILL/scripts/finish.py out/reel.mp4` checks frames,
duration, decoding and loudness, and writes a frame sheet. Look at it. Fix a section
after the full render with `node render.cjs --range 60,75` then `finish.py --splice
out/segment-60-75.mp4`; don't re-render the whole reel. Shrink for a size-limited
channel with `--target-mb 29`.

## Delivering

- **Cowork or a local machine:** the MP4 is already on the user's computer. Give the full
  path and suggest AirDrop, Photos or Google Drive to get it onto a phone.
- **Claude Code on the web:** file attachments are limited to 30 MB and some apps won't open
  them. The fallback is a private artifact page: split the MP4 into 10 MB parts named
  `.mp4`, join them in the page, and save through the `downloads` capability. See
  `references/render-and-deliver.md`.
- Instagram wants 1080x1920 H.264 with AAC audio, and all text between y 250 and 1470.

## Done means

Only call it done when all of these hold:

- Every face has been viewed at full size.
- Names are spelled as confirmed, and privacy blurs are in place.
- No caption sits on a face.
- Imagined parts are labelled as imagined.
- `finish.py` shows the expected frame count, duration and audio, and you have looked
  at the frame sheet.

Then tell the user plainly:
- what is real and what is AI;
- what ran locally;
- any credits spent;
- anything you could not verify.

## References

- `references/story-and-scenes.md`: story arcs, the beat grid, caption markup, and the
  full `scenes.json` schema with layout coordinates.
- `references/ai-portraits.md`: local AI ageing portraits, including the models, the
  chain, eye QA, anchors, eye transplant, what to reject, and licences.
- `references/render-and-deliver.md`: parallax, render speed, section re-renders and
  splicing, compression, and delivery (including the artifact page recipe).
- `references/troubleshooting.md`: failures seen in practice, with their fixes.
