# Story and scenes.json

## Contents
1. Story first
2. Captions
3. scenes.json schema
4. Layout coordinates (1080x1920)
5. Worked timing example

## 1. Story first

Write the beats before touching JSON. A reel works when each photo answers "what happened
next?" and the words say what the parent feels, not what the photo shows.

**Grid.** One chord = 2.5 s (96 BPM x 4 beats). Shots last about 5-6 s and overlap the next
by about 0.7 s (the fade). Start shot N at `4.3 + 5 * (N - 1)` or similar, so cuts fall on
chord changes. Captions start about 1 s after their shot and end about 1 s before the
next caption.

**Arcs that work:**
- **Keepsake (90-130 s):**
  1. Quote hook.
  2. Before (couple, pet).
  3. Arrival, with a bloom and the strings.
  4. Home and video montage.
  5. The pet as protector.
  6. The years ahead (ageing time-lapse), then milestones on portraits and a "someday" reunion.
  7. Faith or family blessing.
  8. The end card.
- **Instagram (30-45 s):**
  1. Hook line.
  2. 5-6 strongest photos.
  3. One video laugh.
  4. The end card.

  Put the emotional turn (bloom) at about 30% of the length.
- **Memorial:** warm, slower (6-7 s shots), no petals, grade 0.25. End on a single portrait
  and dates only if the user gives them.
- **Pet:** the pet as the narrator ("Before you, it was just me and them").
- **Couple, birthday or anniversary (30-45 s):**
  1. Open with "Happy birthday, ~Name~" on the intro.
  2. 4-5 photos in time order, with the dog or kids as a warm beat.
  3. One line of theirs ("Ten years. One love.") on the end card, with both names.

  Address the partner ("Still falling for you, every day").

**Voice.** Use the family's words, Australian or British spelling if that is theirs. Keep
the second person, addressed to the child ("You fell asleep on my heart").

**Quotes.** Quote only well-known lines, and attribute them correctly. A blessing card or
prayer the user sends is gold: quote it with its attribution (for example
"^— Jeddo & Teta").

## 2. Captions

Each caption is a list of lines. The markup is:
- `PLAIN TEXT`: spaced capitals in the sans font (the "label" voice).
- `*italic*`: large italic serif (the "heart" voice). A line can mix both.
- `~Name~`: a big glowing script. Use it once or twice, for names. It gets no dark backdrop.
- `^— Attribution`: a small gold italic.

Pair one caps line with one or two italic lines. Keep each line under about 28 characters;
longer lines auto-shrink, which reads worse. The `theme` values are:
- `photo` (the default): white text on a soft dark backdrop.
- `intro`: no backdrop, for the dark opening.
- `paper`: dark ink, for the ageing and end-card paper.

## 3. scenes.json schema

Times are in seconds. Coordinates for `blur`, `box`, `patch` and Ken Burns `from`/`to` are
fractions of the photo (0..1), unless the photo sets `"disp": [w, h]`. With `disp`, they
are pixels in that space (handy when measuring on a resized preview). Everything except
`duration`, `photos`/`shots` and `captions` is optional.

