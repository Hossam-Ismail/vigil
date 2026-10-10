# Research notes (October 2026)

What exists, which models to build on, and why Vigil is shaped the way it is. Prices and versions were
checked on 2026-10-09; anything marked *unverified* could not be confirmed from a primary source.

## 1. The market

Typing an alert in plain language and getting notified from your cameras is now a standard feature in
enterprise VMS products, and the big consumer brands are adding it. Almost all of them get there by running a
VLM over events or by matching embeddings. Very few compile the request into a model that runs on every frame.

| Product | What it does | How detection works | Gap |
|---|---|---|---|
| Spot AI "Iris" | Builds a custom agent through conversation ("8 minutes, 20 images") | Trains a model per request | Sales-led enterprise; appliance + cloud |
| Verkada | Free-text alerts ("no safety vest") | VLM pipeline | Full AI only on Verkada cameras |
| Lumana, Coram, Ambient.ai, Eagle Eye/Brivo "Eeva" | Natural-language alerts, enterprise | VLMs | Quote-only, appliance + cloud |
| Rhombus Insights | You write a prompt for a number or yes/no; it polls on a schedule | Polls an LLM on snapshots | Not a trained model; costly at high frequency |
| Google Home Premium (May 2026) | Automations triggered by any "visual insight" you describe | Cloud Gemini | Nest cameras only, US preview |
| Arlo Custom Detection | Teach a state or object from your own examples | Per-user example-based model | Arlo cameras only |
| Ring, Wyze | VLM captions and search | Captions | No custom triggers |
| Frigate 0.17 (open source) | Locally trained state/object classifiers, semantic-search triggers, GenAI summaries | MobileNetV2 per state | Configured in YAML; for DIY users |
| Roboflow Rapid (Dec 2025) | Prompt + images produces an auto-labelled, trained RF-DETR model in under 5 minutes | Per-request training | Developer tool; no camera onboarding or alert UX |

**Where Vigil fits:** it compiles each request into a small model that runs on every frame, keeps the expensive
VLM for labeling and for double-checking alerts, works with any camera, runs locally, and learns from every
correction. Conditions that persist ("bin empty for 30 s") and direction ("enters through the door") are handled
explicitly, which snapshot-polling VLM products do poorly.

