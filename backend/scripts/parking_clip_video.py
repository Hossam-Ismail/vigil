"""Render a real-video parking clip of the WHOLE lot, driven by Vigil's own runtime.

Footage: Pexels video 33610407 "High-angle aerial shot of a busy parking lot" (Pexels License: free to use and modify,
no attribution required), 1920x1080, 30 fps, 23.9 s, real continuous footage, stabilized to its first frame
(scripts/parking_demo/1_stabilize.py). Shown at 2x speed.

Training data: the per-space model is trained on PKLot (public dataset, CC BY 4.0, other cameras). It never saw this
lot or this video.

Watched spaces (no zone; every bay in both lots, scripts/parking_demo/3_bays.py): every spot a car is parked in during
the clip (Vigil's own detector), plus the empty bays along each row where the painted bay lines continue, the caravan
bays and the angled top-left row. Each bay runs Vigil's real state-watch runtime ("Text me when a spot opens up"):
checked once per second, 3-of-5 vote, 2 s hold, then the alert. The watch is already running when the clip starts
(the runtime is warmed up on the first frame), so bays open at the start count as already open and send no text.
Drawn: the runtime's state per bay (taken, open, checking, holding, texted). Nothing else.

    .venv/bin/python scripts/parking_clip_video.py ../brand/pexels/lot_stable.mp4 ../brand/parking_video_lot
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark import crop  # noqa: E402
from vigil.engine.runtime import WatchRuntime  # noqa: E402
from vigil.learning.heads import train_head  # noqa: E402
from vigil.perception.embedder import get_embedder  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "brand/pexels/lot_stable.mp4")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else ROOT / "brand/parking_video_lot")
OUT.mkdir(parents=True, exist_ok=True)
BAND = (0, 196, 1920, 1010)          # both lots, 1920x814 = the 920x390 aspect
OUT_SIZE = (920, 390)
SPEED, HOLD, END_HOLD_S = 2, 2.0, 1.2
LIME, AMBER, INK, WHITE = (200, 245, 96), (245, 165, 36), (13, 15, 17), (238, 240, 234)
F = lambda s: ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", s)  # noqa: E731

cap = cv2.VideoCapture(str(SRC))
fps = cap.get(cv2.CAP_PROP_FPS)
frames = []
while True:
    ok, img = cap.read()
    if not ok:
        break
    frames.append(img)
print("frames", len(frames), "fps", fps)

lay = json.load(open(ROOT / "brand/bays.json"))
spaces = lay["bays"]
print("watched bays:", len(spaces), f"({lay['parked_spots']} where a car parks during the clip, "
      f"{len(spaces) - lay['parked_spots']} empty bays from the painted lines)")
emb = get_embedder()
tr = np.load(ROOT / "data/bench/pklot_train_siglip2-base-patch16-224_emb.npz")
w0, b0 = emb.zero_shot_direction("an empty parking space", "a car parked in a parking space")
head = train_head(tr["X"], tr["y"], w0, b0)      # PKLot's three cameras; never this footage

spec = {"name": "Spot opens", "kind": "state", "question": "Is this parking space empty?",
        "positive_label": "an empty parking space", "negative_label": "a car parked in a parking space",
        "min_duration_s": HOLD, "cooldown_s": 300, "trigger": "rising", "check_interval_s": 1.0,
        "alert_message": "A spot just opened"}
rts = [WatchRuntime({"id": i, "camera_id": 1, "name": "Spot opens", "status": "active", "spec": spec}, head)
       for i in range(len(spaces))]


def embed(img):
    return emb.embed_images([crop(img, b[0], b[1], b[2] - b[0], b[3] - b[1], pad=0.0) for b in spaces])


# the watch was already running: warm the runtime up on the first frame, so bays open at the start are "already open"
already: set[int] = set()
X0 = embed(frames[0])
for t in range(-10, 0):
    for i, (rt, e) in enumerate(zip(rts, X0)):
        if rt.step_state(float(t), e):
            already.add(i)


def chip(d, xy, text, fill, color=INK, size=30):
    f = F(size)
    x, y = xy
    w = d.textlength(text, font=f)
    d.rounded_rectangle([x, y, x + w + 24, y + size + 18], radius=10, fill=fill)
    d.text((x + 12, y + 8), text, font=f, fill=color)
    return w + 24


def snapshot(rt):
    return dict(open=rt.score >= head.threshold, votes=sum(1 for v in rt.vote.buf if v == 1), cond=rt.cond,
                phase=rt.machine.phase)


state = [snapshot(rt) for rt in rts]
fired_at: dict[int, float] = {}
log = []
seq = OUT / "seq"
for p in seq.glob("*.png"):
    p.unlink()
seq.mkdir(exist_ok=True)
out_n = 0
step = int(round(fps))
ox, oy = BAND[:2]
for k, img in enumerate(frames):
    t = k / fps
    if k % step == 0:
        for i, (rt, e) in enumerate(zip(rts, embed(img))):
            if rt.step_state(t, e):
                fired_at[i] = t
            state[i] = snapshot(rt)
        log.append({"t": round(t, 2), "open": [i for i, s in enumerate(state) if s["open"]],
                    "fired": sorted(i for i, v in fired_at.items() if v == t)})
    if k % SPEED:
        continue
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).crop(BAND).convert("RGBA")
    ov = Image.new("RGBA", pil.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    chips = []
    for i, (b, s) in enumerate(zip(spaces, state)):
        x0, y0, x1, y1 = b[0] - ox, b[1] - oy, b[2] - ox, b[3] - oy
        if i in fired_at and s["phase"] == "active":                      # alert sent
            d.rounded_rectangle([x0, y0, x1, y1], radius=8, outline=LIME + (255,), width=9)
            if t - fired_at[i] < 5:
                chips.append((x0, y0, y1, "Spot opened · texted you", LIME, 32))
            elif t - fired_at[i] < 9:
                chips.append((x0, y0, y1, "texted you", LIME, 28))
        elif s["cond"] and i not in already and s["phase"] == "pending":   # vote passed, 2 s hold running
            d.rounded_rectangle([x0, y0, x1, y1], radius=8, outline=AMBER + (255,), width=6)
            chips.append((x0, y0, y1, f"holding {HOLD:.0f} s", AMBER, 28))
        elif s["cond"]:                                                    # open (already open, or alerted earlier)
            d.rounded_rectangle([x0, y0, x1, y1], radius=8, outline=LIME + (230,), width=4)
        elif s["open"] and i not in already:                               # model says empty, vote not passed yet
            d.rounded_rectangle([x0, y0, x1, y1], radius=8, outline=AMBER + (255,), width=4)
            chips.append((x0, y0, y1, f"checking {s['votes']}/3", AMBER, 28))
        else:                                                              # taken
            d.rounded_rectangle([x0, y0, x1, y1], radius=6, outline=WHITE + (120,), width=3)
    legend = f"real footage · {SPEED}× speed · {len(spaces)} spaces watched"
    placed = [(24, pil.height - 74, 24 + d.textlength(legend, font=F(30)) + 24, pil.height - 26)]
    rank = {"Spot": 0, "holding": 1, "texted": 2, "checking": 3}
    chips.sort(key=lambda c: rank[c[3].split()[0]])
    for x0, y0, y1, text, fill, size in chips:          # alerts first; a chip that cannot fit cleanly is left out
        w, h = d.textlength(text, font=F(size)) + 24, size + 18
        for cx, cy in ((x0 - 10, y0 - h - 8), (x0 - 10, y1 + 8), (x0 - w + 60, y0 - h - 8),
                       (x0 - w + 60, y1 + 8)):
            cx = min(max(4, cx), pil.width - w - 4)
            r = (cx, cy, cx + w, cy + h)
            if cy >= 4 and cy + h <= pil.height - 4 and not any(
                    r[0] < q[2] + 8 and q[0] < r[2] + 8 and r[1] < q[3] + 8 and q[1] < r[3] + 8 for q in placed):
                chip(d, (cx, cy), text, fill + (255,), INK, size)
                placed.append(r)
                break
    chip(d, placed[0][:2], legend, INK + (230,), WHITE, size=30)
    pil = Image.alpha_composite(pil, ov).convert("RGB")
    pil.resize(OUT_SIZE, Image.LANCZOS).save(seq / f"{out_n:04d}.png")
    out_n += 1

clip_frames = out_n
last_frame = Image.open(seq / f"{clip_frames - 1:04d}.png")
for _ in range(int(END_HOLD_S * 30)):                      # let the last texts be read before the loop
    last_frame.save(seq / f"{out_n:04d}.png")
    out_n += 1
first, last = np.array(Image.open(seq / "0000.png")), np.array(last_frame)
for a in np.linspace(0, 1, 14)[1:-1]:
    Image.fromarray((last * (1 - a) + first * a).astype(np.uint8)).save(seq / f"{out_n:04d}.png")
    out_n += 1
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "30", "-i", str(seq / "%04d.png"), "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "slow", "-movflags", "+faststart",
                str(OUT / "parking_video.mp4")], check=True)
# poster: the moment the most fresh "Spot opened" chips are on screen
best_t = max(fired_at.values(), key=lambda ft: sum(1 for v in fired_at.values() if 0 <= ft + 0.5 - v < 5)) + 0.5
Image.open(seq / f"{min(int(best_t * fps / SPEED), clip_frames - 1):04d}.png").save(OUT / "parking_video_still.png")
(OUT / "log.json").write_text(json.dumps({"spaces": spaces, "parked_spots": lay["parked_spots"],
                                          "fired": fired_at, "already_open": sorted(already), "evals": log}, indent=1))
print("watched", len(spaces), "| open at start", len(already), "| alerts:", {i: round(v, 1) for i, v in fired_at.items()},
      "| frames", out_n, "=", round(out_n / 30, 2), "s | poster t", round(best_t, 1))
