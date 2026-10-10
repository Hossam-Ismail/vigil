"""Same words, two definitions: can a watch head learn a subjective threshold from examples?

Request: "tell me when the blue bin is running low". Text prior: "a nearly empty blue bin" vs
"a well stocked blue bin". User A means "below 50%", user B means "below 20%". We measure test accuracy
of the zero-shot head and of trained heads after n labeled examples, averaged over random draws.
"""

import json
import sys

import numpy as np

from vigil.cameras.demo import ShelfScene
from vigil.learning.heads import sigmoid, train_head
from vigil.perception.embedder import get_embedder
from vigil.perception.geometry import crop

rng = np.random.default_rng(0)
scene = ShelfScene(seed=11)
scene.set_auto(False)
BOX = (0.10, 0.40, 0.367, 0.673)  # bin A-01 region, as Vigil's locator found it

N = 480
levels = rng.uniform(0, 1, N)
times = 1_700_000_000 + rng.uniform(0, 3600, N)  # different lighting drift and sensor noise per frame
crops = []
for lvl, t in zip(levels, times):
    scene.set_level("A-01", float(lvl))
    scene.hand_until = 0
    crops.append(crop(scene.render(now=float(t)), BOX))

emb = get_embedder()
X = emb.embed_images(crops)
w0, b0 = emb.zero_shot_direction("a nearly empty blue bin", "a well stocked blue bin")

test = np.arange(N) >= 280  # last 200 frames are the held-out test set
pool = np.flatnonzero(~test)

results = {}
for name, cut in (("A: low = below 50%", 0.5), ("B: low = below 20%", 0.2)):
    y = (levels < cut).astype(int)
    zs = ((sigmoid(X[test] @ w0 + b0) >= 0.5).astype(int) == y[test]).mean()
    curve = {"0": round(float(zs), 3)}
    for n in (4, 8, 16, 32):
        accs = []
        for trial in range(30):
            r = np.random.default_rng(100 + trial)
            idx = r.choice(pool, size=n, replace=False)
            head = train_head(X[idx], y[idx], w0, b0)
            pred = (head.proba(X[test]) >= head.threshold).astype(int)
            accs.append((pred == y[test]).mean())
        curve[str(n)] = round(float(np.mean(accs)), 3)
    results[name] = curve

print(json.dumps({"test_frames": int(test.sum()), "weights": int(w0.size) + 1, "results": results}, indent=1))