Sources: Spot AI ([AI News](https://www.artificialintelligence-news.com/news/spot-ai-introduces-the-worlds-first-universal-ai-agent-builder-for-security-cameras/)),
Verkada ([blog](https://www.verkada.com/blog/industry-specific-alerts/)), Rhombus Insights ([SIW](https://www.securityinfowatch.com/ai/product/55397966/rhombus-systems-rhombus-insights)),
Google Home ([9to5Google](https://9to5google.com/2026/05/27/google-home-camera-automation-more/)),
Arlo ([FAQ](https://www.arlo.com/en_gb/support/faq/arlo-secure-features/arlo-custom-detection-and-privacy)),
Frigate 0.17 ([release](https://github.com/blakeblackshear/frigate/releases/tag/v0.17.0)),
Roboflow Rapid ([blog](https://roboflow.com/blog/roboflow-rapid)).

## 2. The technique

Don't run a large promptable model on every frame. Treat the sentence as a program to compile:

1. **Compile.** An LLM/VLM turns the request into a spec: kind (state / presence / count), the yes/no question,
   short visual labels for both outcomes, targets, region or tripwire, dwell time, cooldown, trigger policy.
2. **Ground.** Find the region the request names. Vigil asks the VLM for a box, or uses OWLv2 proposals plus
   "set-of-mark" prompting: the candidates are numbered on the image and the VLM picks one.
3. **Bootstrap a model.** Collect frames from the camera's history plus a short live capture, crop the region
   (or the detected objects), choose a diverse and informative subset, have the VLM label it, and train.
4. **Run cheaply.** Motion gate → detector → SigLIP 2 embedding → per-watch linear head → k-of-n vote with
   hysteresis → dwell → cooldown and trigger policy.
5. **Verify and learn.** Each alert's frames go to the VLM before anyone is notified. Its verdict, your 👍/👎, and
   the crops the head is least sure about all become training data. The head retrains in milliseconds.

**Why a linear head on frozen embeddings, and not a fine-tuned detector, for state watches:** with only a few
dozen examples, logistic regression on frozen features matches or beats full fine-tuning
([arXiv 2408.08058](https://arxiv.org/pdf/2408.08058)). It trains in milliseconds, so every correction retrains
immediately. One backbone pass serves every watch on a camera, and it outputs probabilities that the alert
thresholds can use. Frigate ships the same pattern for its state classifiers. Vigil also regularizes the head
toward the zero-shot text direction (`w0 = scale·(text(yes) − text(no))`), so with zero labels it *is* a
zero-shot classifier and it moves smoothly toward the data as labels arrive.

Multi-frame confirmation matters: in one study, requiring agreement across frames cut fire false alarms from
52% to 4% ([arXiv 2607.03131](https://arxiv.org/pdf/2607.03131)).

## 3. Models (measured on an M3 Pro, 36 GB, MPS)

| Model | License | Measured | Role in Vigil |
|---|---|---|---|
| SigLIP 2 base/16-224 (`google/siglip2-base-patch16-224`) | Apache-2.0 | 14 ms/crop, ~10 ms batched | Shared embedding backbone, zero-shot prior, per-watch heads |
| SigLIP 2 so400m/384 | Apache-2.0 | 134 ms/crop | Too slow for per-frame use |
| RF-DETR Nano / Small / Medium (`rfdetr`) | Apache-2.0 | ~40 / 48 / 60 ms per frame | COCO detector (person, car, dog, …) |
| OWLv2 base (`google/owlv2-base-patch16-ensemble`) | Apache-2.0 | 437 ms per frame | Open-vocabulary detection, region proposals |
| Grounding DINO tiny | Apache-2.0 | 765 ms per frame | Not used (slower than OWLv2 here) |
| Qwen3.5-4B / 9B, 4-bit MLX | Apache-2.0 | 3–5 s per answer when the GPU is idle; 10–17 s per crop while cameras run | Local brain: compile, label, verify |
| Claude Opus 5.5 (`claude-opus-5-5`) | API | not measured here (no key on this machine) | Cloud brain: best judgment; structured JSON output |

On the demo shelf, both local Qwen sizes labeled 12 of 12 full/empty bin crops correctly. Batching 6 crops into a
numbered "contact sheet" image cuts VLM calls about 6×. Label wording matters a lot for the zero-shot prior:
"an empty blue bin" vs "a blue bin full of boxes" separates cleanly (p = 0.01 vs 0.90), while adding location words
("…on the top shelf") collapses it. The compiler prompt therefore asks for short visual labels with no locations.

**Models considered and not used by default**
- **SAM 3 / 3.1:** best zero-shot segmentation. Gated, 848M parameters, slow on MPS; a good future labeler.
- **YOLOE-26 / YOLO-World:** real-time open vocabulary, but AGPL (Ultralytics) and YOLOE-26 bundles Apple's
  research-only MobileCLIP2 text encoder. Avoid for a commercial product unless licensed.
- **Gemini:** strongest cloud labeler with native boxes (`box_2d`); a natural third brain.
- **DINOv3 / PE-Core:** strong linear-probe backbones. DINOv3's license requires attribution and is gated;
  SigLIP 2 was chosen because it gives text and image embeddings in one Apache-licensed model.

## 4. Camera connectivity

- **Covered by RTSP/ONVIF:** Reolink (wired), Tapo (wired models), Amcrest, Hikvision, Dahua, Axis, Hanwha,
  UniFi Protect (RTSPS), and many Eufy models. Ingest best practice: TCP transport, the sub-stream for analysis,
  ~5 fps, a decode thread that keeps only the latest frame, and reconnects with backoff. Vigil does all of this.
- **Closed ecosystems:** Ring (ring-mqtt / go2rtc, unofficial), Nest (SDM API, WebRTC on new models), Wyze
  (IDisposable docker-wyze-bridge fork), Arlo (Scrypted plugins). Skip Blink and SimpliSafe.
- **Recommended edge pattern:** a box that runs go2rtc or MediaMTX to restream each camera once, with Vigil reading
  the restream. Vigil's "phone or laptop" camera streams frames from a browser tab, so you can start with no
  hardware at all.

## 5. Privacy and law (not legal advice)

- **GDPR:** see EDPB Guidelines 3/2019. A home camera that covers public space loses the household exemption.
- **EU AI Act Art. 5:** bans emotion recognition at work and biometric categorisation.
- **BIPA (Illinois) and similar laws:** keep face identification out. Vigil v1 does no face recognition.
- **Workplace notice:** NY Civil Rights Law §52-c requires written notice to employees; CT and DE have similar laws.
- **Hikvision / Dahua:** NDAA §889 and the June 2026 FCC order bar import and marketing. Existing installs keep
  working, but don't build B2B kits around them.
- **Data flow:** labeled crops and alert frames go to the cloud only when the Claude brain is selected. The local
  brain keeps everything on the machine.
