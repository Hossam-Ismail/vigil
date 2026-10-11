"""`python -m vigil` starts the server."""

from __future__ import annotations

import asyncio
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
    servers = [uvicorn.Server(uvicorn.Config("vigil.api:app", host=settings.host, port=settings.port,
                                             log_level="info", access_log=False))]
    if settings.lan_https_port:
        # the same app over HTTPS on the Wi-Fi, for phones; it shares the main server's startup (lifespan off)
        from .lan import ensure_cert, lan_url

        cert, key = ensure_cert()
        servers.append(uvicorn.Server(uvicorn.Config("vigil.api:app", host="0.0.0.0", port=settings.lan_https_port,
                                                     ssl_certfile=cert, ssl_keyfile=key, lifespan="off",
                                                     log_level="warning", access_log=False)))
        logging.getLogger("vigil").info("phones on this Wi-Fi: %s", lan_url())

    async def serve() -> None:
        await asyncio.gather(*(s.serve() for s in servers))

    asyncio.run(serve())


if __name__ == "__main__":
    main()
