"""Identity embeddings (insightface buffalo_l ArcFace, local ONNX) for each person in people.json.

  python faces.py [people.json]
people.json: {"mum": [{"file": "IMG_1.jpg", "pick_x": 0.3}, {"file": "IMG_2.jpg"}], "child": [...]}
  pick_x: which face in a group photo (0 = left edge, 1 = right edge); omit for the largest face.
Use 3-6 clear, front-facing photos per person. Writes emb_<who>.npy and face_refs.jpg,
and prints pairwise similarities: a photo scoring < ~0.35 against the others is
probably the wrong face and should be removed or given a better pick_x.
"""
import json
import sys

import cv2
import numpy as np
from insightface.app.common import Face
from insightface.model_zoo import get_model
from PIL import Image

from common import AI, load_photo, model

M = model("buffalo_l")
det = get_model(str(M / "detection" / "model.onnx"), providers=["CPUExecutionProvider"])
det.prepare(ctx_id=-1, det_size=(640, 640))
rec = get_model(str(M / "recognition" / "model.onnx"), providers=["CPUExecutionProvider"])
rec.prepare(ctx_id=-1)

people = json.loads(open(sys.argv[1] if len(sys.argv) > 1 else AI / "people.json").read())
out, crops = {}, []
for who, refs in people.items():
    embs = []
    for r in refs:
        im = load_photo(r["file"])
        im.thumbnail((1600, 1600))
        bgr = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
        bboxes, kpss = det.detect(bgr, max_num=0, metric="default")
        if len(bboxes) == 0:
            print(who, r["file"], "NO FACE FOUND")
            continue
        if r.get("pick_x") is None:
            i = int(np.argmax((bboxes[:, 2] - bboxes[:, 0]) * (bboxes[:, 3] - bboxes[:, 1])))
        else:
            cx = (bboxes[:, 0] + bboxes[:, 2]) / 2 / im.width
            i = int(np.argmin(np.abs(cx - r["pick_x"])))
        f = Face(bbox=bboxes[i, :4], kps=kpss[i], det_score=bboxes[i, 4])
        rec.get(bgr, f)
        embs.append(f.normed_embedding)
        x0, y0, x1, y1 = bboxes[i, :4].astype(int)
        crops.append(im.crop((x0, y0, x1, y1)).resize((128, 128)))
        print(who, r["file"], "faces", len(bboxes), "picked", i, "score %.2f" % bboxes[i, 4])
    if not embs:
        continue
    E = np.stack(embs)
    print(who, "pairwise similarity:\n", np.round(E @ E.T, 2))
    mean = E.mean(0)
    mean /= np.linalg.norm(mean)
    out[who] = mean
    np.save(AI / f"emb_{who}.npy", mean)
if crops:
    sheet = Image.new("RGB", (128 * len(crops), 128))
    for k, c in enumerate(crops):
        sheet.paste(c, (k * 128, 0))
    sheet.save(AI / "face_refs.jpg")
print("cross-person similarity (should be low):", {f"{a}-{b}": round(float(out[a] @ out[b]), 2) for a in out for b in out if a < b})
