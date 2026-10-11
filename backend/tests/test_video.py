from pathlib import Path

import numpy as np
import pytest

CACHED = (Path.home() / ".cache/huggingface/hub/models--microsoft--xclip-base-patch32").exists()


def test_sample_spreads_frames():
    from vigil.perception.video import VideoText

    frames = [np.full((4, 4, 3), i, np.uint8) for i in range(3)]
    picked = VideoText.sample(frames, 8)
    assert len(picked) == 8 and picked[0][0, 0, 0] == 0 and picked[-1][0, 0, 0] == 2


@pytest.mark.skipif(not CACHED, reason="X-CLIP weights not downloaded")
def test_score_returns_probabilities():
    from vigil.perception.video import VideoText

    vt = VideoText(device="cpu")
    frames = [np.random.default_rng(i).integers(0, 255, (224, 224, 3), np.uint8) for i in range(9)]
    probs, ms = vt.score(frames, ["a person waving", "an empty room"])
    assert len(probs) == 2 and abs(sum(probs) - 1) < 1e-4 and ms > 0
