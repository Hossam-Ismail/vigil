"""Pick an existing, already-trained model for a watch. No training, no labeling, nothing from the camera.

  "is X true / is X happening"  -> Google SigLIP 2, zero-shot: each frame is compared with the YES and NO wording
  common objects (COCO classes) -> RF-DETR trained on COCO (118k public images, 80 classes)
  any other named object        -> Google OWLv2, an open-vocabulary detector that finds objects from a description
  an object with a condition    -> the detector finds it, SigLIP 2 judges the condition on each one
"""

from __future__ import annotations

from ..config import settings
from ..perception.detector import coco_class_for
from ..schemas import WatchSpec

SIGLIP = {"name": "Google SigLIP 2", "url": "https://huggingface.co/google/siglip2-base-patch16-224",
          "trained_on": "billions of public image-and-caption pairs"}
COCO = {"name": "RF-DETR (COCO)", "url": "https://cocodataset.org",
        "trained_on": "COCO: 118,000 public images, 80 everyday object classes"}
OWL = {"name": "Google OWLv2", "url": "https://huggingface.co/google/owlv2-base-patch16-ensemble",
       "trained_on": "billions of public image-and-caption pairs; finds objects from a text description"}


def choose(spec: WatchSpec) -> dict:
    """What runs this watch and why, in a form the review screen can show."""
    if spec.library:
        from ..perception.library import BY_ID

        m = BY_ID[spec.library["id"]]
        if m.id == "hardhat" and "NO-Hardhat" in (spec.library.get("yes") or []):
            return {"state": "existing", "models": [COCO, {"name": m.repo.split("/")[-1], "url": m.card()["url"], "trained_on": "public data"}],
                    "how": "Finds every person, then checks whether a hard hat is on each head."}
        what = spec.positive_label or ", ".join(spec.library.get("yes") or [])
        how = (f"Watches every 2-second clip for {what}." if m.kind == "video" else
               f"Looks for {what} in every frame.")
        return {"state": "existing", "models": [{"name": m.repo.split("/")[-1], "url": m.card()["url"],
                                                 "trained_on": "public data"}], "how": how}
    if spec.kind == "state":
        return {"state": "existing", "models": [SIGLIP], "how": "Each frame is compared with “" + spec.positive_label
                + "” versus “" + spec.negative_label + "”; the closer one is the answer."}
    detectors = [COCO if coco_class_for(t) else OWL for t in spec.targets] or [COCO]
    models = list({m["name"]: m for m in detectors}.values())
    if spec.target_question:
        models.append(SIGLIP)
        how = (f"Finds each {', '.join(spec.targets)}, then asks of each one: “{spec.target_question}”.")
    else:
        how = f"Finds and counts each {', '.join(spec.targets)} in view."
    return {"state": "existing", "models": models, "how": how}


def enabled() -> bool:
    return not settings.finetune
