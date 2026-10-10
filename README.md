# Vigil

**Tell your cameras what to watch for, in plain language. Vigil builds a vision model for that request and runs it
on the live stream.**

> “Alert me when the blue bin on the top shelf is empty.”
> “Tell me when someone walks in through the front door.”
> “Warn me if fewer than 3 boxes are left on the pallet.”
> “Let me know if anyone is near the press without a hard hat.”

For each request, Vigil:

1. **Compiles** it into a watch spec (what to look at, the yes/no question, timing, trigger policy).
2. **Finds the region** the request means.
3. **Builds a small per-watch model**: a large vision-language model labels frames from that camera's own
   history, and a head on SigLIP 2 embeddings is trained in milliseconds.
4. **Runs it on every frame**, behind motion gating, a tracker, hysteresis, dwell timers and cooldowns.
5. **Double-checks** each alert with the large model before notifying you.
6. **Keeps learning.** The verifier's verdicts, your 👍/👎, and the frames the model is least sure about all
   become training data.

The expensive model works a few times an hour and the cheap model works every frame. That is how Vigil stays
accurate, private and cheap enough to run continuously.

## Quick start (macOS, Apple Silicon)

```bash
cd backend
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e ".[dev,local]"
vigil                      # API + engine on http://127.0.0.1:8765
```

In a second terminal:

```bash
cd web
npm install
npm run dev                # UI on http://localhost:5180 (proxies to the API)
```

Or build the UI once (`npm run build`) and open http://127.0.0.1:8765, which serves it directly.

