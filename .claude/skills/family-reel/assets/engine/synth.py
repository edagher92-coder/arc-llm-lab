"""Fallback software synthesiser for family-reel scores.

Renders a small General-MIDI file -- piano + music box melody over sustained
string/cello pads, exactly what compose.py writes -- to a stereo WAV using
only numpy/scipy/mido. Used when FluidSynth and a soundfont are not
installed (e.g. a sandboxed VM with no apt access).

Each note is synthesised from a small, per-(instrument, pitch) band-limited
wavetable played back with a phase accumulator, so a whole score renders in
one vectorised pass per note instead of a per-sample Python loop. A
synthetic convolution reverb glues the mix together.

CLI:
    python synth.py score.mid out.wav [--sr 48000]

Library:
    from synth import render
    seconds = render("score.mid", "out.wav", sr=48000)
"""
import argparse

import mido
import numpy as np
from scipy.io import wavfile
from scipy.signal import fftconvolve, lfilter

TABLE_LEN = 2048   # samples per single-cycle wavetable
SEED = 20260927    # deterministic detune / reverb noise
INSTR_BY_PROGRAM = {0: "piano", 10: "musicbox", 48: "strings", 42: "cello"}
LP_CUTOFF = {"strings": 3000.0, "cello": 2100.0}  # gentle softening filter, Hz

# --------------------------------------------------------------- wavetables --

def midi_to_freq(pitch):
    return 440.0 * 2.0 ** ((pitch - 69) / 12.0)

def harmonic_profile(instr):
    """Relative amplitude of harmonics 1..N for each instrument colour."""
    if instr == "piano":
        bright = [1.0 / h ** 1.1 for h in range(1, 33)]    # attack transient
        mellow = [1.0 / h ** 2.2 for h in range(1, 33)]    # settled tone
        return bright, mellow
    if instr == "musicbox":
        return [1.0, 0.0, 0.15, 0.0, 0.08], None            # fund + 3rd + 5th
    if instr == "cello":
        return [1.0 / h for h in range(1, 13)], None         # darker sawtooth
    return [1.0 / h for h in range(1, 17)], None              # strings, brighter

_wt_cache = {}

def get_table(instr, pitch, sr, layer=0):
    """Cached single-cycle wavetable for (instrument, pitch), band-limited
    to this sample rate so higher notes simply drop the harmonics that
    would alias past Nyquist."""
    key = (instr, pitch, sr, layer)
    tbl = _wt_cache.get(key)
    if tbl is None:
        f0 = midi_to_freq(pitch)
        primary, secondary = harmonic_profile(instr)
        amps = primary if layer == 0 else secondary
        n = np.arange(TABLE_LEN)
        wave = np.zeros(TABLE_LEN)
        nyq = sr / 2.0
        for h, amp in enumerate(amps, start=1):
            if h * f0 >= nyq:
                break
            if amp:
                wave += amp * np.sin(2 * np.pi * h * n / TABLE_LEN)
        peak = np.max(np.abs(wave))
        tbl = (wave / peak if peak > 0 else wave).astype(np.float32)
        _wt_cache[key] = tbl
    return tbl

def wavetable_lookup(table, freq, sr):
    """Phase-accumulator playback: freq is Hz per sample (scalar-broadcast
    or a per-sample array for vibrato). Vectorised, no Python sample loop."""
    phase = np.cumsum(freq) / sr
    phase -= np.floor(phase)
    idx = phase * TABLE_LEN
    i0 = idx.astype(np.int64)
    frac = idx - i0
    i1 = (i0 + 1) % TABLE_LEN
    i0 %= TABLE_LEN
    return table[i0] * (1 - frac) + table[i1] * frac

def smoothstep(u):
    u = np.clip(u, 0.0, 1.0)
    return u * u * (3 - 2 * u)

def pan_gains(cc10):
    """Equal-power pan from a raw CC10 value (0..127)."""
    pos = (cc10 / 127.0) * 2 - 1
    theta = (pos + 1) * (np.pi / 4)
    return np.cos(theta), np.sin(theta)

# ------------------------------------------------------------- MIDI parsing --

