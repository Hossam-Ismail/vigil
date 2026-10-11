"""Runtime configuration. Everything can be overridden with VIGIL_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _pick_device() -> str:
    forced = os.environ.get("VIGIL_DEVICE")
    if forced:
        return forced
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


@dataclass
class Settings:
    data_dir: Path = field(
        default_factory=lambda: Path(_env("VIGIL_DATA", str(Path(__file__).resolve().parents[2] / "data")))
    )
    host: str = field(default_factory=lambda: _env("VIGIL_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(_env("VIGIL_PORT", "8765")))

    # Perception
    embed_model: str = field(default_factory=lambda: _env("VIGIL_EMBED_MODEL", "google/siglip2-base-patch16-224"))
    coco_model: str = field(default_factory=lambda: _env("VIGIL_COCO_MODEL", "nano"))  # rf-detr size
    open_vocab_model: str = field(
        default_factory=lambda: _env("VIGIL_OPEN_VOCAB_MODEL", "google/owlv2-base-patch16-ensemble")
    )
    analysis_fps: float = field(default_factory=lambda: float(_env("VIGIL_ANALYSIS_FPS", "4")))
    open_vocab_interval_s: float = field(default_factory=lambda: float(_env("VIGIL_OPEN_VOCAB_INTERVAL", "1.0")))

    # Brain (the large model that compiles requests, labels data and verifies alerts)
    brain: str = field(default_factory=lambda: _env("VIGIL_BRAIN", "auto"))  # auto|anthropic|local|heuristic
    claude_model: str = field(default_factory=lambda: _env("VIGIL_CLAUDE_MODEL", "claude-opus-5-5"))
    # first one that is downloaded wins; set VIGIL_LOCAL_VLM to force a specific MLX model
    local_vlm: str = field(default_factory=lambda: _env(
        "VIGIL_LOCAL_VLM", "mlx-community/Qwen3.5-4B-MLX-4bit,mlx-community/Qwen3.5-9B-4bit"))

    # Learning
    label_budget: int = field(default_factory=lambda: int(_env("VIGIL_LABEL_BUDGET", "40")))
    collect_seconds: float = field(default_factory=lambda: float(_env("VIGIL_COLLECT_SECONDS", "15")))
    # off (default): every watch runs on an existing, already-trained model, live instantly, no training at all.
    # on: a model is fine-tuned per watch on public data (minutes of GPU per watch)
    finetune: bool = field(default_factory=lambda: _env("VIGIL_FINETUNE", "0") not in ("0", "false", "no"))
    finetune_epochs: int = field(default_factory=lambda: int(_env("VIGIL_FINETUNE_EPOCHS", "6")))
    finetune_images: int = field(default_factory=lambda: int(_env("VIGIL_FINETUNE_IMAGES", "450")))
    active_learning_per_hour: int = field(default_factory=lambda: int(_env("VIGIL_ACTIVE_LEARNING_PER_HOUR", "12")))

    # Recording
    history_interval_s: float = field(default_factory=lambda: float(_env("VIGIL_HISTORY_INTERVAL", "20")))
    history_max_frames: int = field(default_factory=lambda: int(_env("VIGIL_HISTORY_MAX", "1500")))
    verify_timeout_s: float = field(default_factory=lambda: float(_env("VIGIL_VERIFY_TIMEOUT", "20")))
    clip_pre_s: float = 6.0
    clip_post_s: float = 4.0
    clip_fps: float = 6.0

    device: str = field(default_factory=_pick_device)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "vigil.db"

    def ensure_dirs(self) -> None:
        for sub in ("", "media", "models", "history", "demo"):
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)


settings = Settings()
