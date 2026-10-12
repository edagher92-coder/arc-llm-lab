"""Guarantee aligned eyes on aged portraits: copy the eye region from a known-good anchor
portrait (same person, same chain) onto an aged image at its detected eye landmarks,
colour-matched and feather-blended. Use for older adult ages derived from one anchor.

  python eyetransplant.py chain/dad_38.png chain/dad_45.png chain/dad_54.png [--replace]
  (writes *_eyes.png next to each target, or overwrites the targets with --replace)
"""
import sys

import cv2
import numpy as np
from PIL import Image

from eyeqa import _detector, eye_score


def _kps(a):
    b, k = _detector().detect(cv2.cvtColor(a, cv2.COLOR_RGB2BGR), max_num=0, metric="default")
    return k[int(np.argmax((b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])))]


def transplant(aged, anchor):
    A = np.asarray(aged.convert("RGB")).astype(np.float32)
    B = np.asarray(anchor.convert("RGB")).astype(np.float32)
    ka, kb = _kps(A.astype(np.uint8)), _kps(B.astype(np.uint8))
    ioda, iodb = np.linalg.norm(ka[1] - ka[0]), np.linalg.norm(kb[1] - kb[0])
    s = ioda / iodb
    ca, cb = (ka[0] + ka[1]) / 2, (kb[0] + kb[1]) / 2
    M = np.array([[s, 0, ca[0] - s * cb[0]], [0, s, ca[1] - s * cb[1]]], np.float32)  # anchor -> aged
    Bw = cv2.warpAffine(B, M, (A.shape[1], A.shape[0]), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT)
    mask = np.zeros(A.shape[:2], np.float32)
    for e in ka:  # one soft ellipse per eye: lids and lashes, not brows
        cv2.ellipse(mask, (int(e[0]), int(e[1])), (int(ioda * 0.36), int(ioda * 0.22)), 0, 0, 360, 1.0, -1)
    mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=ioda * 0.05)[..., None]
    m = mask[..., 0] > 0.5
    for c in range(3):  # match the anchor patch to the aged skin tone
        ma, sa = A[..., c][m].mean(), A[..., c][m].std() + 1e-3
        mb, sb = Bw[..., c][m].mean(), Bw[..., c][m].std() + 1e-3
        Bw[..., c] = (Bw[..., c] - mb) * (0.5 + 0.5 * sa / sb) + ma
    return Image.fromarray(np.clip(Bw * mask + A * (1 - mask), 0, 255).astype(np.uint8))


if __name__ == "__main__":
    replace = "--replace" in sys.argv
    files = [a for a in sys.argv[1:] if a != "--replace"]
    anchor = Image.open(files[0])
    for f in files[1:]:
        before = eye_score(Image.open(f))[0]
        out = transplant(Image.open(f), anchor)
        dst = f if replace else f.replace(".png", "_eyes.png")
        out.save(dst)
        print(f"{dst}: eyes {before:.3f} -> {eye_score(out)[0]:.3f}")