```jsonc
{
  "name": "For Amelia",               // browser tab title only
  "width": 1080, "height": 1920, "fps": 30, "duration": 60,
  "output": "out/reel.mp4",
  "music": null,                      // "uploads/song.mp3" to use the user's own track instead of score.wav
  "look": { "grade": 0.34, "grain": 0.07, "vignette": true, "particles": 0.45, "petals": true },
  "intro": { "t1": 4.3 },             // dark warm background until the first photo (for an opening quote)

  "photos": {                         // name -> source; prep.py writes assets/<name>.jpg
    "arrival": { "file": "IMG_1234.HEIC", "rotate": 0, "blur": [[0.1, 0.62, 0.3, 0.8]] },
    "portrait21": { "chain": "child_21" }   // an AI still from ai/finalize.py ({"gen": "<job id>"} for gen.py scenes)
  },
  "videos": { "laugh": { "src": "IMG_5678.MOV", "ss": 1.2, "speed": 0.85, "crop": null } },   // crop: ffmpeg "w:h:x:y"
  "cards":  { "mum": { "file": "IMG_1.jpg", "box": [0.1, 0.2, 0.4, 0.45], "whiten": false, "patch": [] } },
  "sprites": { "dog": { "src": "dog_clip.mp4", "bg": "auto", "tol": 9, "fps": 12, "max_frames": 120, "height": 480 } },

  "shots": [
    { "photo": "arrival", "t0": 4.3, "t1": 10.4, "fade": 0.9,
      "from": [0.5, 0.45, 0.95], "to": [0.5, 0.40, 0.75],   // [centre x, centre y, frame height] -> zooms in
      "depth": 0.04, "pan": [1, 0.25] },                     // optional 2.5D parallax (needs ai/depth.py + parallax.py)
    { "photo": "beach", "t0": 9.7, "t1": 15.4, "fade": 0.7, "fit": true },   // landscape: sharp photo on a blurred cover
    { "video": "laugh", "t0": 14.7, "t1": 20.4, "fade": 0.7 }
  ],
  "captions": [ { "t0": 0.6, "t1": 4.3, "y": 900, "theme": "intro", "lines": ["*Darkness*", "CAN ONLY BE SCATTERED", "BY *light.*", "^— St John Paul II"], "scale": 1 } ],
  "blooms": [ { "t": 30.3, "y": 800, "size": 1 } ],   // white-gold light bloom: the emotional turn
  "lightLeaks": [12.2, 44.6],
  "petalsFrom": 112,

  "title":  { "t0": 69.8, "t1": 73.0, "y": 930, "lines": ["THE YEARS AHEAD", "*as we dream them*"] },
  "ageing": {                                         // portrait rings age together on paper
    "t0": 72.5, "t1": 82.5, "xfade": 0.45, "counterY": 330, "zoom": 1.28, "lift": 0.5,
    "slots": [ { "key": "m", "x": 200, "y": 760, "r": 140, "label": "Mum" },
               { "key": "a", "x": 540, "y": 700, "r": 180, "label": "Amelia", "big": true },
               { "key": "d", "x": 880, "y": 760, "r": 140, "label": "Dad" },
               { "sprite": "dog", "x": 540, "y": 1120, "h": 280, "label": "Storm", "loop": [27, 56], "fps": 12 } ],
    "steps": [ { "label": "TODAY", "age": "5 months", "a": "age/child_today.jpg", "m": "age/mum_today.jpg", "d": "age/dad_today.jpg" },
               { "label": "AMELIA, AGE", "age": "1", "a": "age/child_01.jpg", "m": "age/mum_39.jpg", "d": "age/dad_34.jpg" } ]
  },
  "reunion": { "t0": 102.3, "t1": 107.9, "label": "SOMEDAY", "age": "still together" },   // the last step, frozen

  "endcard": {
    "t0": 117.3,
    "faces":  [ { "card": "mum", "slot": [250, 520, 130], "label": "Mum", "at": 117.8 } ],
    "sprite": { "name": "dog", "x": 540, "y": 900, "h": 240, "at": 119.0, "fps": 12, "label": "Storm" },
    "lines":  [ { "t": 119.6, "y": 1050, "text": "~Amelia Mae~", "scale": 0.62 },
                { "t": 120.4, "y": 1180, "text": "LOVED BEYOND MEASURE, ALWAYS." },
                { "t": 122.0, "y": 1400, "text": "*Father, thank you for my family.*", "soft": true } ],
    "divider": { "t": 121.2, "y": 1290 }
  },
  "score": { "key": "D", "bpm": 96, "strings_at": 30.0, "key_lift_at": 72.5, "ripple": [72.5, 82.5],
             "music_box_at": [65.0, 117.5], "peak": [97.5, 107.5], "dynamics": [[0, 40], [30, 62], [100, 78], [126, 44]] }
}
```

