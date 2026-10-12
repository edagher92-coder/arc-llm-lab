"""Original score for a family reel, fitted to scenes.json (its optional "score" section).

A canon-style progression changes chord every bar (default 96 BPM x 4 beats = 2.5 s),
so every cut placed on the 2.5 s grid lands on a chord change. Solo piano and a music
box open; strings and cello enter on the emotional turn; an optional whole-step key
lift marks "the years ahead"; 16th-note ripples run under a time-lapse; the last
chords resolve plagally and ring under the end card.

  python compose.py          -> score.mid + score.wav (FluidSynth + soundfont if installed, else synth.py)
  python compose.py --midi   -> score.mid only

"score" keys (all optional; seconds): bpm, beats, key ("D"), strings_at, key_lift_at,
ripple [from, to], music_box_at [t, ...], peak [from, to], dynamics [[t, 40..80], ...], seed.
Sensible defaults come from the blooms, ageing and endcard sections.
"""
import glob
import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

import mido

HERE = Path(__file__).parent
cfg = json.loads((HERE / "scenes.json").read_text())
S = cfg.get("score", {})
D = float(cfg["duration"])
random.seed(S.get("seed", 7))

BPM = S.get("bpm", 96)
BEAT = 60 / BPM
BAR = S.get("beats", 4) * BEAT
END_HOLD = 6.0
TPB = 480
KEYS = {"C": 0, "Db": 1, "D": 2, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "Ab": 8, "A": 9, "Bb": 10, "B": 11}
BASE = KEYS.get(S.get("key", "D"), 2)
BASE = BASE - 12 if BASE > 6 else BASE

C, E, F, G, A, B = 0, 4, 5, 7, 9, 11
Dn = 2
CHORDS = {
    "C": (48, [C, E, G]), "G/B": (47, [G, B, Dn]), "Am": (45, [A, C, E]), "Em/G": (43, [E, G, B]),
    "F": (41, [F, A, C]), "C/E": (40, [C, E, G]), "Dm7": (38, [Dn, F, A, C]),
    "Gsus4": (43, [G, C, Dn]), "G": (43, [G, B, Dn]), "Cend": (36, [C, E, G]),
    "A7": (45, [A, 1, E, G]),  # pivot: V7 of the key a whole step up
}
CYCLE = ["C", "G/B", "Am", "Em/G", "F", "C/E", "Dm7"]

slot = lambda t: int(round(t / BAR))
n = max(8, int((D - END_HOLD) / BAR + 1e-6) + 1)
ageing, endcard, blooms = cfg.get("ageing"), cfg.get("endcard"), cfg.get("blooms", [])
strings_at = S.get("strings_at", blooms[0]["t"] if blooms else D * 0.25)
lift_at = S.get("key_lift_at", ageing["t0"] if ageing else None)
LIFT = slot(lift_at) if lift_at is not None else None
if LIFT is not None and not (8 <= LIFT <= n - 6):
    LIFT = None
ripple = S.get("ripple", [ageing["t0"], ageing["t1"]] if ageing else None)
RIPPLE = set(range(slot(ripple[0]), slot(ripple[1]))) if ripple else set()
peak = S.get("peak")
PEAK = set(range(slot(peak[0]), slot(peak[1]))) if peak else set()
STRINGS_FROM = max(1, slot(strings_at))


def fill(length):
    out, k = [], 0
    while len(out) < length:
        out += CYCLE + (["Gsus4"] if k == 0 else ["G"])
        k += 1
    return out[:length]


body = n - 4
if LIFT:
    seg1 = fill(LIFT)
    seg1[-1] = "A7"
    PROG = seg1 + fill(body - LIFT)
else:
    PROG = fill(body)
PROG += ["Am", "F", "Gsus4", "Cend"]
transpose = lambda i: BASE + (2 if LIFT and i >= LIFT else 0)

# dynamics: keyframes [t, velocity] interpolated at each bar
dyn_keys = S.get("dynamics") or [[0, 40], [D * 0.15, 50], [strings_at, 60], [D * 0.5, 64], [D * 0.8, 72], [D - 8, 56], [D, 44]]
dyn_keys = sorted(dyn_keys)


def dyn_at(t):
    if t <= dyn_keys[0][0]:
        return dyn_keys[0][1]
    for (t0, v0), (t1, v1) in zip(dyn_keys, dyn_keys[1:]):
        if t <= t1:
            return v0 + (v1 - v0) * (t - t0) / max(1e-6, t1 - t0)
    return dyn_keys[-1][1]


DYN = [int(dyn_at(i * BAR)) for i in range(n)]

