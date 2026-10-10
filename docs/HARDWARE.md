# Hardware guide

Vigil runs today on a Mac (Apple Silicon) with any RTSP camera, or with no camera at all (phone browser or demo
scenes). This is what to buy as it moves to homes and factories. Prices were checked on 2026-10-09. DRAM and HDD
shortages have pushed many prices up this year, so treat them as approximate.

## What the software needs

| Workload | Where it runs | Need |
|---|---|---|
| Decode 1080p sub-streams at ~5 fps | Every camera | Hardware video decode (VideoToolbox, NVDEC, QuickSync) |
| Detector (RF-DETR Nano/Small) | Presence and count watches, every tick | ~5–50 ms per frame on a GPU or NPU |
| SigLIP 2 embeddings + linear heads | Every watch | ~10–15 ms per crop |
| OWLv2 open-vocabulary detection | Only for non-COCO targets, about once a second | GPU, ~0.4 s per frame on an M3 Pro |
| Brain (compile, label, verify) | Occasionally: setup, a few labels per hour, each alert | Cloud API, or 8+ GB unified memory for a local 4B VLM |

## Edge compute

| Option | Price | Fit |
|---|---|---|
| **Mac mini M6 (16 GB)** | $899 | Best single box for this codebase as written. MPS + MLX run every model here, including the local VLM. Handles ~10–20 sub-streams. |
| **Jetson Orin Nano Super 8 GB** | $399 (after Jul 2026 price rise) | Production edge target: TensorRT RF-DETR and SigLIP, ~8–11 streams. VLM work goes to the cloud; 8 GB is tight. |
| **Orin NX 16 GB box** (reComputer J4012) | ~$900–1,400 | Small factory line, 15–20 streams, room for a 4B local VLM. |
| **Intel N150 mini PC** (Beelink EQ14) | ~$195 | Cheapest home hub: OpenVINO iGPU, 2–6 streams of fixed detectors, cloud brain only. |
| **Raspberry Pi 5 + AI HAT+ (Hailo-8, 26 TOPS)** | ~$175 + $110–157 | Fixed detectors only (no open vocabulary). No H.264 hardware decode, so use H.265 cameras. |
| **AMD Ryzen AI Max+ 395 (128 GB)** | ~$2,000–3,200 | On-prem 30B-class VLM for fully private factories. |
| Google Coral | — | Avoid: runtime stalled since 2022 and the driver was archived in 2026. |

## Cameras

General rules for ML:
- Analyze the sub-stream and record from it too. Keep targets at least ~32 px across.
- Sensor size matters more than megapixels. Stick to 5 MP or below for Reolink.
- Use fixed mounts. A bumped camera silently moves every region.
- IR night video is monochrome. Train on night frames too (Vigil's history sampling helps), or use color-night cameras.

**Home**
- Reolink RLC-510A (5 MP PoE, 30 m IR): ~$50. Excellent value, clean RTSP.
- Tapo C120 (2K Wi-Fi, RTSP/ONVIF): ~$43.
- Reolink E1 Pro (indoor Wi-Fi): ~$65.
- UniFi G5/G6 Bullet: $129 / $199. Needs a UniFi console, which re-serves the feeds as RTSPS.

**Factory**
- Axis M2035-LE (~$380–450) or Hanwha QNO-6012R (~$305). NDAA-safe, rugged, true WDR.
- UniFi G6 Pro Bullet (1/1.2" sensor): $479. Very good in low light.
- Fast-moving parts or conveyors need global-shutter machine-vision cameras: Basler ace 2 GigE (~$380–490) or
  FLIR Blackfly S PoE (~$370), plus a lens. These are read through GenICam (pypylon / Aravis), not RTSP; an adapter
  for them is a natural next connector.
- Don't build B2B kits on Hikvision or Dahua: FCC import and marketing ban as of July 2026.

## Supporting hardware

- **PoE switch:** TP-Link TL-SG1005P (4 PoE ports, 65 W, ~$49) for homes; a managed 8–16 port PoE+ switch for
  factories. Budget 6–12 W per camera with IR on.
- **Network:** put cameras on their own VLAN with no internet access, and disable P2P/UPnP on them. Only the Vigil
  box talks to both sides, and only outbound.
- **Bandwidth:** sub-streams use ~0.3–1 Mbps each. Sixteen cameras fit easily on gigabit.
- **Storage:** Vigil records event clips, not continuous video, so a few GB lasts a long time. Continuous recording
  at 4 Mbps takes ~43 GB per day per camera.
- **Lighting:** use flicker-free LED drivers and lock exposure and white balance where the camera allows it. Add
  850 nm IR for range, or 940 nm when the illuminator must not be visible.
- **Power:** a small UPS for the box, switch and modem.

## Reference kits

| Kit | Contents | Cost |
|---|---|---|
| **Your dev kit (this month)** | Your Mac + 2× Reolink RLC-510A + Tapo C120 + TL-SG1005P + a cheap IR light. Optional Jetson Orin Nano Super ($399) to start the TensorRT port. | ~$250 without the Jetson, ~$650 with it |
| **Home starter** | Beelink EQ14 or Mac mini, 3× RLC-510A, 4-port PoE switch, cables and mounts, cloud brain | ~$450–600 (N150) / ~$1,150 (Mac mini) |
| **Small factory line** | Orin NX 16 GB box (or Mac mini M5 Pro for a local VLM), 8× Hanwha QNO-6012R, 16-port PoE+ switch, UPS, lighting and mounts, optional 2× Blackfly S | ~$6,500–7,500 |

## Porting notes for production edge

- Export RF-DETR to ONNX → TensorRT (FP16/INT8) and SigLIP 2's vision tower the same way. Per-watch heads are just
  a dot product, so they port anywhere.
- Restream every camera through go2rtc or MediaMTX so Vigil and any recorder share one RTSP session per camera.
- Keep labeling, verification and retraining in the cloud for 8 GB devices. Push new heads (a few KB each) to
  devices.
