"""Fetch small slices of two real, CC BY 4.0 datasets for benchmarking Vigil's training.

PKLot (dronefreak/PKLot): fixed parking-lot cameras, every space labeled vacant/occupied; splits are by capture day.
Hard Hats (keremberke/hard-hat-detection): real construction/factory photos, heads labeled hardhat/no-hardhat.
"""
import json, random, sys, zipfile
from pathlib import Path
from huggingface_hub import hf_hub_download

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "data/bench")
OUT.mkdir(parents=True, exist_ok=True)
rng = random.Random(0)

def pklot(split, per_camera):
    meta = hf_hub_download("dronefreak/PKLot", f"data/images/{split}/metadata.jsonl", repo_type="dataset")
    rows = [json.loads(l) for l in open(meta)]
    picked = []
    for cam in ("PUCPR", "UFPR04", "UFPR05"):
        mine = [r for r in rows if r["file_name"].startswith(cam)]
        picked += rng.sample(mine, min(per_camera, len(mine)))
    d = OUT / "pklot" / split
    d.mkdir(parents=True, exist_ok=True)
    for r in picked:
        p = hf_hub_download("dronefreak/PKLot", f"data/images/{split}/{r['file_name']}", repo_type="dataset")
        (d / r["file_name"]).write_bytes(Path(p).read_bytes())
    (d / "metadata.jsonl").write_text("\n".join(json.dumps(r) for r in picked))
    print("pklot", split, len(picked), "frames")

pklot("train", 20)
pklot("test", 40)
z = hf_hub_download("keremberke/hard-hat-detection", "data/test.zip", repo_type="dataset")
with zipfile.ZipFile(z) as f:
    f.extractall(OUT / "hardhat")
print("hardhat extracted", sum(1 for _ in (OUT / "hardhat").rglob("*.jpg")), "images")