On first run Vigil adds a **demo parts shelf** camera. In auto mode bin A-01 is picked empty every 2½ minutes, and
the camera page has buttons to empty or restock any bin. Try “Alert me when the blue bin on the top shelf is empty”.
For a real-people demo, put any pedestrian video at `data/demo/plaza.mp4` (OpenCV's `vtest.avi` works) and add a
camera of kind `demo` with URL `plaza`.

### Choosing the brain

| Brain | Setup | Speed | Privacy |
|---|---|---|---|
| **Claude** (default when a key exists) | `export ANTHROPIC_API_KEY=...` and restart | ~seconds per request | Labeled crops and alert frames go to the API |
| **Local VLM** (Qwen3.5 4B/9B via MLX) | `pip install -e ".[local]"`; the model downloads on first use, or pre-fetch `mlx-community/Qwen3.5-4B-MLX-4bit` | ~1 min to compile, 5–15 s per labeled crop | Nothing leaves the machine |
| **Built-in** | nothing | instant | local; keyword parsing + zero-shot only |

Pick one under **Settings → Brain**. The per-frame models always run locally regardless of the brain.

## Using it

- **Cameras:** add RTSP/RTSPS (with ONVIF scan and URL formats for Reolink, Tapo, Hikvision, Dahua, Axis, Hanwha,
  UniFi and Eufy), HTTP/HLS streams, video files, USB webcams, or a phone or laptop browser tab (open
  `/push/<camera id>` on the device).
- **New watch:** type the request on the Live page. Review the plan: kind, question, YES/NO labels, the region
  (drag to adjust) or tripwire (drag the ends; the arrow shows which direction counts), dwell, cooldown, severity,
  and double-check. Then **Build & start watching**. You see the labeled examples stream in and the model card
  (cross-validated F1 vs. zero-shot).
- **Watch page:** live probability or count with a threshold sparkline, **Teach it from what you see** buttons,
  the full training set (click any example to relabel it; the model retrains instantly), and the watch's events.
- **Events:** snapshot, 10-second clip, the verifier's reasoning, and **Correct / False alarm** buttons that turn
  into training data. Alerts the verifier filtered out stay visible.
- **Notifications:** ntfy (phone push, no account needed), Slack, webhooks (JSON with a base64 snapshot), Mac
  notifications, and browser notifications.

## How it works

```
camera ──▶ capture thread (reconnects, 16 s ring buffer, history every 20 s)
              │
              ▼
        analysis loop @4 Hz ── motion gate
              │
              ├─ presence/count watches ─▶ RF-DETR (COCO) │ OWLv2 (anything else, ~1 Hz)
              │                              ─▶ tracker ─▶ zone / tripwire ─▶ per-object head (optional)
              │
              └─ state watches ─▶ region crop
                                     │
                          one batched SigLIP 2 pass for every crop
                                     ▼
                     per-watch head (text-anchored logistic regression)
                                     ▼
              k-of-n vote with hysteresis ─▶ dwell ─▶ cooldown / trigger policy
                                     ▼
          event: snapshot ─▶ brain double-check ─▶ notify ─▶ 10 s clip
                                     │
               verdicts, 👍/👎, uncertain crops ─▶ new training examples ─▶ retrain (ms)
```

- **Watch kinds:** `state` (classify a region: empty, open, spilled, lit), `presence` (objects in a zone, or
  crossing a tripwire in a direction), `count` (number of objects compared to a threshold).
- **Heads:** logistic regression on SigLIP 2 embeddings, regularized toward the zero-shot direction
  `scale · (text(yes) − text(no))`. With zero labels it behaves as zero-shot; with one class it calibrates the bias;
  with both classes it picks its regularization and threshold by cross-validation. See
  `backend/vigil/learning/heads.py`.
- **Bootstrap labeling:** candidates come from the camera's on-disk history plus a short live capture. A third of
  the label budget goes to the most "positive-looking" crops (rare states are the ones worth finding), the rest to
  k-center diversity. Local VLMs label six crops per call on a numbered contact sheet.
- **Grounding:** the VLM returns a box directly (Qwen), or picks from numbered OWLv2 proposals (set-of-mark, works
  with Claude), or SigLIP ranks the proposals when no VLM is available.

More detail in [docs/RESEARCH.md](docs/RESEARCH.md) (market, model choices with measured latencies, licenses) and
[docs/HARDWARE.md](docs/HARDWARE.md) (what to buy for home, factory and development).

## Configuration

| Variable | Default | |
|---|---|---|
| `VIGIL_DATA` | `./data` | database, history frames, samples, models, event media |
| `VIGIL_HOST` / `VIGIL_PORT` | `127.0.0.1` / `8765` | use `0.0.0.0` to reach it from your phone (phones need HTTPS for camera access) |
| `VIGIL_BRAIN` | `auto` | `anthropic`, `local` or `heuristic` |
| `VIGIL_CLAUDE_MODEL` | `claude-opus-5-5` | |
| `VIGIL_LOCAL_VLM` | `…Qwen3.5-4B-MLX-4bit,…Qwen3.5-9B-4bit` | first downloaded model wins |
| `VIGIL_COCO_MODEL` | `nano` | RF-DETR size: `nano`, `small`, `medium` |
| `VIGIL_ANALYSIS_FPS` | `4` | analysis ticks per camera |
| `VIGIL_LABEL_BUDGET` | `40` | brain labels per bootstrap |
| `VIGIL_ACTIVE_LEARNING_PER_HOUR` | `12` | brain labels per watch per hour while running |
| `VIGIL_VERIFY_TIMEOUT` | `20` | seconds before an alert goes out unverified (the verdict still lands later) |

## Development

```bash
cd backend && source .venv/bin/activate
python -m pytest -q                                               # unit tests (~5 s)
VIGIL_DATA=/tmp/vigil-e2e VIGIL_BRAIN=heuristic python scripts/e2e_demo.py   # full pipeline on the demo shelf
cd ../web && npx tsc -b && npm run build
```

Layout:

```
backend/vigil/
  api.py            HTTP + WebSocket API, static hosting of the web app
  cameras/          sources (PyAV RTSP/HTTP/file, webcam, browser push, demo scenes), capture runtime, ONVIF
  perception/       SigLIP 2 embedder, RF-DETR + OWLv2 detectors, motion gate, tracker, geometry
  brain/            Claude, local MLX VLM and heuristic brains; prompts and schemas
  learning/         heads, bootstrap builder, active learner, region locator, model store
  engine/           per-camera analysis loop, watch runtime (votes, dwell, tripwires), events, notifications
web/src/            React + Tailwind UI (Live, New watch, Watch, Events, Cameras, Settings, phone camera)
```

## Limits and next steps

- **Detector fine-tuning:** today object detection uses pretrained RF-DETR or OWLv2 plus per-object heads. For
  objects OWLv2 struggles with, the next step is fine-tuning RF-DETR Nano on brain-labeled boxes (SAM 3 or Gemini
  as labeler) on a GPU.
- **Actions** ("someone falls") currently work as presence plus a per-object check plus dwell. A pose model or a
  short-clip VLM check would make them sturdier.
- **Edge port:** TensorRT exports of RF-DETR and SigLIP 2 for Jetson, go2rtc restreaming, an outbound-only
  cloud link.
- **Multi-user auth** and HTTPS are not built in yet. Run Vigil on a trusted network or behind a reverse proxy.
