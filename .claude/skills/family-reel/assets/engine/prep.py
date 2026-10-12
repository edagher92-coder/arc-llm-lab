"""Prepare reel assets from the user's photos and videos, driven by scenes.json.

  python prep.py [uploads_dir]          (default: $UPLOADS_DIR or ./uploads)

- photos:  EXIF-orient, optional rotate, privacy blurs, downsize (max 2400 px) -> assets/<name>.jpg
- cards:   square face cards for the end card (optionally "whitened" for drawn/printed art) -> assets/cards/
- videos:  trimmed, slowed, cropped 30 fps JPEG sequences at the reel size -> assets/vid/<name>/
- sprites: a short clip of a pet/toy on a plain background keyed to transparent PNGs -> assets/sprites/<name>/
- out/crop_preview.jpg: first and last Ken Burns frame of every photo shot, to check framing before rendering

Coordinates (blur boxes, card boxes, Ken Burns from/to) are fractions of the photo
(0..1) unless the photo sets "disp": [w, h], in which case they are in that pixel space.
"""
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

try:  # iPhone photos arrive as HEIC
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

HERE = Path(__file__).parent
UP = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("UPLOADS_DIR", HERE / "uploads"))
A = HERE / "assets"
OUT = HERE / "out"
for d in (A, OUT):
    d.mkdir(parents=True, exist_ok=True)
cfg = json.loads((HERE / "scenes.json").read_text())
W, H, FPS = cfg.get("width", 1080), cfg.get("height", 1920), cfg.get("fps", 30)
MAX = 2400


def resolve(name):
    """Find an upload by exact name, by Claude upload id (<id>-image.jpg), or by prefix."""
    p = Path(name)
    if p.is_absolute() and p.exists():
        return p
    for c in (UP / name, HERE / name, UP / f"{name}-image.jpg"):
        if c.exists():
            return c
    hits = sorted(UP.glob(f"{name}*"))
    if hits:
        return hits[0]
    sys.exit(f"missing upload: {name} (looked in {UP})")


def load(name, rotate=0):
    im = ImageOps.exif_transpose(Image.open(resolve(name))).convert("RGB")
    return im.rotate(-rotate, expand=True) if rotate else im


def to_px(im, disp, box):
    sx, sy = im.width / disp[0], im.height / disp[1]
    return tuple(int(round(v * s)) for v, s in zip(box, (sx, sy, sx, sy)))


def blur_box(im, disp, box):
    b = to_px(im, disp, box)
    radius = max(12, int(max(im.size) / 60))
    im.paste(im.crop(b).filter(ImageFilter.GaussianBlur(radius)), b)


def whiten(c):
    """Per-channel levels from the bright percentile: turns paper white so it sits on the paper end card."""
    bands = []
    for band in c.split():
        hist, total, acc, hi = band.histogram(), c.width * c.height, 0, 255
        for v in range(255, -1, -1):
            acc += hist[v]
            if acc > total * 0.35:
                hi = v
                break
        lo = 12
        bands.append(band.point([max(0, min(255, int((v - lo) * 255 / max(1, hi - lo)))) for v in range(256)]))
    return Image.merge("RGB", bands)


# ---- photos ----
for name, p in cfg.get("photos", {}).items():
    if "gen" in p or "chain" in p:
        continue  # AI stills are written by ai/finalize.py
    im = load(p["file"], p.get("rotate", 0))
    disp = p.get("disp", [1, 1])
    for box in p.get("blur", []):
        blur_box(im, disp, box)
    im.thumbnail((MAX, MAX), Image.LANCZOS)
    im.save(A / f"{name}.jpg", quality=92)
    print("photo", name, im.size, f"({len(p.get('blur', []))} blurred areas)" if p.get("blur") else "")

# ---- end-card face cards ----
if cfg.get("cards"):
    (A / "cards").mkdir(exist_ok=True)
