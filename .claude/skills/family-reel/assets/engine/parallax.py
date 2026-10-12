"""Pre-render 2.5D depth-parallax shots to JPEG sequences at the reel's fps.

For every photo shot with a "depth" amount, the Ken Burns frame drifts while each
pixel is displaced by its Depth Anything depth (near things move more than far
things), so a still reads like a small camera move. Same maths as the WebGL
fallback in reel.js, but on all CPU cores, which is far faster than software WebGL.

Needs assets/depth/<photo>.png + depth.json from ai/depth.py. Shots without a depth
map simply render as flat Ken Burns moves.
"""
import json
import math
import os
from multiprocessing import Pool
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).parent
A = HERE / "assets"
cfg = json.loads((HERE / "scenes.json").read_text())
W, H, FPS = cfg.get("width", 1080), cfg.get("height", 1920), cfg.get("fps", 30)
META_FILE = A / "depth" / "depth.json"
meta = json.loads(META_FILE.read_text()) if META_FILE.exists() else {}


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return -(math.cos(math.pi * x) - 1) / 2


def render_shot(s):
    name = s["photo"]
    img = cv2.imread(str(A / f"{name}.jpg"))
    dep = cv2.imread(str(A / "depth" / f"{name}.png"), cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255
    ih, iw = img.shape[:2]
    dh, dw = dep.shape
    disp = cfg["photos"][name].get("disp", [1, 1])  # default: coordinates are fractions of the photo
    kx, ky = iw / disp[0], ih / disp[1]
    focus = meta[name]["focus"]
    dirx, diry = s.get("pan", [1, 0.25])
    frm = s.get("from", [disp[0] / 2, disp[1] / 2, disp[1]])
    to = s.get("to", frm)
    n = math.ceil((s["t1"] - s["t0"]) * FPS) + 1
    out = A / "par" / name
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.jpg"):
        old.unlink()
    gx, gy = np.meshgrid((np.arange(W, dtype=np.float32) + 0.5) / W, (np.arange(H, dtype=np.float32) + 0.5) / H)
    for i in range(n):
        t = s["t0"] + i / FPS
        u = ease((t - s["t0"]) / (s["t1"] - s["t0"]))
        cx = frm[0] + (to[0] - frm[0]) * u
        cy = frm[1] + (to[1] - frm[1]) * u
        fh = frm[2] * (to[2] / frm[2]) ** u                 # constant-rate zoom
        w = min(fh * ky * W / H, iw)
        h = w * H / W
        x = min(max(cx * kx - w / 2, 0), iw - w)
        y = min(max(cy * ky - h / 2, 0), ih - h)
        m = (u - 0.5) * 2 * s["depth"]
        camx, camy = dirx * m, diry * m
        sx, sy = x + gx * w, y + gy * h                      # source pixel coords
        ox = np.zeros_like(sx)
        oy = np.zeros_like(sy)
        for _ in range(3):                                   # same 3-step refinement as the shader
            d = cv2.remap(dep, (sx - ox) * (dw / iw), (sy - oy) * (dh / ih), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            ox = (d - focus) * camx * w
            oy = (d - focus) * camy * h
        fx = np.clip(sx - ox, 0, iw - 1)
        fy = np.clip(sy - oy, 0, ih - 1)
        frame = cv2.remap(img, fx, fy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        cv2.imwrite(str(out / f"{i + 1:04d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
    (out / "count.txt").write_text(str(n))
    return name, n


if __name__ == "__main__":
    shots = [s for s in cfg["shots"] if s.get("photo") and s.get("depth") and not s.get("fit") and s["photo"] in meta]
    skipped = [s["photo"] for s in cfg["shots"] if s.get("photo") and s.get("depth") and s["photo"] not in meta]
    if skipped:
        print("no depth map (run ai/depth.py), rendering flat:", ", ".join(sorted(set(skipped))))
    cv2.setNumThreads(1)
    with Pool(max(1, (os.cpu_count() or 2) - 0)) as pool:
        for name, n in pool.imap_unordered(render_shot, shots):
            print("parallax", name, n, "frames", flush=True)