N = lambda s: {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[s[0]] + 12 * (int(s[1:]) + 1)
PHRASE_A = [
    [("E5", 0, 2), ("D5", 2, 1), ("E5", 3, 1)],
    [("G5", 0, 1.5), ("E5", 1.5, 0.5), ("D5", 2, 2)],
    [("C5", 0, 2), ("A4", 2, 1), ("C5", 3, 1)],
    [("E5", 0, 1.5), ("D5", 1.5, 0.5), ("C5", 2, 2)],
    [("D5", 0, 1), ("E5", 1, 1), ("F5", 2, 1), ("A5", 3, 1)],
    [("G5", 0, 2), ("F5", 2, 1), ("D5", 3, 1)],
]
PHRASE_B = [
    [("E5", 0, 1), ("G5", 1, 1), ("C6", 2, 2)],
    [("B5", 0, 1.5), ("A5", 1.5, 0.5), ("G5", 2, 2)],
    [("A5", 0, 1), ("C6", 1, 1), ("E6", 2, 1.5), ("D6", 3.5, 0.5)],
    [("B5", 0, 2), ("G5", 2, 1), ("B5", 3, 1)],
    [("C6", 0, 1.5), ("A5", 1.5, 0.5), ("F5", 2, 1), ("A5", 3, 1)],
    [("G5", 0, 1.5), ("E5", 1.5, 0.5), ("C6", 2, 2)],
    [("D6", 0, 1), ("C6", 1, 1), ("A5", 2, 1), ("F5", 3, 1)],
    [("D5", 0, 2), ("B4", 2, 1), ("D5", 3, 1)],
]
LIFT_OPEN = [("G5", 0, 1), ("C6", 1, 1), ("E6", 2, 2)]
ENDING = [[("C5", 0, 2), ("E5", 2, 2)], [("A5", 0, 2), ("G5", 2, 1), ("F5", 3, 1)],
          [("G5", 0, 2), ("F5", 2, 1), ("D5", 3, 1)], [("E5", 0, 4), ("C6", 4, 4)]]

MEL = {}
for i in range(2, body):
    if i < STRINGS_FROM:
        MEL[i] = PHRASE_A[(i - 2) % len(PHRASE_A)]
    elif LIFT and i >= LIFT:
        k = (i - LIFT) % len(PHRASE_B)
        MEL[i] = LIFT_OPEN if k == 0 else PHRASE_B[k]
    else:
        MEL[i] = PHRASE_B[(i - STRINGS_FROM) % len(PHRASE_B)]
for k, notes in enumerate(ENDING):
    MEL[body + k] = notes

BOX_A = [("E6", 0, 1), ("D6", 1, 1), ("C6", 2, 2)]
BOX_B = [("B5", 0, 1), ("C6", 1, 1), ("D6", 2, 2)]
MUSIC_BOX = {0: BOX_A, 1: BOX_B}
for tm in S.get("music_box_at", [endcard["t0"]] if endcard else []):
    i = slot(tm)
    if 0 <= i < n - 1:
        MUSIC_BOX[i], MUSIC_BOX[i + 1] = BOX_A, BOX_B
if endcard or n - 1 in MUSIC_BOX:
    MUSIC_BOX[n - 2], MUSIC_BOX[n - 1] = BOX_A, [("E6", 2, 3), ("G6", 6, 3)]

events = []
PIANO, BOX, STR, CELLO = 0, 1, 2, 3
CUR = [BASE]


def note(ch, t, dur, pitch, vel):
    t += random.uniform(-0.008, 0.008)
    vel = max(1, min(127, int(vel + random.uniform(-5, 5))))
    events.append((max(0.0, t), ch, "on", pitch + CUR[0], vel))
    events.append((t + dur, ch, "off", pitch + CUR[0], 0))


def cc(ch, t, num, val):
    events.append((t, ch, "cc", num, int(max(0, min(127, val)))))


for i, name in enumerate(PROG):
    t0 = i * BAR
    CUR[0] = transpose(i)
    bass, pcs = CHORDS[name]
    last = i == n - 1
    cc(PIANO, t0 + 0.03, 64, 0)
    cc(PIANO, t0 + 0.06, 64, 127)
    tones = [p for p in range(bass + 5, bass + 26) if p % 12 in pcs][:4]
    if last:  # slow roll, held under the end card
        for k, p in enumerate([bass, bass + 7, bass + 12, bass + 16, bass + 19]):
            note(PIANO, t0 + k * 0.35, END_HOLD, p, DYN[i] - 4)
    elif i in RIPPLE:  # 16ths up and down: time flying by
        run = [bass] + tones + [x + 12 for x in tones[:3]]
        run = run + run[-2:0:-1]
        for k in range(16):
            note(PIANO, t0 + k * BEAT / 4, BEAT * 0.9, run[k % len(run)], DYN[i] - 10 - (4 if k % 2 else 0))
    else:
        for k, p in enumerate([bass] + tones + tones[-2::-1][:3]):
            note(PIANO, t0 + k * BEAT / 2, BEAT * 1.5, p, DYN[i] - (6 if k else 0) - (4 if k % 2 else 0))
    for nm, off, d in MEL.get(i, []):
        note(PIANO, t0 + off * BEAT, d * BEAT * 1.05, N(nm), DYN[i] + 18)
        if i in PEAK:
            note(PIANO, t0 + off * BEAT, d * BEAT, N(nm) - 12, DYN[i])
    for nm, off, d in MUSIC_BOX.get(i, []):
        note(BOX, t0 + off * BEAT, d * BEAT * 1.5, N(nm), 58)
    if i >= STRINGS_FROM:
        hold = END_HOLD if last else BAR + 0.15
        for p in [p for p in range(60, 80) if p % 12 in pcs][:3]:
            note(STR, t0, hold, p, 70)
        note(CELLO, t0, hold, bass if bass >= 36 else bass + 12, 72)

# strings expression follows the dynamics, blooming in on entry and fading under the end
t_in, t_end = STRINGS_FROM * BAR, (n - 1) * BAR
for ch in (STR, CELLO):
    k = 0
    t = t_in
    while t <= D:
        v = 1.55 * dyn_at(t) - 2
        if t < t_in + BAR:
            v = 20 + (v - 20) * (t - t_in) / BAR
        if LIFT and LIFT * BAR - 2 * BAR <= t < LIFT * BAR:
            v += 14 * (t - (LIFT * BAR - 2 * BAR)) / (2 * BAR)  # swell into the key change
        if t > t_end:
            v *= max(0.0, 1 - (t - t_end) / END_HOLD)
        cc(ch, t, 11, v)
        k += 1
        t = t_in + k * 0.25

mid = mido.MidiFile(ticks_per_beat=TPB)
meta = mido.MidiTrack()
meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(BPM), time=0))
mid.tracks.append(meta)
tr = mido.MidiTrack()
mid.tracks.append(tr)
for ch, prog, vol, pan in ((PIANO, 0, 110, 64), (BOX, 10, 70, 76), (STR, 48, 92, 52), (CELLO, 42, 80, 44)):
    tr.append(mido.Message("program_change", channel=ch, program=prog, time=0))
    tr.append(mido.Message("control_change", channel=ch, control=91, value=100, time=0))
    tr.append(mido.Message("control_change", channel=ch, control=7, value=vol, time=0))
    tr.append(mido.Message("control_change", channel=ch, control=10, value=pan, time=0))
