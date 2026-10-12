"""Collect AI images into the reel's assets.

1. Ageing portraits: chain/<who>_<tag>.png -> assets/age/<who>_<tag>.jpg (600 px; small magenta
   blemishes the IP-Adapter leaves on faces are inpainted). Reference them from scenes.json ageing steps.
2. Full-screen stills: photos with {"chain": "<who>_<tag>"} (Real-ESRGAN x4) or {"gen": "<job id>"}
   (the seed chosen in sel.json, x2) -> assets/<name>.jpg

  python finalize.py
"""
import json

import cv2
import numpy as np
import torch
from PIL import Image

from common import AI, ASSETS, PROJECT, THREADS, model

torch.set_num_threads(THREADS)
cfg = json.loads((PROJECT / "scenes.json").read_text())
(ASSETS / "age").mkdir(parents=True, exist_ok=True)


def demagenta(img):
    """Inpaint small magenta blobs on the upper face (not clothing); cheeks and lips stay rosy."""
    a = np.asarray(img.convert("RGB"))
    hsv = cv2.cvtColor(a, cv2.COLOR_RGB2HSV)
    h, s, v = (hsv[..., i].astype(int) for i in range(3))
    keep = np.zeros(a.shape[:2], np.uint8)
    for m, ymax in ((((h >= 140) & (h <= 172) & (s > 90) & (v > 90)), 0.65),
                    ((((h >= 165) | (h <= 4)) & (s > 110) & (v > 120)), 0.35)):
        n, lab, stats, cent = cv2.connectedComponentsWithStats(m.astype(np.uint8))
        for i in range(1, n):
            if 8 <= stats[i, 4] <= 800 and cent[i][1] < a.shape[0] * ymax:
                keep[lab == i] = 255
    if not keep.any():
        return img, 0
    keep = cv2.dilate(keep, np.ones((5, 5), np.uint8), iterations=2)
    out = cv2.inpaint(cv2.cvtColor(a, cv2.COLOR_RGB2BGR), keep, 7, cv2.INPAINT_TELEA)
    return Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)), int((keep > 0).sum())


for f in sorted((AI / "chain").glob("*.png")):
    img = Image.open(f).convert("RGB")
    if not f.stem.endswith("_today"):
        img, fixed = demagenta(img)
        if fixed:
            print("  cleaned blemish", f.name, fixed, "px")
    img.resize((600, 600), Image.LANCZOS).save(ASSETS / "age" / f"{f.stem}.jpg", quality=94)
print("ageing portraits:", len(list((ASSETS / "age").glob("*.jpg"))), "-> assets/age/")

_up = {}


def upscale(img, scale):
    import spandrel
    if scale not in _up:
        f = model("esrgan_x2") / "diffusion_pytorch_model.safetensors" if scale == 2 else model("esrgan") / "RealESRGAN_x4plus.safetensors"
        _up[scale] = spandrel.ModelLoader().load_from_file(str(f)).eval()
    x = torch.from_numpy(np.asarray(img.convert("RGB"), dtype=np.float32) / 255).permute(2, 0, 1)[None]
    with torch.no_grad():
        y = _up[scale](x).clamp(0, 1)[0].permute(1, 2, 0).numpy()
    return Image.fromarray((y * 255).round().astype(np.uint8))


sel_file = AI / "sel.json"
sel = json.loads(sel_file.read_text()) if sel_file.exists() else {}
for name, p in cfg.get("photos", {}).items():
    if "gen" in p:
        src = AI / "out" / f"{p['gen']}_s{sel[p['gen']]}.png"
        out = upscale(Image.open(src), 2)
    elif "chain" in p:
        src = AI / "chain" / f"{p['chain']}.png"
        out = upscale(demagenta(Image.open(src).convert("RGB"))[0], 4)
    else:
        continue
    out.save(ASSETS / f"{name}.jpg", quality=94)
    print("still", name, "<-", src.name, out.size)