def parse_score(path):
    """Returns (notes, programs, volume, pan, expr, total_seconds).
    Handles sustain pedal (CC64): a note-off while the pedal is down on that
    channel is deferred until the next pedal-up."""
    mf = mido.MidiFile(path)
    programs, volume, pan, expr = {}, {}, {}, {}
    pedal_down, held_off, active, notes = {}, {}, {}, []
    t = 0.0

    def finish(key, end_t):
        n = active.pop(key, None)
        if n is None:
            return
        ch, pitch = key
        notes.append(dict(channel=ch, program=programs.get(ch, 0), pitch=pitch,
                           velocity=n["vel"], start=n["start"], end=end_t))

    for msg in mf:
        t += msg.time
        if msg.type == "program_change":
            programs[msg.channel] = msg.program
        elif msg.type == "control_change":
            if msg.control == 7:
                volume[msg.channel] = msg.value
            elif msg.control == 10:
                pan[msg.channel] = msg.value
            elif msg.control == 11:
                expr.setdefault(msg.channel, []).append((t, msg.value))
            elif msg.control == 64:
                down = msg.value >= 64
                was_down = pedal_down.get(msg.channel, False)
                pedal_down[msg.channel] = down
                if was_down and not down:
                    for key in held_off.pop(msg.channel, ()):
                        finish(key, t)
        elif msg.type == "note_on" and msg.velocity > 0:
            key = (msg.channel, msg.note)
            if key in active:
                finish(key, t)  # retrigger without an off: cut the old note
            active[key] = {"start": t, "vel": msg.velocity}
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            key = (msg.channel, msg.note)
            if key not in active:
                continue
            if pedal_down.get(msg.channel, False):
                held_off.setdefault(msg.channel, set()).add(key)
            else:
                finish(key, t)

    for key in list(active):
        finish(key, t)  # anything still ringing at end of file
    return notes, programs, volume, pan, expr, t

def make_expr_fn(events):
    if not events:
        return lambda t_arr: 1.0
    times = np.array([e[0] for e in events])
    vals = np.array([e[1] for e in events]) / 127.0
    return lambda t_arr: np.interp(t_arr, times, vals, left=vals[0], right=vals[-1])

# ---------------------------------------------------------------- per-note --

def render_piano_note(note, sr, rng):
    pitch, vel = note["pitch"], note["velocity"]
    f0 = midi_to_freq(pitch) * (1 + rng.normal(0, 0.0008))
    dur_on = max(note["end"] - note["start"], 0.03)
    tau_slow = float(np.clip(3.2 * 2 ** (-(pitch - 60) / 26), 0.5, 5.5))
    tau_fast = tau_slow / 7.0
    release = float(np.clip(0.30 - 0.10 * (vel / 127), 0.15, 0.30))
    n = int((dur_on + release + 0.05) * sr)
    t = np.arange(n) / sr
    attack = np.clip(t / 0.005, 0, 1)
    gate = np.where(t <= dur_on, 1.0, np.clip(1 - (t - dur_on) / release, 0, 1))
    freq = np.full(n, f0)
    w_bright = 0.10 + 0.30 * (vel / 127)
    y = wavetable_lookup(get_table("piano", pitch, sr, 1), freq, sr) * attack * np.exp(-t / tau_slow) * gate
    y += w_bright * wavetable_lookup(get_table("piano", pitch, sr, 0), freq, sr) * attack * np.exp(-t / tau_fast) * gate
    return (y * (vel / 127) ** 1.3).astype(np.float32)

def render_musicbox_note(note, sr, rng):
    pitch, vel = note["pitch"], note["velocity"]
    f0 = midi_to_freq(pitch) * (1 + rng.normal(0, 0.001))
    tau = 0.8 + 0.4 * rng.random()
    dur_on = max(note["end"] - note["start"], 0.02)
    release = 0.15
    n = int(max(dur_on + release, tau * 4) * sr)
    t = np.arange(n) / sr
    attack = np.clip(t / 0.003, 0, 1)
    gate = np.where(t <= dur_on, 1.0, np.clip(1 - (t - dur_on) / release, 0, 1))
    y = wavetable_lookup(get_table("musicbox", pitch, sr), np.full(n, f0), sr) * attack * np.exp(-t / tau) * gate
    return (y * (vel / 127) ** 1.1).astype(np.float32)

def render_pad_note(note, sr, rng):
    pitch, vel, instr = note["pitch"], note["velocity"], note["instr"]
    f0 = midi_to_freq(pitch) * (1 + rng.normal(0, 0.0012))
    attack_t = 0.30 + 0.08 * rng.random()
    release_t = 0.40 + 0.15 * rng.random()
    dur_on = max(note["end"] - note["start"], attack_t + 0.05)
    n = int((dur_on + release_t + 0.05) * sr)
    t = np.arange(n) / sr
    env = smoothstep(t / attack_t) * (1.0 - smoothstep((t - dur_on) / release_t))
    vibrato = 1.0 + 0.003 * smoothstep((t - 0.3) / 0.2) * np.sin(2 * np.pi * 5.0 * t)
    y = wavetable_lookup(get_table(instr, pitch, sr), f0 * vibrato, sr) * env
    alpha = 1 - np.exp(-2 * np.pi * LP_CUTOFF[instr] / sr)
    y = lfilter([alpha], [1, -(1 - alpha)], y)
    return (y * (vel / 127)).astype(np.float32)

