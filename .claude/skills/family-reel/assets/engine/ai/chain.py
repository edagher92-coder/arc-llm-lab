"""Ageing chain: a real face crop -> 3D-animated portrait at the first age -> each next age
from the previous one (img2img), so the portraits share a composition and crossfade like a
morph. Identity is carried by the init image plus a light IP-Adapter FaceID nudge.

  python chain.py chain.json
chain.json: {"child": {"src": "IMG_3.jpg", "pick_x": null, "scale": 1.9, "emb": "child",
                       "id": 0.35, "beam": [7, 11, 23], "steps": [
                         {"tag": "01", "strength": 0.6, "prompt": "close-up portrait of a cute 1 year old baby girl, ..."},
                         {"tag": "05", "strength": 0.55, "prompt": "..."}]},
             "dad": {..., "steps": [{"tag": "45", "strength": 0.5, "from": "chain/dad_38.png", "prompt": "..."}]}}
  beam: seeds tried per step; the one with the best eye score wins (stops early when < "good", default 0.035).
  from: derive this age from a known-good anchor image instead of the previous step (stops drift for adults).
Writes chain/<who>_today.png and chain/<who>_<tag>.png; every candidate is kept in beam/.
"""
import json
import os
import sys
import time

import cv2
import numpy as np
import torch
from diffusers import LCMScheduler, StableDiffusionImg2ImgPipeline
from insightface.model_zoo import get_model
from PIL import Image

from common import AI, THREADS, load_photo, model
from eyeqa import eye_score

torch.set_num_threads(THREADS)
pipe = StableDiffusionImg2ImgPipeline.from_pretrained(str(model("pixar-lcm")), safety_checker=None, requires_safety_checker=False,
                                                      torch_dtype=torch.float32)
pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
pipe.load_ip_adapter(str(model("faceid")), subfolder=None, weight_name="ip-adapter-faceid_sd15.bin", image_encoder_folder=None)
pipe.set_progress_bar_config(disable=True)
det = get_model(str(model("buffalo_l") / "detection" / "model.onnx"), providers=["CPUExecutionProvider"])
det.prepare(ctx_id=-1, det_size=(640, 640))
STYLE = "3d pixar style animated film still, cinematic lighting"  # first: CLIP truncates prompts at 77 tokens
NEG = "cross-eyed, lazy eye, strabismus, looking sideways, asymmetrical eyes, mismatched eyes, blemish, spot, mark on face, deformed, blurry"


def face_crop(src, pick_x=None, scale=2.1, lift=0.12, box=None):
    im = load_photo(src)
    if box:  # manual box as fractions [x0, y0, x1, y1]
        return im.crop(tuple(int(v * s) for v, s in zip(box, (im.width, im.height) * 2))).resize((512, 512), Image.LANCZOS)
    bgr = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
    s = 1600 / max(im.size)
    small = cv2.resize(bgr, None, fx=s, fy=s)
    b, _ = det.detect(small, max_num=0, metric="default")
    if len(b) == 0:
        raise SystemExit(f"no face found in {src}: give a 'box'")
    if pick_x is None:
        i = int(np.argmax((b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])))
    else:
        i = int(np.argmin(np.abs((b[:, 0] + b[:, 2]) / 2 / small.shape[1] - pick_x)))
    x0, y0, x1, y1 = b[i, :4] / s
    cx, cy, size = (x0 + x1) / 2, (y0 + y1) / 2 + (y1 - y0) * lift, max(x1 - x0, y1 - y0) * scale
    size = min(size, im.width, im.height)  # keep the crop inside the photo (no black borders)
    x0 = min(max(cx - size / 2, 0), im.width - size)
    y0 = min(max(cy - size / 2, 0), im.height - size)
    return im.crop((int(x0), int(y0), int(x0 + size), int(y0 + size))).resize((512, 512), Image.LANCZOS)


cfg = json.load(open(sys.argv[1] if len(sys.argv) > 1 else AI / "chain.json"))
os.chdir(AI)
os.makedirs("chain", exist_ok=True)
os.makedirs("beam", exist_ok=True)
for who, c in cfg.items():
    emb_file = f"emb_{c.get('emb', who)}.npy"
    emb = torch.from_numpy(np.load(emb_file)).float().view(1, 1, 1, 512) if os.path.exists(emb_file) else torch.zeros(1, 1, 1, 512)
    if not os.path.exists(emb_file):
        print(f"note: {emb_file} missing (run faces.py); identity comes from the photo alone")
    prev = face_crop(c["src"], c.get("pick_x"), c.get("scale", 2.1), box=c.get("box"))
    prev.save(f"chain/{who}_today.png")
    for step in c["steps"]:
        f = f"chain/{who}_{step['tag']}.png"
        if os.path.exists(f):  # resumable: delete a file to regenerate it
            prev = Image.open(f)
            continue
        if step.get("from"):
            prev = Image.open(step["from"]).convert("RGB")
        pipe.set_ip_adapter_scale(step.get("id", c.get("id", 0.5)))
        t = time.time()
        cfg_s = c.get("cfg", 1.5)
        embeds = torch.cat([torch.zeros_like(emb), emb]) if cfg_s > 1 else emb
        best = None
        for sd in step.get("beam", c.get("beam", [c.get("seed", 7)])):
            cand = pipe(prompt=f"{STYLE}, {step['prompt']}", negative_prompt=NEG if cfg_s > 1 else None, image=prev,
                        strength=step["strength"], num_inference_steps=step.get("steps", 8), guidance_scale=cfg_s,
                        ip_adapter_image_embeds=[embeds], generator=torch.Generator().manual_seed(sd)).images[0]
            score = eye_score(cand)[0] if c.get("eyes", True) else 0.0
            cand.save(f"beam/{who}_{step['tag']}_s{sd}_{score:.3f}.png")
            if best is None or score < best[0]:
                best = (score, cand, sd)
            if score < c.get("good", 0.035):
                break
        best[1].save(f)
        prev = best[1]
        print(f"{f}  seed {best[2]}  eyes {best[0]:.3f}  {time.time() - t:.0f}s", flush=True)
