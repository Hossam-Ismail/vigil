"""`python -m vigil` starts the server."""

from __future__ import annotations

import logging
import os


def main() -> None:
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