for key, c in cfg.get("cards", {}).items():
    im = load(c["file"], c.get("rotate", 0))
    disp = c.get("disp", [1, 1])
    for patch in c.get("patch", []):  # paint over something poking into the circle, using the colour just left of it
        b = to_px(im, disp, patch)
        ImageDraw.Draw(im).rectangle(b, fill=im.getpixel((max(0, b[0] - 4), b[1])))
    x0, y0, x1, y1 = to_px(im, disp, c["box"])
    side = max(x1 - x0, y1 - y0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    crop = im.crop((int(cx - side / 2), int(cy - side / 2), int(cx + side / 2), int(cy + side / 2)))
    if c.get("whiten"):
        crop = whiten(crop.filter(ImageFilter.GaussianBlur(2.2)))
    crop.resize((700, 700), Image.LANCZOS).save(A / "cards" / f"{key}.jpg", quality=94)
    print("card", key)
if cfg.get("cards"):  # check every card is a well-centred face before rendering
    keys = list(cfg["cards"])
    cs = Image.new("RGB", (240 * len(keys), 270), "#f3e6d2")
    dc = ImageDraw.Draw(cs)
    for i, key in enumerate(keys):
        cs.paste(Image.open(A / "cards" / f"{key}.jpg").resize((220, 220)), (i * 240 + 10, 10))
        dc.text((i * 240 + 12, 240), key, fill="black")
    cs.save(OUT / "cards_preview.jpg", quality=85)
    print("wrote out/cards_preview.jpg")

# ---- crop preview sheet (check every Ken Burns frame before rendering) ----
shots = [s for s in cfg.get("shots", []) if s.get("photo") and not s.get("fit") and (A / f"{s['photo']}.jpg").exists()]
if shots:
    TW, TH = 216, int(216 * H / W)
    sheet = Image.new("RGB", (TW * len(shots), TH * 2 + 30), "black")
    d = ImageDraw.Draw(sheet)
    for i, s in enumerate(shots):
        p = cfg["photos"][s["photo"]]
        disp = p.get("disp", [1, 1])
        im = Image.open(A / f"{s['photo']}.jpg")
        frm = s.get("from", [disp[0] / 2, disp[1] / 2, disp[1]])
        for row, key in enumerate(("from", "to")):
            cx, cy, fh = s.get(key, frm)
            k = im.height / disp[1]
            w = min(fh * k * W / H, im.width)
            h = w * H / W
            x = min(max(cx * im.width / disp[0] - w / 2, 0), im.width - w)
            y = min(max(cy * k - h / 2, 0), im.height - h)
            sheet.paste(im.crop((int(x), int(y), int(x + w), int(y + h))).resize((TW, TH)), (i * TW, row * TH))
        d.text((i * TW + 4, TH * 2 + 8), s["photo"][:28], fill="white")
    sheet.save(OUT / "crop_preview.jpg", quality=85)
    print("wrote out/crop_preview.jpg")

# ---- video snippets -> JPEG sequences at the reel size ----
if cfg.get("videos"):
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    for vname, v in cfg["videos"].items():
        uses = [s for s in cfg.get("shots", []) if s.get("video") == vname]
        if not uses:
            continue
        n = max(math.ceil((s["t1"] - s["t0"]) * FPS) + 2 for s in uses)
        out = A / "vid" / vname
        out.mkdir(parents=True, exist_ok=True)
        for old in out.glob("*.jpg"):
            old.unlink()
        vf = [f"setpts=(PTS-STARTPTS)/{v.get('speed', 1.0)}", f"fps={FPS}"]
        if v.get("crop"):
            vf.append(f"crop={v['crop']}")
        # cover-crop to the reel's aspect, then scale
        vf += [f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos", f"crop={W}:{H}", "unsharp=5:5:0.5"]
        subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", str(v.get("ss", 0)), "-i", str(resolve(v["src"])),
                        "-vf", ",".join(vf), "-frames:v", str(n), "-q:v", "3", str(out / "%04d.jpg")], check=True)
        got = len(list(out.glob("*.jpg")))
        (out / "count.txt").write_text(str(got))
        print("video", vname, "frames", got, "needed", n, "" if got >= n - 2 else "  <- clip too short: lower ss/speed or shorten the shot")

# ---- sprites: a pet/toy clip on a plain background -> keyed PNG frames ----
if cfg.get("sprites"):
    import imageio_ffmpeg
    import numpy as np
    from scipy import ndimage
    for sname, sp in cfg["sprites"].items():
        out = A / "sprites" / sname
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        src = resolve(sp["src"])
        frames = []
        if src.is_dir():  # already-transparent PNGs
            frames = [Image.open(f).convert("RGBA") for f in sorted(src.glob("*.png"))]
        else:
            reader = imageio_ffmpeg.read_frames(str(src), output_params=["-vf", f"fps={sp.get('fps', 12)}"])
            meta = next(reader)
            fw, fh = meta["size"]
            for i, raw in enumerate(reader):
                if i >= sp.get("max_frames", 120):
                    break
                f = np.frombuffer(raw, dtype=np.uint8).reshape(fh, fw, 3).astype(np.float32)
                border = np.concatenate([f[0], f[-1], f[:, 0], f[:, -1]])
                bg = np.median(border, axis=0) if sp.get("bg", "auto") == "auto" else np.array(sp["bg"], np.float32)
                d = np.linalg.norm(f - bg, axis=2)
                near = d < sp.get("tol", 9)
                lab, _ = ndimage.label(near)
                # only background connected to the frame edge is removed, so white chests/eyes stay
                edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
                exterior = np.isin(lab, edge[edge > 0])
                band = ndimage.binary_dilation(exterior, iterations=2) & ~exterior
                alpha = np.ones((fh, fw), np.float32)
                alpha[exterior] = 0
                alpha[band] = np.clip((d[band] - 4) / 60, 0, 1)
                a3 = np.maximum(alpha[..., None], 1e-3)
                rgb = np.where(band[..., None], np.clip((f - (1 - a3) * bg) / a3, 0, 255), f)  # remove the light halo
                frames.append(Image.fromarray(np.dstack([rgb, alpha * 255]).astype(np.uint8), "RGBA"))
        hmax = sp.get("height", 480)
        for i, fr in enumerate(frames):
            bbox = fr.getbbox() if sp.get("trim", False) else None
            fr = fr.crop(bbox) if bbox else fr
            if fr.height > hmax:
                fr = fr.resize((int(fr.width * hmax / fr.height), hmax), Image.LANCZOS)
            fr.save(out / f"{i:03d}.png")
        (out / "count.txt").write_text(str(len(frames)))
        print("sprite", sname, "frames", len(frames))
        if frames:  # keying check on light and dark grounds
            picks = [frames[int(k * (len(frames) - 1) / 5)] for k in range(6)] if len(frames) >= 6 else frames
            pw, ph = picks[0].size
            pv = Image.new("RGB", (pw * len(picks), ph * 2), "#f3e6d2")
            pv.paste(Image.new("RGB", (pw * len(picks), ph), "#20150c"), (0, ph))
            for k, fr in enumerate(picks):
                fr = fr.resize((pw, ph))
                pv.paste(fr, (k * pw, 0), fr)
                pv.paste(fr, (k * pw, ph), fr)
            pv.save(OUT / f"sprite_{sname}_preview.jpg", quality=85)
print("prep done")
