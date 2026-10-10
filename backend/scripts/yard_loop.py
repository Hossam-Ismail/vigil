"""Deck cover + landing hero: real footage of a working yard, with Vigil's own truck detection.

Footage: Pexels video 2711276 (lumber yard from above, Pexels License). The lime bracket follows the truck that
Vigil's COCO detector finds in each frame (class "truck", conf >= 0.3), smoothed by a one-track EMA so it glides.
Nothing is hand-placed. Outputs a 1920x1080 MP4 loop (deck) and a 1280x676 animated WebP loop (site).

    .venv/bin/python scripts/yard_loop.py
"""
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vigil.perception.detector import get_coco  # noqa: E402

ROOT = Path(__file__).resolve().parents[2] / "brand"
SRC = ROOT / "pexels/wall/2711276-hd_1920_1080_24fps.mp4"
OUT = ROOT / "yard"
OUT.mkdir(exist_ok=True)
FADE = 0.6
LIME = (200, 245, 96)

cap = cv2.VideoCapture(str(SRC))
fps = cap.get(cv2.CAP_PROP_FPS)
frames = []
while True:
    ok, img = cap.read()
    if not ok:
        break
    frames.append(img)
total = len(frames)
N, F = total - int(FADE * fps), int(FADE * fps)

box, miss, boxes = None, 99, []
for img in frames:
    trucks = [d for d in get_coco().detect(img, {"truck": ["truck"]}, threshold=0.3)]
    h, w = img.shape[:2]
    cands = [[d.box[0] * w, d.box[1] * h, d.box[2] * w, d.box[3] * h] for d in trucks]
    if cands:
        c = max(cands, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))      # the big truck in the yard
        box = c if box is None or miss > 12 else [0.6 * a + 0.4 * b for a, b in zip(box, c)]
        miss = 0
    else:
        miss += 1
    boxes.append(box if miss <= 12 else None)
print("frames", total, "truck found in", sum(b is not None for b in boxes))


def render(img, b):
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    pil = Image.blend(pil, Image.new("RGB", pil.size, (13, 15, 17)), 0.18)
    if b is not None:
        d = ImageDraw.Draw(pil)
        x0, y0, x1, y1 = b[0] - 14, b[1] - 14, b[2] + 14, b[3] + 14
        L = int(min(x1 - x0, y1 - y0) * 0.22)
        for (ax, ay, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            d.line([(ax, ay), (ax + dx * L, ay)], fill=LIME, width=6)
            d.line([(ax, ay), (ax, ay + dy * L)], fill=LIME, width=6)
    return pil


imgs = [render(f, b) for f, b in zip(frames, boxes)]
loop = [Image.blend(imgs[N + i], imgs[i], i / F) if i < F else imgs[i] for i in range(N)]
seq = OUT / "seq"
seq.mkdir(exist_ok=True)
for p in seq.glob("*.png"):
    p.unlink()
for i, im in enumerate(loop):
    im.save(seq / f"{i:04d}.png")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(round(fps)), "-i", str(seq / "%04d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "22", "-preset", "slow", "-movflags", "+faststart",
                str(OUT / "yard.mp4")], check=True)
loop[N // 3].save(OUT / "yard_still.jpg", quality=88)
W, H = 1280, 676
small = []
for im in loop:
    s = im.resize((W, int(im.height * W / im.width)), Image.LANCZOS)
    top = (s.height - H) // 2
    small.append(s.crop((0, top, W, top + H)))
small[0].save(OUT / "yard.webp", save_all=True, append_images=small[1:], duration=int(1000 / fps), loop=0,
              quality=60, method=4)
small[N // 3].save(OUT / "yard_web_still.jpg", quality=88)
print("loop s", round(N / fps, 2), "mp4 MB", round((OUT / "yard.mp4").stat().st_size / 1e6, 1),
      "webp MB", round((OUT / "yard.webp").stat().st_size / 1e6, 1))