# ------------------------------------------------------------------ reverb --

def make_reverb_ir(sr, rt60=2.3, predelay=0.02):
    """Synthetic stereo IR: decorrelated exponentially-decaying noise, with
    a darker (low-passed) tail and a short pre-delay."""
    n = int(rt60 * sr)
    t = np.arange(n) / sr
    decay = np.exp(-t * (6.9 / rt60))  # -60 dB at rt60
    rng = np.random.default_rng(SEED + 1)
    alpha = 1 - np.exp(-2 * np.pi * 4000 / sr)
    pre = int(predelay * sr)
    irs = []
    for _ in range(2):
        noise = lfilter([alpha], [1, -(1 - alpha)], rng.standard_normal(n))
        ir = np.concatenate([np.zeros(pre), noise * decay])[:n]
        energy = np.sqrt(np.sum(ir ** 2)) or 1.0
        irs.append((ir / energy).astype(np.float32))
    return irs[0], irs[1]

def add_reverb(left, right, sr, wet=0.25):
    ir_l, ir_r = make_reverb_ir(sr)
    wet_l = fftconvolve(left, ir_l)[: left.size]
    wet_r = fftconvolve(right, ir_r)[: right.size]
    return left + wet * wet_l, right + wet * wet_r

# ----------------------------------------------------------------- render --

def render(midi_path, wav_path, sr=48000):
    notes, programs, volume, pan, expr, total_t = parse_score(midi_path)
    for note in notes:
        note["instr"] = INSTR_BY_PROGRAM.get(note["program"], "strings")
    notes.sort(key=lambda n: (n["start"], n["channel"], n["pitch"]))  # deterministic rng draw order

    expr_fn = {ch: make_expr_fn(evs) for ch, evs in expr.items()}
    chan_vol = {ch: v / 127.0 for ch, v in volume.items()}
    chan_pan = {ch: pan_gains(pan.get(ch, 64)) for ch in {n["channel"] for n in notes}}

    n_total = int((total_t + 4.0) * sr) + 1   # 4 s tail for releases + reverb
    out_l = np.zeros(n_total, dtype=np.float64)
    out_r = np.zeros(n_total, dtype=np.float64)
    rng = np.random.default_rng(SEED)

    for note in notes:
        instr = note["instr"]
        if instr == "piano":
            y = render_piano_note(note, sr, rng)
        elif instr == "musicbox":
            y = render_musicbox_note(note, sr, rng)
        else:
            y = render_pad_note(note, sr, rng)

        ch = note["channel"]
        if ch in expr_fn:
            y = y * expr_fn[ch](note["start"] + np.arange(y.size) / sr)
        y = y * chan_vol.get(ch, 1.0)

        start_i = int(note["start"] * sr)
        end_i = min(start_i + y.size, n_total)
        y = y[: end_i - start_i]
        lg, rg = chan_pan.get(ch, (0.7071, 0.7071))
        out_l[start_i:end_i] += y * lg
        out_r[start_i:end_i] += y * rg

    out_l, out_r = add_reverb(out_l, out_r, sr)
    stereo = np.stack([out_l, out_r], axis=1)
    peak = np.max(np.abs(stereo))
    if peak > 0:
        stereo *= (10 ** (-1 / 20)) / peak  # normalise to -1 dBFS peak
    pcm = np.clip(np.round(stereo * 32767), -32768, 32767).astype(np.int16)
    wavfile.write(wav_path, sr, pcm)
    return n_total / sr

def main():
    ap = argparse.ArgumentParser(description="Render a MIDI score to WAV without FluidSynth.")
    ap.add_argument("midi_path")
    ap.add_argument("wav_path")
    ap.add_argument("--sr", type=int, default=48000)
    args = ap.parse_args()
    seconds = render(args.midi_path, args.wav_path, sr=args.sr)
    print(f"wrote {args.wav_path}: {seconds:.2f}s @ {args.sr} Hz")

if __name__ == "__main__":
    main()
