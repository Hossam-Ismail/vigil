"""Deck cover: a 3x2 wall of real camera feeds (Pexels License clips), looped, with feed labels only.

No detections are drawn: the wall is the "nobody is watching" beat. Sources (pexels.com/video/<id>):
16393893 construction site, 13852105 pedestrian crossing, 20654640 truck yard, 19384327 main street,
2711276 lumber yard, 5092285 pallet yard.

    .venv/bin/python scripts/cover_wall.py
"""
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2] / "brand"
SRC = ROOT / "pexels/wall"
OUT = ROOT / "cover"
OUT.mkdir(exist_ok=True)
FEEDS = [("16393893-hd_1280_720_30fps", 3.0, "CAM 01 // SITE 4 · LEVEL 3"),
         ("13852105-hd_1280_720_30fps", 6.0, "CAM 02 // PIER CROSSING"),
         ("20654640-hd_1280_720_30fps", 1.0, "CAM 03 // YARD GATE"),
         ("19384327-hd_1280_720_30fps", 4.0, "CAM 04 // MAIN ST"),
         ("2711276-hd_1920_1080_24fps", 0.5, "CAM 05 // LUMBER YARD"),
         ("5092285-hd_1280_720_30fps", 12.0, "CAM 06 // PALLET YARD")]
FPS, SECONDS, FADE = 30, 8.0, 0.8
TW, TH, GAP = 636, 536, 6
N = int(FPS * SECONDS)
MONO = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 17)
scan = np.ones((TH, TW, 1), np.float32)
scan[::3] = 0.82


def read(name, start):
    cap = cv2.VideoCapture(str(SRC / f"{name}.mp4"))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    want = [int((start + i / FPS) * fps) % total for i in range(N + int(FADE * FPS))]
    frames, k, cache = [], -1, None
    for w in want:
        while k < w:
            ok, img = cap.read()
            if not ok:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0); k = -1; continue
            k += 1; cache = img
        frames.append(cache)
    return frames


def tile(img):
    h, w = img.shape[:2]
    s = max(TW / w, TH / h)
    img = cv2.resize(img, (int(w * s + 1), int(h * s + 1)), interpolation=cv2.INTER_AREA)
    y, x = (img.shape[0] - TH) // 2, (img.shape[1] - TW) // 2
    img = img[y:y + TH, x:x + TW].astype(np.float32)
    g = img.mean(2, keepdims=True)
    img = (0.25 * img + 0.75 * g) * np.array([0.92, 1.0, 0.95])  # nearly monochrome, faint green
    return np.clip(img * 0.9 * scan, 0, 255).astype(np.uint8)


streams = [read(n, s) for n, s, _ in FEEDS]
seq = OUT / "seq"
seq.mkdir(exist_ok=True)
for p in seq.glob("*.png"):
    p.unlink()
F = int(FADE * FPS)
for i in range(N):
    canvas = Image.new("RGB", (1920, 1080), (13, 15, 17))
    for j, ((_, _, label), fr) in enumerate(zip(FEEDS, streams)):
        img = tile(fr[i])
        if i < F:                                    # loop seam: blend the tail into the head
            a = i / F
            img = (tile(fr[N + i]) * (1 - a) + img * a).astype(np.uint8)
        img[:52] = (img[:52] * 0.45).astype(np.uint8)          # dark strip so the feed label reads on any tile
        t = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        d = ImageDraw.Draw(t)
        ts = f"10:42:{(7 + i // FPS + 3 * j) % 60:02d}"
        d.text((18, 14), label, font=MONO, fill=(232, 236, 230))
        d.text((TW - 132, 14), ts, font=MONO, fill=(170, 176, 172))
        if (i // 15) % 2 == 0:
            d.ellipse([TW - 152, 19, TW - 142, 29], fill=(255, 59, 48))
        canvas.paste(t, ((j % 3) * (TW + GAP), (j // 3) * (TH + GAP)))
    canvas.save(seq / f"{i:04d}.png")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(seq / "%04d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "24", "-preset", "slow", "-movflags", "+faststart",
                str(OUT / "cover_wall.mp4")], check=True)
Image.open(seq / f"{N // 2:04d}.png").save(OUT / "cover_wall_still.jpg", quality=88)
print("frames", N)
