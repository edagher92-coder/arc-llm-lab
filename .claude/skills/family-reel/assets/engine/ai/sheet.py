"""Contact sheets for choosing and checking AI images: one sheet per person/prefix.

  python sheet.py            -> sheet_chain_<who>.jpg, sheet_beam_<who>.jpg, sheet_out_<prefix>.jpg
Look at every face at full size too: the eye metric misses subtle problems.
"""
from collections import defaultdict

from PIL import Image, ImageDraw

from common import AI

for folder in ("chain", "beam", "out"):
    groups = defaultdict(list)
    for f in sorted((AI / folder).glob("*.png")):
        groups[f.stem.split("_")[0]].append(f)
    for g, fs in groups.items():
        ims = [Image.open(f) for f in fs]
        tw = 200
        th = int(tw * ims[0].height / ims[0].width)
        cols = 8
        rows = (len(ims) + cols - 1) // cols
        s = Image.new("RGB", (cols * tw, rows * (th + 18)), "white")
        d = ImageDraw.Draw(s)
        for i, (f, im) in enumerate(zip(fs, ims)):
            x, y = (i % cols) * tw, (i // cols) * (th + 18)
            s.paste(im.resize((tw, int(tw * im.height / im.width))), (x, y))
            d.text((x + 3, y + th + 3), f.stem[:30], fill="black")
        s.save(AI / f"sheet_{folder}_{g}.jpg", quality=88)
        print(folder, g, len(fs))
