"""`python -m vigil` starts the server."""

from __future__ import annotations

import logging
import os
from pathlib import Path


def load_env_file() -> None:
    """KEY=VALUE lines from vigil/.env (mail sender, keys). Never overrides what the shell already set."""
    path = Path(__file__).resolve().parents[2] / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> None:
    load_env_file()
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore", "transformers", "huggingface_hub", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    import uvicorn

    from .config import settings

    settings.ensure_dirs()
    uvicorn.run("vigil.api:app", host=settings.host, port=settings.port, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
