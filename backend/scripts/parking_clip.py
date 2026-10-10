"""Render a real parking clip driven by Vigil's own runtime.

Source: PKLot (dronefreak/PKLot on Hugging Face, CC BY 4.0), camera PUCPR, 2012-10-16, test split. Every capture day in
the test split is held out from the training split, so the model never saw these frames. Frames are ~5 minutes apart
(time-lapse). One state watch per front-row space ("Text me when a spot opens up in the front row"), each running
Vigil's WatchRuntime (3-of-5 vote, hold time, alert) on a head trained only on PUCPR's training days. Only the model's
calls and the runtime's state are drawn; the dataset's labels are used afterwards to check the calls, never to draw.

    .venv/bin/python scripts/parking_clip.py ../data/bench ../brand/parking_clip
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from huggingface_hub import hf_hub_download
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark import crop  # noqa: E402
from vigil.brain.heuristic import HeuristicBrain  # noqa: E402
from vigil.engine.runtime import WatchRuntime  # noqa: E402
from vigil.learning.heads import train_head  # noqa: E402
from vigil.perception.embedder import get_embedder  # noqa: E402

BENCH = Path(sys.argv[1] if len(sys.argv) > 1 else "../data/bench")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "../brand/parking_clip")
OUT.mkdir(parents=True, exist_ok=True)
DAY, WARM, FIRST, LAST = "2012-10-16", 30, 50, 64  # frame indices within the day (space 92 opens at frame 55)
# frames WARM..FIRST-1 run through the watch but are not shown, so the clip starts mid-morning like a live watch would
CROP = (80, 330, 1000, 720)                      # 920x390 window on the 1280x720 frame
PROMPT = "Text me when a spot opens up in the front row"
LIME, AMBER, INK, WHITE = (200, 245, 96), (245, 165, 36), (13, 15, 17), (238, 240, 234)
F = lambda s: ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", s)  # noqa: E731

rows = [json.loads(l) for l in open(hf_hub_download("dronefreak/PKLot", "data/images/test/metadata.jsonl", repo_type="dataset"))]
day = sorted((r for r in rows if r["file_name"].startswith(f"PUCPR_{DAY}")), key=lambda r: r["file_name"])
ref = max((r for r in rows if r["file_name"].startswith("PUCPR")), key=lambda r: len(r["objects"]["bbox"]))
RB = np.array(ref["objects"]["bbox"], dtype=float)
RC = RB[:, :2] + RB[:, 2:] / 2
FRONT = [i for i in range(len(RC)) if RC[i, 1] > 500]   # the bottom row of the main lot: the watch's spaces

# the watch, compiled from the prompt, and its model (training days only)
spec = HeuristicBrain().compile(PROMPT, None, "Parking lot")
spec.update(name="Front-row spot opens", positive_label="an empty parking space",
            negative_label="a car parked in a parking space", alert_message="A front-row spot just opened")
emb = get_embedder()
tr = np.load(BENCH / "pklot_train_siglip2-base-patch16-224_emb.npz")
w0, b0 = emb.zero_shot_direction(spec["positive_label"], spec["negative_label"])
head = train_head(tr["X"][tr["g"] == "PUCPR"], tr["y"][tr["g"] == "PUCPR"], w0, b0)
rts = {i: WatchRuntime({"id": i, "camera_id": 1, "name": spec["name"], "status": "active", "spec": spec}, head) for i in FRONT}
print("watch:", spec["kind"], "hold", spec["min_duration_s"], "s; head", head.mode, "thr", round(head.threshold, 2))


def ts_of(name: str) -> float:
    return datetime.strptime(name[6:25], "%Y-%m-%d_%H_%M_%S").timestamp()


def chip(d, xy, text, fill, color=INK, size=18):
    f = F(size)
    x, y = xy
    w = d.textlength(text, font=f)
    d.rounded_rectangle([x, y, x + w + 16, y + size + 12], radius=7, fill=fill)
    d.text((x + 8, y + 5), text, font=f, fill=color)


frames, log, fired_at = [], [], {}
agree = total = 0
for k in range(WARM, LAST + 1):
    r = day[k]
    p_img = hf_hub_download("dronefreak/PKLot", f"data/images/test/{r['file_name']}", repo_type="dataset")
    img = cv2.imread(p_img)
    ts = ts_of(r["file_name"])
    E = emb.embed_images([crop(img, *RB[i]) for i in FRONT])
    # ground truth for checking only
    B = np.array(r["objects"]["bbox"]); C = B[:, :2] + B[:, 2:] / 2
    state = {}
    for i, e in zip(FRONT, E):
        rt = rts[i]
        trig = rt.step_state(ts, e)
        p = rt.score
        if trig:
            fired_at[i] = k
        j = int(np.linalg.norm(C - RC[i], axis=1).argmin())
        truth_open = r["objects"]["categories"][j] == 0
        call_open = p >= head.threshold
        if k >= FIRST:
            agree += int(truth_open == call_open); total += 1
        state[i] = dict(p=round(p, 3), open=call_open, votes=sum(1 for v in rt.vote.buf if v == 1), cond=rt.cond,
                        phase=rt.machine.phase, fired=bool(trig), truth_open=truth_open)
    log.append({"frame": k, "file": r["file_name"], "spaces": {str(i): s for i, s in state.items()}})
    if k < FIRST:
        continue

    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).crop(CROP)
    d = ImageDraw.Draw(pil)
    ox, oy = CROP[:2]
    for i in FRONT:
        s = state[i]
        x, y, w, h = RB[i]
        x, y = x - ox, y - oy
        if not (0 <= x and x + w <= pil.width):
            continue
        if fired_at.get(i, -1) >= FIRST and s["phase"] == "active":  # alert fired in view: this spot is reported open
            d.rounded_rectangle([x, y, x + w, y + h], radius=6, outline=LIME, width=5)
        elif s["open"]:                                     # model calls it open
            d.rounded_rectangle([x, y, x + w, y + h], radius=6, outline=LIME, width=3)
            if not s["cond"]:                               # 3-of-5 vote still collecting
                chip(d, (x - 4, y + h + 6), f"confirming {s['votes']}/3", AMBER, size=16)
            elif s["phase"] == "pending":                   # vote passed, hold time running
                chip(d, (x - 4, y + h + 6), f"holding {spec['min_duration_s']:.0f} s", AMBER, size=16)
    for i, kf in fired_at.items():
        if kf < FIRST or kf > k:
            continue
        x, y, w, h = RB[i]
        chip(d, (x - ox - 4, y - oy - 34), "Spot opened · texted you" if k == kf else "texted you", LIME, size=18)
    t = datetime.fromtimestamp(ts_of(r["file_name"]))
    chip(d, (12, 12), f"PKLot · PUCPR · {t:%b %-d %Y · %-I:%M %p}", (13, 15, 17), WHITE, size=16)
    chip(d, (12, pil.height - 40), "time-lapse · 1 frame ≈ 5 min", (13, 15, 17), WHITE, size=16)
    path = OUT / f"f{k:03d}.png"
    pil.save(path)
    frames.append(path)

print("model agreed with PKLot's labels on", agree, "of", total, "front-row space-frames")
print("alerts:", {i: (day[k]["file_name"], "in clip" if k >= FIRST else "during warm-up") for i, k in fired_at.items()})
(OUT / "log.json").write_text(json.dumps({"day": DAY, "frames": [FIRST, LAST], "front_row": FRONT, "agree": agree,
                                          "total": total, "fired": {str(i): k for i, k in fired_at.items()},
                                          "spec": {k: spec[k] for k in ("kind", "min_duration_s", "trigger")},
                                          "threshold": head.threshold, "log": log}, indent=1))

# video: each frame held 0.6 s at 15 fps, then a 0.4 s cross-fade back to the first frame so it loops cleanly
seq = OUT / "seq"
seq.mkdir(exist_ok=True)
n = 0
imgs = [np.array(Image.open(p)) for p in frames]
for im in imgs:
    for _ in range(9):
        Image.fromarray(im).save(seq / f"{n:04d}.png"); n += 1
for a in np.linspace(0, 1, 7)[1:-1]:
    Image.fromarray((imgs[-1] * (1 - a) + imgs[0] * a).astype(np.uint8)).save(seq / f"{n:04d}.png"); n += 1
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "15", "-i", str(seq / "%04d.png"), "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "slow", "-movflags", "+faststart",
                str(OUT / "parking_clip.mp4")], check=True)
still = next((frames[k - FIRST] for k in sorted(fired_at.values()) if k >= FIRST), frames[-1])
Image.open(still).save(OUT / "parking_still.png")
print("frames:", n, "duration:", round(n / 15, 2), "s; still:", still.name)
