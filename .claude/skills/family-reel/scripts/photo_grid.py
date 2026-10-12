"""Overlay a labelled 0-1 coordinate grid on photos so crop boxes, blur boxes and Ken Burns
centres can be read straight off the image (look at the output with an image viewer / Read tool).
When the AI tier's face detector is installed, detected faces are boxed and printed as fractions,
with a suggested square card box for each.

  python photo_grid.py uploads/IMG_0001.jpg uploads/IMG_0002.HEIC ...   -> out/grid/<name>.jpg
  python photo_grid.py uploads/                                            (every photo in the folder)
"""
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

MODELS = Path(os.environ.get("MODELS_DIR", Path.home() / ".cache" / "family-reel" / "models"))
EXTS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}


def face_detector():
    """SCRFD from the AI tier (buffalo_l), if installed; otherwise None."""
    det_file = MODELS / "buffalo_l" / "detection" / "model.onnx"
    if not det_file.exists():
        return None
    try:
        from insightface.model_zoo import get_model
    except ImportError:
        return None
    det = get_model(str(det_file), providers=["CPUExecutionProvider"])
    det.prepare(ctx_id=-1, det_size=(640, 640))
    return det


def main():
    args = [Path(a) for a in sys.argv[1:]] or [Path("uploads")]
    files = []
    for a in args:
        files += sorted(f for f in a.iterdir() if f.suffix.lower() in EXTS) if a.is_dir() else [a]
    out = Path("out") / "grid"
    out.mkdir(parents=True, exist_ok=True)
    det = face_detector()
    if det is None:
        print("(no face detector installed: grid only; `doctor.py --install ai` adds face boxes)")
    for f in files:
        im = ImageOps.exif_transpose(Image.open(f)).convert("RGB")
        im.thumbnail((1400, 1400))
        w, h = im.size
        d = ImageDraw.Draw(im, "RGBA")
        font = ImageFont.load_default(size=max(14, w // 60)) if hasattr(ImageFont, "load_default") else None
        for k in range(11):
            x, y = int(k / 10 * (w - 1)), int(k / 10 * (h - 1))
            strong = k % 5 == 0
            col = (255, 255, 0, 200) if strong else (255, 255, 255, 110)
            d.line([(x, 0), (x, h)], fill=col, width=3 if strong else 1)
            d.line([(0, y), (w, y)], fill=col, width=3 if strong else 1)
            d.text((x + 3, 3), f"{k / 10:.1f}", fill=(255, 255, 0, 255), font=font, stroke_width=2, stroke_fill=(0, 0, 0, 255))
            d.text((3, y + 3), f"{k / 10:.1f}", fill=(255, 255, 0, 255), font=font, stroke_width=2, stroke_fill=(0, 0, 0, 255))
        line = f"{f.name}  {w}x{h} ({'portrait' if h > w else 'landscape'})"
        if det is not None:
            import cv2
            import numpy as np
            boxes, _ = det.detect(cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR), max_num=0, metric="default")
            boxes = sorted(boxes.tolist(), key=lambda b: b[0])  # left to right
            for i, (x0, y0, x1, y1, score) in enumerate(boxes):
                d.rectangle((x0, y0, x1, y1), outline=(0, 255, 120, 255), width=4)
                d.text((x0 + 4, y1 + 4), f"face {i}", fill=(0, 255, 120, 255), font=font, stroke_width=2, stroke_fill=(0, 0, 0, 255))
                cx, cy, side = (x0 + x1) / 2 / w, (y0 + y1) / 2 / h, max(x1 - x0, y1 - y0) * 1.6
                card = [round(max(0, cx - side / 2 / w), 3), round(max(0, cy - side / 2 / h), 3),
                        round(min(1, cx + side / 2 / w), 3), round(min(1, cy + side / 2 / h), 3)]
                line += (f"\n   face {i}: box [{x0 / w:.3f}, {y0 / h:.3f}, {x1 / w:.3f}, {y1 / h:.3f}]  centre [{cx:.3f}, {cy:.3f}]"
                         f"  pick_x {cx:.2f}  suggested card box {card}")
        im.save(out / f"{f.stem}.jpg", quality=85)
        print(line)
    print(f"wrote {len(files)} grid images to {out}/")


if __name__ == "__main__":
    main()
