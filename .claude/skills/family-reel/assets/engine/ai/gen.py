"""Text-to-image scenes in the same 3D-animated style, optionally nudged towards a person's identity.
Use sparingly: multi-person scenes lose likeness and AI-aged pets look uncanny. Prefer real photos.

  python gen.py jobs.json
jobs.json: [{"id": "s_firststeps", "prompt": "...", "who": "child" | null, "scale": 0.7, "seeds": [1, 2, 3],
             "w": 512, "h": 896, "steps": 6, "cfg": 1.0}]
Writes out/<id>_s<seed>.png; pick the best seed into sel.json ({"s_firststeps": 2}) for finalize.py.
"""
import json
import os
import sys
import time

import numpy as np
import torch
from diffusers import LCMScheduler, StableDiffusionPipeline

from common import AI, THREADS, model

torch.set_num_threads(THREADS)
pipe = StableDiffusionPipeline.from_pretrained(str(model("pixar-lcm")), safety_checker=None, requires_safety_checker=False,
                                               torch_dtype=torch.float32)
pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
pipe.load_ip_adapter(str(model("faceid")), subfolder=None, weight_name="ip-adapter-faceid_sd15.bin", image_encoder_folder=None)
pipe.set_progress_bar_config(disable=True)
NEG = "blurry, deformed, disfigured, bad anatomy, extra fingers, extra limbs, text, watermark, lowres, ugly, creepy, realistic photo"
STYLE = "3d pixar style animated film still, cinematic lighting"
_emb = {}


def emb(who):
    if who not in _emb:
        _emb[who] = torch.from_numpy(np.load(AI / f"emb_{who}.npy")).float()
    return _emb[who]


jobs = json.load(open(sys.argv[1]))
os.makedirs(AI / "out", exist_ok=True)
for j in jobs:
    who, cfg = j.get("who"), j.get("cfg", 1.0)
    pos = (emb(who) if who else torch.zeros(512)).view(1, 1, 1, 512)
    embeds = torch.cat([torch.zeros_like(pos), pos]) if cfg > 1 else pos
    pipe.set_ip_adapter_scale(j.get("scale", 0.7) if who else 0.0)
    for seed in j["seeds"]:
        f = AI / "out" / f"{j['id']}_s{seed}.png"
        if f.exists():
            continue
        t = time.time()
        img = pipe(prompt=f"{STYLE}, {j['prompt']}", negative_prompt=NEG if cfg > 1 else None,
                   ip_adapter_image_embeds=[embeds], num_inference_steps=j.get("steps", 6), guidance_scale=cfg,
                   width=j.get("w", 512), height=j.get("h", 896), generator=torch.Generator().manual_seed(seed)).images[0]
        img.save(f)
        print(f"{f.name} {time.time() - t:.0f}s", flush=True)