for ch in (STR, CELLO):
    tr.append(mido.Message("control_change", channel=ch, control=11, value=0, time=0))
order = {"off": 0, "cc": 1, "on": 2}
events.sort(key=lambda e: (e[0], order[e[2]]))
tps = TPB / BEAT
last_tick = 0
for t, ch, kind, a, b in events:
    tick = int(round(t * tps))
    delta, last_tick = max(0, tick - last_tick), tick
    if kind == "on":
        tr.append(mido.Message("note_on", channel=ch, note=max(0, min(127, a)), velocity=b, time=delta))
    elif kind == "off":
        tr.append(mido.Message("note_off", channel=ch, note=max(0, min(127, a)), velocity=0, time=delta))
    else:
        tr.append(mido.Message("control_change", channel=ch, control=a, value=b, time=delta))
mid.save(HERE / "score.mid")
print(f"score.mid: {n} chords of {BAR:.2f} s, strings from {STRINGS_FROM * BAR:.1f} s"
      + (f", key lift at {LIFT * BAR:.1f} s" if LIFT else "") + f", {D:.1f} s")
if "--midi" in sys.argv:
    sys.exit(0)


def find_soundfont():
    cands = [os.environ.get("SOUNDFONT", ""), "/usr/share/sounds/sf2/FluidR3_GM.sf2", "/usr/share/soundfonts/FluidR3_GM.sf2",
             "/usr/share/soundfonts/default.sf2"]
    cands += glob.glob(str(HERE / "soundfonts" / "*.sf2")) + glob.glob(os.path.expanduser("~/.cache/family-reel/*.sf2"))
    cands += glob.glob("/opt/homebrew/share/soundfonts/*.sf2") + glob.glob("/usr/local/share/soundfonts/*.sf2")
    return next((c for c in cands if c and os.path.exists(c)), None)


raw = HERE / "out" / "score_raw.wav"
raw.parent.mkdir(exist_ok=True)
sf2, fs = find_soundfont(), shutil.which("fluidsynth")
if fs and sf2 and os.environ.get("REEL_SYNTH") != "builtin":  # REEL_SYNTH=builtin forces the fallback
    subprocess.run([fs, "-ni", "-g", "0.5", "-r", "48000", "-o", "synth.reverb.room-size=0.85", "-o", "synth.reverb.damp=0.35",
                    "-o", "synth.reverb.width=0.9", "-o", "synth.reverb.level=0.75", "-o", "synth.chorus.active=0",
                    "-F", str(raw), sf2, str(HERE / "score.mid")], check=True, stdout=subprocess.DEVNULL)
    print("rendered with FluidSynth +", os.path.basename(sf2))
else:
    sys.path.insert(0, str(HERE))
    from synth import render
    render(str(HERE / "score.mid"), str(raw), sr=48000)
    print("FluidSynth/soundfont not found: rendered with the built-in synth (install fluidsynth for a richer piano)")

import imageio_ffmpeg
subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
                "-af", f"apad,atrim=0:{D},afade=t=out:st={max(0, D - 3.5)}:d=3.5,loudnorm=I=-16:TP=-1.5:LRA=11",
                "-ar", "48000", str(HERE / "score.wav")], check=True)
print("wrote score.wav")
