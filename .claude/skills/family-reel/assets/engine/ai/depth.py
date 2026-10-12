"""Depth maps (Depth Anything V2 Base, local) for every photo shot with a "depth" amount,
used by parallax.py for the 2.5D camera moves. Run after prep.py (and finalize.py if AI
stills are used), then run parallax.py.

  python depth.py   -> assets/depth/<photo>.png + depth.json (focus = depth that stays still)
"""
import json

import numpy as np
import torch
from PIL import Image, ImageFilter
from transformers import pipeline

from common import ASSETS, PROJECT, THREADS, model

torch.set_num_threads(THREADS)
cfg = json.loads((PROJECT / "scenes.json").read_text())
(ASSETS / "depth").mkdir(parents=True, exist_ok=True)
est = pipeline("depth-estimation", model=str(model("depth-base")), device=-1)
meta = {}
for s in cfg.get("shots", []):
    name = s.get("photo")
    if not name or not s.get("depth") or s.get("fit") or name in meta:
        continue
    im = Image.open(ASSETS / f"{name}.jpg").convert("RGB")
    small = im.copy()
    small.thumbnail((768, 768))
    d = np.asarray(est(small)["predicted_depth"].squeeze().float().numpy(), dtype=np.float32)
    lo, hi = np.percentile(d, 2), np.percentile(d, 98)
    d = np.clip((d - lo) / max(hi - lo, 1e-6), 0, 1)  # 1 = near
    dm = Image.fromarray((d * 255).astype(np.uint8)).resize(small.size, Image.BILINEAR)
    dm = dm.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(4))  # grow foreground edges, soften seams
    dm.save(ASSETS / "depth" / f"{name}.png")
    arr = np.asarray(dm, dtype=np.float32) / 255
    h, w = arr.shape
    meta[name] = {"focus": round(float(np.percentile(arr[int(h * .3):int(h * .7), int(w * .3):int(w * .7)], 65)), 3)}
    print("depth", name, meta[name])
(ASSETS / "depth" / "depth.json").write_text(json.dumps(meta, indent=1))
