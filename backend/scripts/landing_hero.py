"""Landing hero: a smooth looping animated WebP of real footage with Vigil's own person detections.

Footage: Pexels video 13852105 "Pedestrians on street in overhead view" (Pexels License). Every bracket is a person
found by Vigil's COCO detector (tiled, every frame), lightly smoothed by an IoU tracker so the boxes glide instead of
jitter. The count in the corner is the number of those detections. Nothing is hand-placed.

    .venv/bin/python scripts/landing_hero.py
"""
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vigil.perception.detector import get_coco  # noqa: E402

ROOT = Path(__file__).resolve().parents[2] / "brand"
SRC = ROOT / "pexels/wall/13852105-hd_1280_720_30fps.mp4"
OUT = ROOT / "landing"
OUT.mkdir(exist_ok=True)
START, SECONDS, FPS, FADE = 8.0, 6.0, 24, 0.75
W, H = 1280, 676
MONO = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 15)


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1])); i = ix * iy
    return i / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i + 1e-9)


def detect(img):
    h, w = img.shape[:2]
    out = []
    for ty in range(2):
        for tx in range(3):
            x0, y0 = int(tx * w / 3 * 0.9), int(ty * h / 2 * 0.85)
            x1, y1 = min(w, x0 + int(w / 3 * 1.2)), min(h, y0 + int(h / 2 * 1.3))
            for d in get_coco().detect(img[y0:y1, x0:x1], {"person": ["person"]}, threshold=0.35):
                b = d.box
                out.append([x0 + b[0] * (x1 - x0), y0 + b[1] * (y1 - y0), x0 + b[2] * (x1 - x0), y0 + b[3] * (y1 - y0), float(d.conf)])
    keep = []
    for b in sorted(out, key=lambda x: -x[4]):
        if all(iou(b, k) < 0.4 for k in keep):
            keep.append(b)
    return keep


cap = cv2.VideoCapture(str(SRC))
src_fps = cap.get(cv2.CAP_PROP_FPS)
n = int((SECONDS + FADE) * FPS)
frames = []
for i in range(n):
    cap.set(cv2.CAP_PROP_POS_FRAMES, int((START + i / FPS) * src_fps))
    ok, img = cap.read()
    frames.append(img)

tracks = []      # [box(4), conf, misses]
drawn = []
for img in frames:
    dets = detect(img)
    used = set()
    for tr in tracks:
        best = max(range(len(dets)), key=lambda j: iou(tr[0], dets[j]), default=None)
        if best is not None and best not in used and iou(tr[0], dets[best]) > 0.25:
            tr[0] = [0.55 * a + 0.45 * b for a, b in zip(tr[0], dets[best][:4])]
            tr[1], tr[2] = dets[best][4], 0
            used.add(best)
        else:
            tr[2] += 1
    tracks = [t for t in tracks if t[2] <= 3] + [[d[:4], d[4], 0] for j, d in enumerate(dets) if j not in used]
    drawn.append([(list(t[0]), t[1]) for t in tracks if t[2] <= 1])


def render(img, boxes):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    rgb = np.stack([g * 0.9, g * 0.97, g * 0.93], 2) * 0.62           # monochrome, dimmed for the headline
    rgb[::3] *= 0.86                                                    # scanlines
    pil = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).convert("RGBA")
    ov = Image.new("RGBA", pil.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for (x0, y0, x1, y1), _ in boxes:
        L = max(4, int(min(x1 - x0, y1 - y0) * 0.35))
        for (ax, ay, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            d.line([(ax, ay), (ax + dx * L, ay)], fill=(238, 240, 234, 210), width=2)
            d.line([(ax, ay), (ax, ay + dy * L)], fill=(238, 240, 234, 210), width=2)
    d.rectangle([0, 0, W, 40], fill=(0, 0, 0, 110))
    d.text((16, 12), f"CAM 07 // PIER CROSSING      PEOPLE {len(boxes):>3}", font=MONO, fill=(200, 245, 96, 255))
    out = Image.alpha_composite(pil, ov).convert("RGB")
    s = max(W / out.width, H / out.height)
    out = out.resize((int(out.width * s + 0.5), int(out.height * s + 0.5)), Image.LANCZOS)
    return out.crop(((out.width - W) // 2, (out.height - H) // 2, (out.width - W) // 2 + W, (out.height - H) // 2 + H))


N, F = int(SECONDS * FPS), int(FADE * FPS)
imgs = [render(f, b) for f, b in zip(frames, drawn)]
loop = []
for i in range(N):
    if i < F:                                          # seamless loop: the tail fades into the head
        a = i / F
        loop.append(Image.blend(imgs[N + i], imgs[i], a))
    else:
        loop.append(imgs[i])
loop[0].save(OUT / "hero.webp", save_all=True, append_images=loop[1:], duration=int(1000 / FPS), loop=0,
             quality=62, method=4)
loop[N // 2].save(OUT / "hero_still.jpg", quality=88)
print("frames", N, "mean people", round(np.mean([len(b) for b in drawn[:N]]), 1),
      "size MB", round((OUT / "hero.webp").stat().st_size / 1e6, 2))
