"""Eye-alignment score for a generated face: both irises should sit at the same
relative position inside their eyes (no cross-eye / wall-eye). Lower is better;
above ~0.08 is visibly off. Always also look at the face at full size.

  python eyeqa.py chain/*.png
"""
import numpy as np
import cv2
from insightface.model_zoo import get_model

from common import model

_det = None


def _detector():
    global _det
    if _det is None:
        _det = get_model(str(model("buffalo_l") / "detection" / "model.onnx"), providers=["CPUExecutionProvider"])
        _det.prepare(ctx_id=-1, det_size=(512, 512))
    return _det


def eye_score(pil_img):
    bgr = cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)
    b, k = _detector().detect(bgr, max_num=0, metric="default")
    if len(b) == 0:
        return 9.0, None
    i = int(np.argmax((b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])))
    kps = k[i]
    iod = np.linalg.norm(kps[1] - kps[0])
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    offs = []
    for e in (kps[0], kps[1]):
        hw, hh = int(iod * 0.30), int(iod * 0.20)
        x0, y0 = int(e[0] - hw), int(e[1] - hh)
        win = gray[max(y0, 0):int(e[1] + hh), max(x0, 0):int(e[0] + hw)]
        if win.size == 0:
            return 9.0, None
        thr = np.percentile(win, 12)             # darkest pixels = iris/pupil
        ys, xs = np.nonzero(win <= thr)
        cx, cy = xs.mean() + max(x0, 0), ys.mean() + max(y0, 0)
        offs.append(np.array([(cx - e[0]) / iod, (cy - e[1]) / iod]))
    return float(np.linalg.norm(offs[0] - offs[1])), offs


if __name__ == "__main__":
    import sys
    from PIL import Image
    for f in sys.argv[1:]:
        s, o = eye_score(Image.open(f))
        print(f"{f}: {s:.3f}", "FLAG" if s > 0.08 else "", "" if o is None else np.round(np.array(o), 3).tolist())