Notes:
- **Shots** draw in list order; overlap them by the fade. The `from` frame height is a
  fraction of the photo's height. `1.0` means the whole height; smaller zooms in. The
  frame is clamped inside the photo, so an edge subject can't be centred.
- **Ageing** step keys match slot `key`s. Values are paths under `assets/` (from
  `ai/finalize.py`: `age/<who>_<tag>.jpg`, plus `age/<who>_today.jpg` for the real
  crop). Each step lasts `(t1 - t0) / steps`; the last `xfade` seconds crossfade.
- **Sprites** play once on the end card and hold their last frame. In an ageing slot they
  loop the `loop` frame range. Key a clip with a plain background (the default "auto"
  takes the median border colour). Only edge-connected background is removed, so white
  patches on the animal stay.
- **Cards** are square crops used in the end-card circles. `whiten` levels paper to white,
  for drawn or printed art. `patch` paints over something poking into the circle.
- **Score** defaults come from the timeline: strings enter at the first bloom, the key
  lifts at `ageing.t0`, the ripple runs through the ageing window, and a music box plays
  at the start and the end card. Override only what the story needs.

## 4. Layout coordinates (1080x1920)

- **Caption safe zone:** y 250-1470. Instagram's own UI covers the top 250 px and the
  bottom 450 px. Put captions over photos at y 1250-1350, or at y 850-950 when the faces
  are low in the frame.
- **Three portraits:** slots (200, 760, r 140), (540, 700, r 180, big), (880, 760, r 140).
  The counter goes at y 330, and a sprite sits under the middle ring at y 1120 with h 280.
  Keep at least 40 px between a label's baseline and the top of the sprite. Labels sit
  about r + 60 below the ring centre.
- **End card:** faces at y 470-520, then a sprite at about y 900, the script name at about
  1050, a caps line at 1180, a divider at 1270-1290, and a soft italic line at 1400. Face
  `slot` presets `[x, y, r]`:
  - **1 person:** `[540, 560, 200]`
  - **2 people:** `[330, 540, 160]`, `[750, 540, 160]`
  - **3 people:** `[250, 520, 130]`, `[540, 470, 160]`, `[830, 520, 130]`
  - **4 people:** `[160, 560, 105]`, `[390, 510, 115]`, `[690, 510, 115]`, `[920, 560, 105]`

  Stagger their `at` times by 0.5 s.
- **Reading coordinates:** don't measure pixels by hand. Run
  `python SKILL/scripts/photo_grid.py uploads/` and look at `out/grid/*.jpg`: each photo
  gets a labelled 0.0-1.0 grid, which you can read for `blur` boxes, card `box`es and Ken
  Burns centres. With the AI tier installed it also boxes faces and prints `pick_x` and a
  suggested card box. After `prep.py`, check `out/cards_preview.jpg`.

## 5. Worked timing example (45 s, Instagram)

| t | beat | notes |
|---|---|---|
| 0-4.3 | quote on the intro | `intro.t1` = 4.3, caption theme intro |
| 4.3-10.4 | the couple / pet | 2 shots of about 5 s |
| 10.4 | bloom + name | the strings enter (score `strings_at` 10) |
| 10-25 | arrival, home, a video laugh | captions at 11, 16, 21 |
| 25-35 | two strongest photos | one landscape in `fit` mode |
| 36.8-45 | end card | faces at 37.3, 37.8, 38.3; lines at 39-41 |

**30 s version:** set `"score": {"bpm": 120}` for 2 s bars, and cut every 4 s so shots
still land on chord changes.

| t | beat |
|---|---|
| 0-3.3 | hook on the intro (`intro.t1` 3.3) |
| 3.3-7.8, 7.1-11.6 | two photos (bloom and strings at about 8) |
| 10.9-15.4 | video clip (pet or kids) |
| 14.7-19.2, 18.5-23.5 | the landscape photo in `fit`, then the finale photo |
| 23.0-30.0 | end card: faces at 23.5 and 24.0, name at 25.2, line at 26.0, divider at 26.6 |
